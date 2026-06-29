package device

import (
	"context"
	"crypto/tls"
	"fmt"
	"image"
	"image/color"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	vnc "github.com/kward/go-vnc"
	"github.com/kward/go-vnc/buttons"
	"github.com/kward/go-vnc/keys"
)

type VNCDevice struct {
	conn   *vnc.ClientConn
	raw    net.Conn
	events chan vnc.ServerMessage
	ready  chan struct{}

	mu     sync.Mutex
	opMu   sync.Mutex
	img    *image.RGBA
	width  int
	height int
	closed bool

	mouseButtons buttons.Button
	lastX        int
	lastY        int
}

func NewVNCDevice(config map[string]any) (*VNCDevice, error) {
	timeout := time.Duration(intFromConfig(config, "connect_timeout", 30)) * time.Second
	raw, err := dialVNC(config, timeout)
	if err != nil {
		return nil, err
	}
	events := make(chan vnc.ServerMessage, 16)
	cfg := vnc.NewClientConfig(stringConfig(config, "password"))
	cfg.Exclusive = boolFromConfig(config, "exclusive", false)
	cfg.ServerMessageCh = events
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	conn, err := vnc.Connect(ctx, raw, cfg)
	if err != nil {
		_ = raw.Close()
		return nil, err
	}
	dev := &VNCDevice{
		conn:   conn,
		raw:    raw,
		events: events,
		ready:  make(chan struct{}, 1),
		width:  int(conn.FramebufferWidth()),
		height: int(conn.FramebufferHeight()),
	}
	if dev.width <= 0 || dev.height <= 0 {
		_ = conn.Close()
		return nil, fmt.Errorf("invalid vnc framebuffer size %dx%d", dev.width, dev.height)
	}
	dev.img = image.NewRGBA(image.Rect(0, 0, dev.width, dev.height))
	if err := dev.conn.SetPixelFormat(vncRGBPixelFormat()); err != nil {
		_ = dev.Close()
		return nil, err
	}
	go dev.listen()
	firstTimeout := time.Duration(intFromConfig(config, "first_update_timeout", 10)) * time.Second
	if err := dev.requestUpdate(false); err != nil {
		_ = dev.Close()
		return nil, err
	}
	if err := dev.waitForFrame(context.Background(), firstTimeout); err != nil {
		_ = dev.Close()
		return nil, err
	}
	return dev, nil
}

func (d *VNCDevice) Capture(ctx context.Context, dst **image.RGBA) error {
	if err := d.requestUpdate(true); err != nil {
		return err
	}
	waitCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	_ = d.waitForFrame(waitCtx, 2*time.Second)
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.img == nil {
		return fmt.Errorf("vnc device has no framebuffer")
	}
	img := EnsureRGBA(dst, d.img.Bounds())
	copy(img.Pix, d.img.Pix)
	return nil
}

func (d *VNCDevice) Size() (int, int) {
	if d == nil {
		return 0, 0
	}
	return d.width, d.height
}

func (d *VNCDevice) MouseMove(ctx context.Context, x, y int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	d.opMu.Lock()
	defer d.opMu.Unlock()
	return d.sendPointerEventLocked(d.mouseButtons, x, y)
}

func (d *VNCDevice) MouseDown(ctx context.Context, button Button, x, y int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	d.opMu.Lock()
	defer d.opMu.Unlock()
	d.mouseButtons = addVNCButton(d.mouseButtons, vncButton(button))
	return d.sendPointerEventLocked(d.mouseButtons, x, y)
}

func (d *VNCDevice) MouseUp(ctx context.Context, button Button, x, y int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	d.opMu.Lock()
	defer d.opMu.Unlock()
	d.mouseButtons = removeVNCButton(d.mouseButtons, vncButton(button))
	return d.sendPointerEventLocked(d.mouseButtons, x, y)
}

func (d *VNCDevice) MouseWheel(ctx context.Context, delta int) error {
	if delta == 0 {
		return nil
	}
	if err := ctx.Err(); err != nil {
		return err
	}

	wheelButton := buttons.Four
	if delta < 0 {
		wheelButton = buttons.Five
	}

	d.opMu.Lock()
	defer d.opMu.Unlock()

	// VNC wheel is also represented as a temporary button mask.
	// Use the last cursor position instead of forcing the pointer to 0,0.
	if err := d.sendPointerEventLocked(addVNCButton(d.mouseButtons, wheelButton), d.lastX, d.lastY); err != nil {
		return err
	}
	return d.sendPointerEventLocked(d.mouseButtons, d.lastX, d.lastY)
}

func (d *VNCDevice) Drag(ctx context.Context, button Button, x1, y1, x2, y2 int) error {
	if err := d.MouseMove(ctx, x1, y1); err != nil {
		return err
	}
	if err := sleepContext(ctx, 30*time.Millisecond); err != nil {
		return err
	}
	if err := d.MouseDown(ctx, button, x1, y1); err != nil {
		return err
	}
	if err := sleepContext(ctx, 80*time.Millisecond); err != nil {
		return err
	}

	const steps = 12
	for i := 1; i <= steps; i++ {
		x := x1 + (x2-x1)*i/steps
		y := y1 + (y2-y1)*i/steps
		if err := d.MouseMove(ctx, x, y); err != nil {
			return err
		}
		if err := sleepContext(ctx, 15*time.Millisecond); err != nil {
			return err
		}
	}

	if err := sleepContext(ctx, 50*time.Millisecond); err != nil {
		return err
	}
	return d.MouseUp(ctx, button, x2, y2)
}

func (d *VNCDevice) KeyDown(ctx context.Context, key Key) error {
	return d.keyEvent(ctx, key, true)
}

func (d *VNCDevice) KeyUp(ctx context.Context, key Key) error {
	return d.keyEvent(ctx, key, false)
}

func (d *VNCDevice) TypeText(ctx context.Context, text string) error {
	ks, err := keys.TextToKeys(text)
	if err != nil {
		return err
	}
	for _, k := range ks {
		if err := d.keySym(ctx, k, true); err != nil {
			return err
		}
		if err := d.keySym(ctx, k, false); err != nil {
			return err
		}
	}
	return nil
}

func (d *VNCDevice) Close() error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.closed {
		return nil
	}
	d.closed = true
	if d.conn != nil {
		return d.conn.Close()
	}
	if d.raw != nil {
		return d.raw.Close()
	}
	return nil
}

func (d *VNCDevice) listen() {
	go func() {
		_ = d.conn.ListenAndHandle()
	}()
	for msg := range d.events {
		if update, ok := msg.(*vnc.FramebufferUpdate); ok {
			d.applyFramebufferUpdate(update)
			select {
			case d.ready <- struct{}{}:
			default:
			}
		}
	}
}

func (d *VNCDevice) applyFramebufferUpdate(update *vnc.FramebufferUpdate) {
	d.mu.Lock()
	defer d.mu.Unlock()
	for _, rect := range update.Rects {
		raw, ok := rect.Enc.(*vnc.RawEncoding)
		if !ok {
			continue
		}
		for y := 0; y < int(rect.Height); y++ {
			for x := 0; x < int(rect.Width); x++ {
				idx := y*int(rect.Width) + x
				if idx >= len(raw.Colors) {
					continue
				}
				c := raw.Colors[idx]
				d.img.SetRGBA(int(rect.X)+x, int(rect.Y)+y, imageColor(c.R, c.G, c.B))
			}
		}
	}
}

func imageColor(r, g, b uint16) color.RGBA {
	return color.RGBA{R: vncColor8(r), G: vncColor8(g), B: vncColor8(b), A: 255}
}

func vncColor8(v uint16) uint8 {
	if v > 255 {
		return uint8(v >> 8)
	}
	return uint8(v)
}

func vncRGBPixelFormat() vnc.PixelFormat {
	return vnc.PixelFormat{
		BPP:        32,
		Depth:      24,
		BigEndian:  false,
		TrueColor:  true,
		RedMax:     255,
		GreenMax:   255,
		BlueMax:    255,
		RedShift:   16,
		GreenShift: 8,
		BlueShift:  0,
	}
}

func (d *VNCDevice) requestUpdate(incremental bool) error {
	d.opMu.Lock()
	defer d.opMu.Unlock()
	return d.conn.FramebufferUpdateRequest(incremental, 0, 0, uint16(d.width), uint16(d.height))
}

func (d *VNCDevice) waitForFrame(ctx context.Context, timeout time.Duration) error {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case <-d.ready:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return fmt.Errorf("timeout waiting for vnc framebuffer update")
	}
}

func (d *VNCDevice) pointerEvent(ctx context.Context, button buttons.Button, x, y int) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	d.opMu.Lock()
	defer d.opMu.Unlock()
	return d.sendPointerEventLocked(button, x, y)
}

func (d *VNCDevice) sendPointerEventLocked(button buttons.Button, x, y int) error {
	d.lastX = x
	d.lastY = y
	return d.conn.PointerEvent(button, clampUint16(x), clampUint16(y))
}

func addVNCButton(mask, button buttons.Button) buttons.Button {
	return buttons.Button(uint8(mask) | uint8(button))
}

func removeVNCButton(mask, button buttons.Button) buttons.Button {
	return buttons.Button(uint8(mask) &^ uint8(button))
}

func sleepContext(ctx context.Context, timeout time.Duration) error {
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func (d *VNCDevice) keyEvent(ctx context.Context, key Key, down bool) error {
	ks, ok := vncKey(key)
	if !ok {
		return fmt.Errorf("unsupported VNC key %q", key)
	}
	return d.keySym(ctx, ks, down)
}

func (d *VNCDevice) keySym(ctx context.Context, key keys.Key, down bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	d.opMu.Lock()
	defer d.opMu.Unlock()
	return d.conn.KeyEvent(key, down)
}

func dialVNC(config map[string]any, timeout time.Duration) (net.Conn, error) {
	if rawURL := stringConfig(config, "url"); rawURL != "" {
		u, err := url.Parse(rawURL)
		if err != nil {
			return nil, err
		}
		switch u.Scheme {
		case "ws", "wss":
			return dialVNCWebSocket(rawURL, config, timeout)
		case "tcp", "vnc":
			return net.DialTimeout("tcp", u.Host, timeout)
		default:
			return nil, fmt.Errorf("unsupported vnc url scheme %q", u.Scheme)
		}
	}
	host := stringConfig(config, "host")
	if host == "" {
		return nil, fmt.Errorf("novnc device requires url or host")
	}
	port := intFromConfig(config, "port", 5900)
	return net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), timeout)
}

func dialVNCWebSocket(rawURL string, config map[string]any, timeout time.Duration) (net.Conn, error) {
	dialer := websocket.Dialer{HandshakeTimeout: timeout}
	if boolFromConfig(config, "insecure_tls", false) || !boolFromConfig(config, "verify_tls", true) {
		dialer.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	header := http.Header{}
	if origin := stringConfig(config, "origin"); origin != "" {
		header.Set("Origin", origin)
	}
	if cookie := stringConfig(config, "cookie"); cookie != "" {
		header.Set("Cookie", cookie)
	}
	conn, _, err := dialer.Dial(rawURL, header)
	if err != nil {
		return nil, err
	}
	return &websocketNetConn{conn: conn}, nil
}

func vncButton(button Button) buttons.Button {
	switch button {
	case ButtonMiddle:
		return buttons.Middle
	case ButtonRight:
		return buttons.Right
	default:
		return buttons.Left
	}
}

func vncKey(key Key) (keys.Key, bool) {
	text := strings.ToLower(string(key))
	if ks, ok := vncNamedKeys[text]; ok {
		return ks, true
	}
	runes := []rune(string(key))
	if len(runes) == 1 {
		return keys.FromRune(runes[0])
	}
	return 0, false
}

func clampUint16(v int) uint16 {
	if v < 0 {
		return 0
	}
	if v > 65535 {
		return 65535
	}
	return uint16(v)
}

func boolFromConfig(config map[string]any, key string, fallback bool) bool {
	if config == nil {
		return fallback
	}
	switch v := config[key].(type) {
	case bool:
		return v
	case string:
		parsed, err := strconv.ParseBool(v)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

var vncNamedKeys = map[string]keys.Key{
	"esc":       keys.Escape,
	"escape":    keys.Escape,
	"backspace": keys.BackSpace,
	"tab":       keys.Tab,
	"enter":     keys.Return,
	"return":    keys.Return,
	"delete":    keys.Delete,
	"home":      keys.Home,
	"end":       keys.End,
	"pageup":    keys.PageUp,
	"pagedown":  keys.PageDown,
	"left":      keys.Left,
	"right":     keys.Right,
	"up":        keys.Up,
	"down":      keys.Down,
	"shift":     keys.ShiftLeft,
	"ctrl":      keys.ControlLeft,
	"control":   keys.ControlLeft,
	"alt":       keys.AltLeft,
	"space":     keys.Space,
}

type websocketNetConn struct {
	conn    *websocket.Conn
	readMu  sync.Mutex
	writeMu sync.Mutex
	reader  io.Reader
}

func (c *websocketNetConn) Read(p []byte) (int, error) {
	c.readMu.Lock()
	defer c.readMu.Unlock()
	for {
		if c.reader != nil {
			n, err := c.reader.Read(p)
			if err == io.EOF {
				c.reader = nil
				if n > 0 {
					return n, nil
				}
				continue
			}
			return n, err
		}
		msgType, reader, err := c.conn.NextReader()
		if err != nil {
			return 0, err
		}
		if msgType != websocket.BinaryMessage {
			continue
		}
		c.reader = reader
	}
}

func (c *websocketNetConn) Write(p []byte) (int, error) {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	err := c.conn.WriteMessage(websocket.BinaryMessage, p)
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func (c *websocketNetConn) Close() error {
	return c.conn.Close()
}

func (c *websocketNetConn) LocalAddr() net.Addr {
	return c.conn.LocalAddr()
}

func (c *websocketNetConn) RemoteAddr() net.Addr {
	return c.conn.RemoteAddr()
}

func (c *websocketNetConn) SetDeadline(t time.Time) error {
	if err := c.conn.SetReadDeadline(t); err != nil {
		return err
	}
	return c.conn.SetWriteDeadline(t)
}

func (c *websocketNetConn) SetReadDeadline(t time.Time) error {
	return c.conn.SetReadDeadline(t)
}

func (c *websocketNetConn) SetWriteDeadline(t time.Time) error {
	return c.conn.SetWriteDeadline(t)
}
