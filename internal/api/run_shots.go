package api

import (
	"bytes"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
)

func saveNodeShot(p interface {
	SaveRunFile(string, string, []byte) error
}, runName string, nodeID int64, img image.Image, rects []image.Rectangle) (string, error) {
	if img == nil {
		return "", nil
	}
	out := image.NewRGBA(img.Bounds())
	draw.Draw(out, out.Bounds(), img, img.Bounds().Min, draw.Src)
	for _, rect := range rects {
		drawRect(out, rect, color.RGBA{R: 255, A: 255})
		drawCross(out, rect, color.RGBA{R: 255, A: 255})
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, out); err != nil {
		return "", err
	}
	name := fmt.Sprintf("node_%d_shot.png", nodeID)
	if err := p.SaveRunFile(runName, name, buf.Bytes()); err != nil {
		return "", err
	}
	return name, nil
}

func drawRect(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	rect = rect.Intersect(img.Bounds())
	if rect.Empty() {
		return
	}
	for x := rect.Min.X; x < rect.Max.X; x++ {
		img.SetRGBA(x, rect.Min.Y, c)
		img.SetRGBA(x, rect.Max.Y-1, c)
	}
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		img.SetRGBA(rect.Min.X, y, c)
		img.SetRGBA(rect.Max.X-1, y, c)
	}
}

func drawCross(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	rect = rect.Intersect(img.Bounds())
	if rect.Empty() {
		return
	}
	cx := (rect.Min.X + rect.Max.X) / 2
	cy := (rect.Min.Y + rect.Max.Y) / 2
	for x := rect.Min.X; x < rect.Max.X; x++ {
		img.SetRGBA(x, cy, c)
	}
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		img.SetRGBA(cx, y, c)
	}
}
