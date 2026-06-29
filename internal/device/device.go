package device

import (
	"context"
	"image"
)

type Button string

const (
	ButtonLeft   Button = "left"
	ButtonMiddle Button = "middle"
	ButtonRight  Button = "right"
)

type Key string

type Ref struct {
	Resource    string         `json:"resource"`
	Kind        string         `json:"kind"`
	Config      map[string]any `json:"config,omitempty"`
	Width       int            `json:"width,omitempty"`
	Height      int            `json:"height,omitempty"`
	Unsupported bool           `json:"unsupported,omitempty"`
	Device      Device         `json:"-"`
}

type Device interface {
	Capture(ctx context.Context, dst **image.RGBA) error
	MouseMove(ctx context.Context, x, y int) error
	MouseDown(ctx context.Context, button Button, x, y int) error
	MouseUp(ctx context.Context, button Button, x, y int) error
	MouseWheel(ctx context.Context, delta int) error
	KeyDown(ctx context.Context, key Key) error
	KeyUp(ctx context.Context, key Key) error
	TypeText(ctx context.Context, text string) error
	Close() error
}

type SizedDevice interface {
	Size() (width int, height int)
}

func CaptureImage(ctx context.Context, dev Device) (image.Image, error) {
	if dev == nil {
		return nil, nil
	}
	var img *image.RGBA
	if err := dev.Capture(ctx, &img); err != nil {
		return nil, err
	}
	return img, nil
}

func EnsureRGBA(dst **image.RGBA, rect image.Rectangle) *image.RGBA {
	if dst == nil {
		return image.NewRGBA(rect)
	}
	if *dst == nil || !(*dst).Rect.Eq(rect) {
		*dst = image.NewRGBA(rect)
		return *dst
	}
	return *dst
}

func NewUnsupportedRef(kind string, config map[string]any, width, height int) Ref {
	if config == nil {
		config = map[string]any{}
	}
	return Ref{
		Resource:    "device",
		Kind:        kind,
		Config:      config,
		Width:       width,
		Height:      height,
		Unsupported: true,
	}
}
