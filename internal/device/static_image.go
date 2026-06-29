package device

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"strings"
)

type StaticImageDevice struct {
	image image.Image
}

func NewConfiguredDevice(kind string, config map[string]any) (Device, error) {
	driver := stringConfig(config, "driver")
	if kind == "rdp" {
		return NewRDPDevice(config)
	}
	if kind == "novnc" {
		return NewVNCDevice(config)
	}
	if kind == "pve" {
		return NewPVEDevice(config)
	}
	if kind == "vmware" {
		return NewVMwareDevice(config)
	}
	if kind != "static_image" && driver != "static_image" {
		return nil, nil
	}
	img, err := imageFromConfig(config)
	if err != nil {
		return nil, err
	}
	return &StaticImageDevice{image: img}, nil
}

func (d *StaticImageDevice) Capture(ctx context.Context, dst **image.RGBA) error {
	if d == nil || d.image == nil {
		return fmt.Errorf("static image device has no image")
	}
	bounds := d.image.Bounds()
	img := EnsureRGBA(dst, image.Rect(0, 0, bounds.Dx(), bounds.Dy()))
	for y := 0; y < bounds.Dy(); y++ {
		for x := 0; x < bounds.Dx(); x++ {
			img.Set(x, y, d.image.At(bounds.Min.X+x, bounds.Min.Y+y))
		}
	}
	return nil
}

func (d *StaticImageDevice) Size() (int, int) {
	if d == nil || d.image == nil {
		return 0, 0
	}
	bounds := d.image.Bounds()
	return bounds.Dx(), bounds.Dy()
}

func (d *StaticImageDevice) MouseMove(context.Context, int, int) error         { return nil }
func (d *StaticImageDevice) MouseDown(context.Context, Button, int, int) error { return nil }
func (d *StaticImageDevice) MouseUp(context.Context, Button, int, int) error   { return nil }
func (d *StaticImageDevice) MouseWheel(context.Context, int) error             { return nil }
func (d *StaticImageDevice) KeyDown(context.Context, Key) error                { return nil }
func (d *StaticImageDevice) KeyUp(context.Context, Key) error                  { return nil }
func (d *StaticImageDevice) TypeText(context.Context, string) error            { return nil }
func (d *StaticImageDevice) Close() error                                      { return nil }

func imageFromConfig(config map[string]any) (image.Image, error) {
	if img, ok := config["image"].(image.Image); ok && img != nil {
		return img, nil
	}
	if path := stringConfig(config, "image_path"); path != "" {
		file, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		defer file.Close()
		img, _, err := image.Decode(file)
		return img, err
	}
	if raw := stringConfig(config, "image_base64"); raw != "" {
		if idx := strings.Index(raw, ","); strings.HasPrefix(raw, "data:") && idx >= 0 {
			raw = raw[idx+1:]
		}
		data, err := base64.StdEncoding.DecodeString(raw)
		if err != nil {
			return nil, err
		}
		img, _, err := image.Decode(bytes.NewReader(data))
		return img, err
	}
	return nil, fmt.Errorf("static_image device requires image, image_path, or image_base64")
}

func stringConfig(config map[string]any, key string) string {
	value, ok := config[key]
	if !ok || value == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(value))
}
