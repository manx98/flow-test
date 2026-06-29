package device

import (
	"context"
	"image"
	"os"
	"strconv"
	"testing"
)

func TestPVEDeviceIntegration(t *testing.T) {
	if os.Getenv("PVE_TEST") != "1" {
		t.Skip("set PVE_TEST=1 to run the PVE integration test")
	}
	port, err := strconv.Atoi(envDefault("PVE_PORT", "8006"))
	if err != nil {
		t.Fatal(err)
	}
	vmid, err := strconv.Atoi(envDefault("PVE_VMID", "100"))
	if err != nil {
		t.Fatal(err)
	}
	connectTimeout, err := strconv.Atoi(envDefault("PVE_CONNECT_TIMEOUT", "8"))
	if err != nil {
		t.Fatal(err)
	}
	firstUpdateTimeout, err := strconv.Atoi(envDefault("PVE_FIRST_UPDATE_TIMEOUT", "8"))
	if err != nil {
		t.Fatal(err)
	}
	dev, err := NewPVEDevice(map[string]any{
		"host":                 envDefault("PVE_HOST", "127.0.0.1"),
		"port":                 port,
		"node":                 envDefault("PVE_NODE", "pve"),
		"vmid":                 vmid,
		"vmtype":               envDefault("PVE_VMTYPE", "qemu"),
		"username":             envDefault("PVE_USERNAME", "root@pam"),
		"password":             os.Getenv("PVE_PASSWORD"),
		"verify_tls":           envDefault("PVE_VERIFY_TLS", "false") == "true",
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
}

func envDefault(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
