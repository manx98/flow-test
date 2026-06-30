package device

import (
	"context"
	"encoding/json"
	"image"
	"image/color"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"testing"

	"github.com/gorilla/websocket"
)

func TestPVEDeviceConnectsThroughVNCWebSocket(t *testing.T) {
	var sawCookie, sawCSRF bool
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api2/json/access/ticket":
			if r.Method != http.MethodPost {
				t.Errorf("login method = %s", r.Method)
			}
			if err := r.ParseForm(); err != nil {
				t.Errorf("ParseForm() error = %v", err)
			}
			if r.Form.Get("username") != "root@pam" || r.Form.Get("password") != "secret" {
				t.Errorf("login form = %v", r.Form)
			}
			writePVEJSON(w, map[string]any{
				"ticket":              "auth-ticket",
				"CSRFPreventionToken": "csrf-token",
			})
		case "/api2/json/nodes/pve/qemu/100/vncproxy":
			sawCookie = r.Header.Get("Cookie") == "PVEAuthCookie=auth-ticket"
			sawCSRF = r.Header.Get("CSRFPreventionToken") == "csrf-token"
			writePVEJSON(w, map[string]any{
				"ticket": "vnc-ticket",
				"port":   "5901",
			})
		case "/api2/json/nodes/pve/qemu/100/vncwebsocket":
			if r.Header.Get("Cookie") != "PVEAuthCookie=auth-ticket" {
				t.Errorf("websocket cookie = %q", r.Header.Get("Cookie"))
			}
			if r.URL.Query().Get("port") != "5901" || r.URL.Query().Get("vncticket") != "vnc-ticket" {
				t.Errorf("websocket query = %v", r.URL.Query())
			}
			serveTestRFBWebSocket(t, w, r)
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	host, port := splitTestServerHostPort(t, server.URL)
	dev, err := NewPVEDevice(map[string]any{
		"host":                 host,
		"port":                 port,
		"node":                 "pve",
		"vmid":                 100,
		"vmtype":               "qemu",
		"username":             "root@pam",
		"password":             "secret",
		"verify_tls":           false,
		"connect_timeout":      2,
		"first_update_timeout": 2,
	})
	if err != nil {
		t.Fatalf("NewPVEDevice() error = %v", err)
	}
	defer dev.Close()
	if !sawCookie || !sawCSRF {
		t.Fatalf("vncproxy auth headers cookie=%t csrf=%t", sawCookie, sawCSRF)
	}
	var img *image.RGBA
	if err := dev.Capture(context.Background(), &img); err != nil {
		t.Fatalf("Capture() error = %v", err)
	}
	if got := color.RGBAModel.Convert(img.At(0, 0)).(color.RGBA); got.R != 255 || got.G != 0 || got.B != 0 {
		t.Fatalf("pixel = %#v", got)
	}
}

func writePVEJSON(w http.ResponseWriter, data map[string]any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"data": data})
}

func splitTestServerHostPort(t *testing.T, rawURL string) (string, int) {
	t.Helper()
	u, err := url.Parse(rawURL)
	if err != nil {
		t.Fatal(err)
	}
	host, portText, err := net.SplitHostPort(u.Host)
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(portText)
	if err != nil {
		t.Fatal(err)
	}
	return host, port
}

func serveTestRFBWebSocket(t *testing.T, w http.ResponseWriter, r *http.Request) {
	t.Helper()
	conn, err := websocket.Upgrade(w, r, nil, 1024, 1024)
	if err != nil {
		t.Errorf("Upgrade() error = %v", err)
		return
	}
	defer conn.Close()
	rfb := &testRFBConn{conn: conn}
	rfb.write([]byte("RFB 003.008\n"))
	rfb.read(12)
	rfb.write([]byte{1, 2})
	rfb.read(1)
	rfb.write(make([]byte, 16))
	rfb.read(16)
	rfb.write(make([]byte, 4))
	rfb.read(1)
	rfb.write(serverInit(2, 2))
	rfb.read(8)
	rfb.read(20)
	rfb.read(20)
	rfb.read(10)
	rfb.write(framebufferUpdate(2, 2, []byte{
		0, 0, 255, 0, 0, 255, 0, 0,
		255, 0, 0, 0, 255, 255, 255, 0,
	}))
	rfb.read(10)
	rfb.write(framebufferUpdate(2, 2, []byte{
		0, 0, 255, 0, 0, 255, 0, 0,
		255, 0, 0, 0, 255, 255, 255, 0,
	}))
}
