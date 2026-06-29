package device

import (
	"context"
	"encoding/binary"
	"image"
	"image/color"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestVNCDeviceNoAuthCaptureAndInput(t *testing.T) {
	var mu sync.Mutex
	events := []byte{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Upgrade(w, r, nil, 1024, 1024)
		if err != nil {
			t.Errorf("Upgrade() error = %v", err)
			return
		}
		defer conn.Close()
		rfb := &testRFBConn{conn: conn}
		rfb.write([]byte("RFB 003.008\n"))
		rfb.read(12)
		rfb.write([]byte{1, 1})
		rfb.read(1)
		rfb.read(1)
		rfb.write(serverInit(2, 2))
		rfb.read(8)
		rfb.read(20)
		rfb.read(20)
		rfb.read(10)
		rfb.write(framebufferUpdate(2, 2, []byte{
			0, 255, 0, 0, 0, 0, 255, 0,
			0, 0, 0, 255, 0, 255, 255, 255,
		}))
		rfb.read(10)
		rfb.write(framebufferUpdate(2, 2, []byte{
			0, 255, 0, 0, 0, 0, 255, 0,
			0, 0, 0, 255, 0, 255, 255, 255,
		}))
		for i := 0; i < 5; i++ {
			msg := rfb.read(1)
			mu.Lock()
			events = append(events, msg[0])
			mu.Unlock()
			switch msg[0] {
			case 4:
				rfb.read(7)
			case 5:
				rfb.read(5)
			default:
				return
			}
		}
	}))
	defer server.Close()

	url := "ws" + server.URL[len("http"):]
	dev, err := NewVNCDevice(map[string]any{"url": url, "connect_timeout": 2, "first_update_timeout": 2})
	if err != nil {
		t.Fatalf("NewVNCDevice() error = %v", err)
	}
	defer dev.Close()
	var img *image.RGBA
	if err := dev.Capture(context.Background(), &img); err != nil {
		t.Fatalf("Capture() error = %v", err)
	}
	if got := color.RGBAModel.Convert(img.At(0, 0)).(color.RGBA); got.R != 255 || got.G != 0 || got.B != 0 {
		t.Fatalf("pixel = %#v", got)
	}
	if err := dev.MouseMove(context.Background(), 1, 1); err != nil {
		t.Fatalf("MouseMove() error = %v", err)
	}
	if err := dev.MouseDown(context.Background(), ButtonLeft, 1, 1); err != nil {
		t.Fatalf("MouseDown() error = %v", err)
	}
	if err := dev.MouseUp(context.Background(), ButtonLeft, 1, 1); err != nil {
		t.Fatalf("MouseUp() error = %v", err)
	}
	if err := dev.KeyDown(context.Background(), Key("a")); err != nil {
		t.Fatalf("KeyDown() error = %v", err)
	}
	if err := dev.KeyUp(context.Background(), Key("a")); err != nil {
		t.Fatalf("KeyUp() error = %v", err)
	}
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		n := len(events)
		mu.Unlock()
		if n >= 5 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(events) < 5 || events[0] != 5 || events[3] != 4 {
		t.Fatalf("events = %#v", events)
	}
}

type testRFBConn struct {
	conn *websocket.Conn
	rx   []byte
}

func (c *testRFBConn) read(n int) []byte {
	for len(c.rx) < n {
		_, reader, err := c.conn.NextReader()
		if err != nil {
			return nil
		}
		buf := make([]byte, 4096)
		for {
			read, err := reader.Read(buf)
			if read > 0 {
				c.rx = append(c.rx, buf[:read]...)
			}
			if err != nil {
				break
			}
		}
	}
	out := append([]byte(nil), c.rx[:n]...)
	c.rx = c.rx[n:]
	return out
}

func (c *testRFBConn) write(data []byte) {
	_ = c.conn.WriteMessage(websocket.BinaryMessage, data)
}

func serverInit(width, height int) []byte {
	msg := make([]byte, 24)
	binary.BigEndian.PutUint16(msg[0:2], uint16(width))
	binary.BigEndian.PutUint16(msg[2:4], uint16(height))
	msg[4] = 32
	msg[5] = 24
	msg[6] = 0
	msg[7] = 1
	binary.BigEndian.PutUint16(msg[8:10], 255)
	binary.BigEndian.PutUint16(msg[10:12], 255)
	binary.BigEndian.PutUint16(msg[12:14], 255)
	msg[14] = 16
	msg[15] = 8
	msg[16] = 0
	return msg
}

func framebufferUpdate(width, height int, pixels []byte) []byte {
	msg := make([]byte, 4+12+len(pixels))
	msg[0] = 0
	binary.BigEndian.PutUint16(msg[2:4], 1)
	binary.BigEndian.PutUint16(msg[8:10], uint16(width))
	binary.BigEndian.PutUint16(msg[10:12], uint16(height))
	copy(msg[16:], pixels)
	return msg
}
