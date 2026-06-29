package jsplugin

import (
	"context"
	"fmt"
	"image"
	"image/color"
	"strings"
	"testing"
	"time"

	"flow-test-go/internal/device"
)

func TestRuntimeGetArgSetResultAndLog(t *testing.T) {
	rt := NewRuntime()
	resp, err := rt.Run(context.Background(), Request{
		Code: "const name = getArg('name', 'nobody'); log(name); setResult('ok', name === 'alice')",
		Args: map[string]any{"name": "alice"},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != true {
		t.Fatalf("ok result = %#v", resp.Results["ok"])
	}
	if len(resp.Logs) != 1 || resp.Logs[0] != "alice" {
		t.Fatalf("logs = %#v", resp.Logs)
	}
}

func TestRuntimeInterruptsInfiniteLoop(t *testing.T) {
	rt := &Runtime{Timeout: 10 * time.Millisecond}
	_, err := rt.Run(context.Background(), Request{Code: "while (true) {}"})
	if err == nil {
		t.Fatalf("Run() error = nil, want timeout")
	}
}

func TestRuntimeDisablesEval(t *testing.T) {
	_, err := NewRuntime().Run(context.Background(), Request{Code: "eval('1 + 1')"})
	if err == nil {
		t.Fatalf("Run() error = nil, want disabled eval error")
	}
}

func TestRuntimeRejectsEmptyResultName(t *testing.T) {
	_, err := NewRuntime().Run(context.Background(), Request{Code: "setResult('', true)"})
	if err == nil {
		t.Fatalf("Run() error = nil, want empty result name error")
	}
}

func TestRuntimeWrapsDeviceArg(t *testing.T) {
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
const found = pc.findImage('button.png')
pc.click({x: 10, y: 20})
pc.type('hello')
pc.hotkey('ctrl+c')
setResult('ok', found.ok === false && pc.raw === undefined)
`,
		Args: map[string]any{
			"pc": map[string]any{"resource": "device", "kind": "rdp", "unsupported": true},
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != true {
		t.Fatalf("ok result = %#v", resp.Results["ok"])
	}
	if len(resp.Logs) != 3 {
		t.Fatalf("logs = %#v, want 3 planned actions", resp.Logs)
	}
}

func TestRuntimeWrapsDeviceRefArg(t *testing.T) {
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: "const pc = getArg('pc'); setResult('kind', pc.kind); setResult('rawMissing', pc.raw === undefined)",
		Args: map[string]any{
			"pc": device.NewUnsupportedRef("vmware", map[string]any{"host": "esxi"}, 1280, 720),
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["kind"] != "vmware" || resp.Results["rawMissing"] != true {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWrapperUsesRealDevice(t *testing.T) {
	dev := &fakeDevice{}
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
pc.click({x: 10, y: 20})
pc.type('hello')
pc.hotkey('ctrl+c')
setResult('ok', pc.raw === undefined)
`,
		Args: map[string]any{
			"pc": device.Ref{Resource: "device", Kind: "rdp", Device: dev},
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != true {
		t.Fatalf("ok result = %#v", resp.Results["ok"])
	}
	if len(resp.Logs) != 0 {
		t.Fatalf("logs = %#v, want no planned logs", resp.Logs)
	}
	log := strings.Join(dev.calls, "|")
	for _, want := range []string{
		"move 10 20",
		"down left 10 20",
		"up left 10 20",
		"type hello",
		"keyDown ctrl",
		"keyDown c",
		"keyUp c",
		"keyUp ctrl",
	} {
		if !strings.Contains(log, want) {
			t.Fatalf("device calls missing %q: %s", want, log)
		}
	}
}

func TestRuntimeDeviceWrapperFindImageUsesCapture(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 6, 6))
	fillImage(source, colorRGBA(1, 1, 1))
	fillImageRect(source, image.Rect(2, 3, 4, 5), colorRGBA(220, 10, 10))
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillImage(template, colorRGBA(220, 10, 10))
	dev := &fakeDevice{img: source}
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
const tmpl = getArg('template')
const found = pc.findImage(tmpl, {threshold: 0.99})
setResult('ok', found.ok)
setResult('x', found.rect.x)
setResult('y', found.rect.y)
setResult('px', found.point.X || found.point.x)
`,
		Args: map[string]any{
			"pc":       device.Ref{Resource: "device", Kind: "rdp", Device: dev},
			"template": template,
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != true || resp.Results["x"] != int64(2) || resp.Results["y"] != int64(3) {
		t.Fatalf("results = %#v", resp.Results)
	}
	if len(dev.calls) == 0 || dev.calls[0] != "capture" {
		t.Fatalf("device calls = %#v", dev.calls)
	}
}

func TestRuntimeDeviceWrapperFindImageUsesMask(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 6, 4))
	fillImage(source, colorRGBA(1, 1, 1))
	source.SetRGBA(2, 1, colorRGBA(220, 0, 0))
	source.SetRGBA(3, 1, colorRGBA(0, 0, 220))
	template := image.NewRGBA(image.Rect(0, 0, 2, 1))
	template.SetRGBA(0, 0, colorRGBA(220, 0, 0))
	template.SetRGBA(1, 0, colorRGBA(0, 220, 0))
	mask := image.NewRGBA(image.Rect(0, 0, 2, 1))
	mask.SetRGBA(0, 0, colorRGBA(255, 255, 255))
	mask.SetRGBA(1, 0, color.RGBA{A: 255})
	dev := &fakeDevice{img: source}
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
const tmpl = getArg('template')
const mask = getArg('mask')
const withoutMask = pc.findImage(tmpl, {threshold: 0.99})
const withMask = pc.findImage(tmpl, {threshold: 0.99, mask})
setResult('withoutMask', withoutMask.ok)
setResult('withMask', withMask.ok)
setResult('x', withMask.rect.x)
`,
		Args: map[string]any{
			"pc":       device.Ref{Resource: "device", Kind: "rdp", Device: dev},
			"template": template,
			"mask":     mask,
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["withoutMask"] != false || resp.Results["withMask"] != true || resp.Results["x"] != int64(2) {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWrapperFindAllUsesCapture(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 8, 4))
	fillImage(source, colorRGBA(1, 1, 1))
	fillImageRect(source, image.Rect(1, 1, 3, 3), colorRGBA(10, 220, 10))
	fillImageRect(source, image.Rect(5, 1, 7, 3), colorRGBA(10, 220, 10))
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillImage(template, colorRGBA(10, 220, 10))
	dev := &fakeDevice{img: source}
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
const tmpl = getArg('template')
const matches = pc.findAll(tmpl, {threshold: 0.99})
setResult('count', matches.length)
setResult('firstX', matches[0].rect.x)
setResult('secondX', matches[1].rect.x)
`,
		Args: map[string]any{
			"pc":       device.Ref{Resource: "device", Kind: "rdp", Device: dev},
			"template": template,
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["count"] != int64(2) || resp.Results["firstX"] != int64(1) || resp.Results["secondX"] != int64(5) {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWrapperFindAllUnsupportedReturnsEmpty(t *testing.T) {
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: "const pc = getArg('pc'); setResult('count', pc.findAll('button.png').length)",
		Args: map[string]any{
			"pc": map[string]any{"resource": "device", "kind": "rdp", "unsupported": true},
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["count"] != int64(0) {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWrapperFindTextUsesConfiguredBlocks(t *testing.T) {
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: `
const pc = getArg('pc')
const found = pc.findText('Build \\d+', {regex: true, minConfidence: 0.5})
setResult('ok', found.ok)
setResult('text', found.text)
setResult('x', found.rect.x)
`,
		Args: map[string]any{
			"pc": map[string]any{
				"resource":    "device",
				"kind":        "rdp",
				"unsupported": true,
				"config": map[string]any{
					"blocks": []any{
						map[string]any{"text": "Build 42", "confidence": 0.2, "x": 1, "y": 2, "w": 20, "h": 10},
						map[string]any{"text": "Build 84", "confidence": 0.8, "x": 3, "y": 4, "w": 30, "h": 12},
					},
				},
			},
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != true || resp.Results["text"] != "Build 84" || resp.Results["x"] != int64(3) {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWrapperFindTextUnsupportedWithoutBlocks(t *testing.T) {
	resp, err := NewRuntime().Run(context.Background(), Request{
		Code: "const found = getArg('pc').findText('Login'); setResult('ok', found.ok); setResult('unsupported', found.unsupported)",
		Args: map[string]any{
			"pc": map[string]any{"resource": "device", "kind": "rdp", "unsupported": true},
		},
	})
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if resp.Results["ok"] != false || resp.Results["unsupported"] != true {
		t.Fatalf("results = %#v", resp.Results)
	}
}

func TestRuntimeDeviceWaitHonorsContext(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	_, err := (&Runtime{Timeout: time.Second}).Run(ctx, Request{
		Code: "getArg('pc').wait(1000)",
		Args: map[string]any{
			"pc": map[string]any{"resource": "device", "kind": "rdp", "unsupported": true},
		},
	})
	if err == nil {
		t.Fatalf("Run() error = nil, want context timeout")
	}
}

type fakeDevice struct {
	calls []string
	img   image.Image
}

func (d *fakeDevice) Capture(_ context.Context, dst **image.RGBA) error {
	d.calls = append(d.calls, "capture")
	source := d.img
	if source == nil {
		source = image.NewRGBA(image.Rect(0, 0, 1, 1))
	}
	bounds := source.Bounds()
	img := device.EnsureRGBA(dst, image.Rect(0, 0, bounds.Dx(), bounds.Dy()))
	for y := 0; y < bounds.Dy(); y++ {
		for x := 0; x < bounds.Dx(); x++ {
			img.Set(x, y, source.At(bounds.Min.X+x, bounds.Min.Y+y))
		}
	}
	return nil
}

func (d *fakeDevice) MouseMove(_ context.Context, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("move %d %d", x, y))
	return nil
}

func (d *fakeDevice) MouseDown(_ context.Context, button device.Button, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("down %s %d %d", button, x, y))
	return nil
}

func (d *fakeDevice) MouseUp(_ context.Context, button device.Button, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("up %s %d %d", button, x, y))
	return nil
}

func (d *fakeDevice) MouseWheel(_ context.Context, delta int) error {
	d.calls = append(d.calls, fmt.Sprintf("wheel %d", delta))
	return nil
}

func (d *fakeDevice) KeyDown(_ context.Context, key device.Key) error {
	d.calls = append(d.calls, fmt.Sprintf("keyDown %s", key))
	return nil
}

func (d *fakeDevice) KeyUp(_ context.Context, key device.Key) error {
	d.calls = append(d.calls, fmt.Sprintf("keyUp %s", key))
	return nil
}

func (d *fakeDevice) TypeText(_ context.Context, text string) error {
	d.calls = append(d.calls, "type "+text)
	return nil
}

func (d *fakeDevice) Close() error {
	d.calls = append(d.calls, "close")
	return nil
}

func colorRGBA(r, g, b uint8) color.RGBA {
	return color.RGBA{R: r, G: g, B: b, A: 255}
}

func fillImage(img *image.RGBA, c color.RGBA) {
	fillImageRect(img, img.Bounds(), c)
}

func fillImageRect(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			img.SetRGBA(x, y, c)
		}
	}
}
