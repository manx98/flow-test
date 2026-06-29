package device

import (
	"context"
	"encoding/json"
	"image"
	"image/color"
	"testing"
)

func TestUnsupportedRefJSON(t *testing.T) {
	ref := NewUnsupportedRef("rdp", map[string]any{"host": "127.0.0.1"}, 1024, 768)
	data, err := json.Marshal(ref)
	if err != nil {
		t.Fatalf("Marshal() error = %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if out["resource"] != "device" || out["kind"] != "rdp" || out["unsupported"] != true {
		t.Fatalf("ref JSON = %#v", out)
	}
	if out["Device"] != nil {
		t.Fatalf("Device field should not be serialized: %#v", out)
	}
}

func TestSessionStoreLifecycle(t *testing.T) {
	store := NewSessionStore()
	session, err := store.Create("unknown", map[string]any{"width": float64(1600), "height": float64(900), "password": "secret"}, "demo", 7)
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if session.ID == "" || session.Kind != "unknown" || session.Project != "demo" || session.NodeID != 7 {
		t.Fatalf("session = %#v", session)
	}
	if session.Width != 1600 || session.Height != 900 || !session.Unsupported {
		t.Fatalf("session size/support = %#v", session)
	}
	ref, ok := store.Ref(session.ID)
	if !ok || ref.Kind != "unknown" || ref.Width != 1600 || ref.Height != 900 || !ref.Unsupported {
		t.Fatalf("ref = %#v ok=%v", ref, ok)
	}
	if _, ok := ref.Config["password"]; ok {
		t.Fatalf("public ref leaked password: %#v", ref.Config)
	}
	byNode, ok := store.RefByProjectNode("demo", 7)
	if !ok || byNode.Kind != "unknown" || byNode.Width != 1600 {
		t.Fatalf("RefByProjectNode() = %#v ok=%v", byNode, ok)
	}
	if !store.Delete(session.ID) {
		t.Fatalf("Delete() = false")
	}
	if _, ok := store.Get(session.ID); ok {
		t.Fatalf("session still present")
	}
}

func TestSessionStoreStaticImageDevice(t *testing.T) {
	store := NewSessionStore()
	img := image.NewRGBA(image.Rect(0, 0, 3, 2))
	img.Set(1, 1, color.RGBA{R: 200, A: 255})
	session, err := store.Create("static_image", map[string]any{"image": img, "width": 3, "height": 2}, "demo", 8)
	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if session.Unsupported || session.Device == nil {
		t.Fatalf("session support/device = %#v / %#v", session.Unsupported, session.Device)
	}
	ref, ok := store.RefByProjectNode("demo", 8)
	if !ok || ref.Unsupported || ref.Device == nil {
		t.Fatalf("RefByProjectNode() = %#v ok=%v", ref, ok)
	}
	var captured *image.RGBA
	if err := ref.Device.Capture(context.Background(), &captured); err != nil {
		t.Fatalf("Capture() error = %v", err)
	}
	if captured.Bounds().Dx() != 3 || captured.Bounds().Dy() != 2 {
		t.Fatalf("captured bounds = %v", captured.Bounds())
	}
	if session.Width != 3 || session.Height != 2 {
		t.Fatalf("session size = %dx%d", session.Width, session.Height)
	}
}

func TestStaticImageDeviceCaptureReusesRGBA(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 3, 2))
	dev := &StaticImageDevice{image: source}
	var dst *image.RGBA
	if err := dev.Capture(context.Background(), &dst); err != nil {
		t.Fatalf("Capture() error = %v", err)
	}
	first := dst
	if err := dev.Capture(context.Background(), &dst); err != nil {
		t.Fatalf("second Capture() error = %v", err)
	}
	if dst != first {
		t.Fatalf("Capture() did not reuse same-size dst")
	}
	dst = image.NewRGBA(image.Rect(0, 0, 1, 1))
	if err := dev.Capture(context.Background(), &dst); err != nil {
		t.Fatalf("resized Capture() error = %v", err)
	}
	if dst == nil || dst.Bounds().Dx() != 3 || dst.Bounds().Dy() != 2 {
		t.Fatalf("resized dst bounds = %v", dst.Bounds())
	}
}
