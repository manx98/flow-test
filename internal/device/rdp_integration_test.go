package device

import (
	"context"
	"image"
	"os"
	"strconv"
	"testing"
	"time"
)

func TestRDPDeviceIntegration(t *testing.T) {
	if os.Getenv("RDP_TEST") != "1" {
		t.Skip("set RDP_TEST=1 to run the RDP integration test")
	}
	port, err := strconv.Atoi(envDefault("RDP_PORT", "3389"))
	if err != nil {
		t.Fatal(err)
	}
	width, err := strconv.Atoi(envDefault("RDP_WIDTH", "1280"))
	if err != nil {
		t.Fatal(err)
	}
	height, err := strconv.Atoi(envDefault("RDP_HEIGHT", "800"))
	if err != nil {
		t.Fatal(err)
	}
	connectTimeout, err := strconv.Atoi(envDefault("RDP_CONNECT_TIMEOUT", "10"))
	if err != nil {
		t.Fatal(err)
	}
	firstUpdateTimeout, err := strconv.Atoi(envDefault("RDP_FIRST_UPDATE_TIMEOUT", "10"))
	if err != nil {
		t.Fatal(err)
	}
	dev, err := NewRDPDevice(map[string]any{
		"host":                 envDefault("RDP_HOST", "127.0.0.1"),
		"port":                 port,
		"username":             envDefault("RDP_USERNAME", ""),
		"password":             os.Getenv("RDP_PASSWORD"),
		"domain":               envDefault("RDP_DOMAIN", ""),
		"security_protocol":    envDefault("RDP_SECURITY_PROTOCOL", "auto"),
		"width":                width,
		"height":               height,
		"connect_timeout":      connectTimeout,
		"first_update_timeout": firstUpdateTimeout,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer dev.Close()
	var img *image.RGBA
	if err := dev.Capture(context.Background(), &img); err != nil {
		t.Fatal(err)
	}
	if img.Bounds().Dx() <= 0 || img.Bounds().Dy() <= 0 {
		t.Fatalf("empty capture bounds: %v", img.Bounds())
	}
	time.Sleep(2 * time.Second)
	if err := dev.Capture(context.Background(), &img); err != nil {
		t.Fatal(err)
	}
	if img.Bounds().Dx() <= 0 || img.Bounds().Dy() <= 0 {
		t.Fatalf("second capture empty bounds: %v", img.Bounds())
	}
}
