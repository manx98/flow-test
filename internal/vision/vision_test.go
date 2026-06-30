package vision

import (
	"image"
	"image/color"
	"testing"
)

func TestMatchPointAnchors(t *testing.T) {
	match := Match{X: 10, Y: 20, W: 30, H: 40}
	got := match.Point("center", 1, -2)
	if got != (Point{X: 26, Y: 38}) {
		t.Fatalf("center point = %#v", got)
	}
	got = match.Point("bottom-right", 0, 0)
	if got != (Point{X: 40, Y: 60}) {
		t.Fatalf("bottom-right point = %#v", got)
	}
}

func TestFindTemplate(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 8, 8))
	fill(src, color.RGBA{R: 10, G: 10, B: 10, A: 255})
	drawRect(src, image.Rect(3, 2, 6, 4), color.RGBA{R: 220, G: 30, B: 40, A: 255})
	tpl := image.NewRGBA(image.Rect(0, 0, 3, 2))
	fill(tpl, color.RGBA{R: 220, G: 30, B: 40, A: 255})

	match, ok, err := FindTemplate(src, tpl, 0.99)
	if err != nil {
		t.Fatalf("FindTemplate() error = %v", err)
	}
	if !ok {
		t.Fatalf("FindTemplate() ok = false")
	}
	if match.X != 3 || match.Y != 2 || match.W != 3 || match.H != 2 || match.Score < 0.99 {
		t.Fatalf("match = %#v", match)
	}
}

func TestFindTemplateReturnsBestScore(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 8, 3))
	fill(src, color.RGBA{R: 10, G: 10, B: 10, A: 255})
	drawRect(src, image.Rect(1, 1, 3, 3), color.RGBA{R: 210, G: 30, B: 40, A: 255})
	drawRect(src, image.Rect(5, 1, 7, 3), color.RGBA{R: 220, G: 30, B: 40, A: 255})
	tpl := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fill(tpl, color.RGBA{R: 220, G: 30, B: 40, A: 255})

	match, ok, err := FindTemplate(src, tpl, 0.8)
	if err != nil {
		t.Fatalf("FindTemplate() error = %v", err)
	}
	if !ok || match.X != 5 || match.Y != 1 {
		t.Fatalf("best match ok=%v match=%#v", ok, match)
	}
}

func TestFindAllTemplatesNoMatchAndTooLarge(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 4, 4))
	fill(src, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	tpl := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fill(tpl, color.RGBA{R: 200, G: 200, B: 200, A: 255})
	matches, err := FindAllTemplates(src, tpl, 0.99)
	if err != nil {
		t.Fatalf("FindAllTemplates() error = %v", err)
	}
	if len(matches) != 0 {
		t.Fatalf("matches = %#v", matches)
	}
	large := image.NewRGBA(image.Rect(0, 0, 5, 5))
	matches, err = FindAllTemplates(src, large, 0.99)
	if err != nil {
		t.Fatalf("FindAllTemplates(large) error = %v", err)
	}
	if len(matches) != 0 {
		t.Fatalf("large matches = %#v", matches)
	}
}

func TestFindTemplateWithMask(t *testing.T) {
	src := image.NewRGBA(image.Rect(0, 0, 6, 4))
	fill(src, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	src.SetRGBA(2, 1, color.RGBA{R: 220, A: 255})
	src.SetRGBA(3, 1, color.RGBA{B: 220, A: 255})
	tpl := image.NewRGBA(image.Rect(0, 0, 2, 1))
	tpl.SetRGBA(0, 0, color.RGBA{R: 220, A: 255})
	tpl.SetRGBA(1, 0, color.RGBA{G: 220, A: 255})
	if _, ok, err := FindTemplate(src, tpl, 0.99); err != nil || ok {
		t.Fatalf("FindTemplate without mask ok=%v err=%v", ok, err)
	}
	mask := image.NewRGBA(image.Rect(0, 0, 2, 1))
	mask.SetRGBA(0, 0, color.RGBA{R: 255, G: 255, B: 255, A: 255})
	mask.SetRGBA(1, 0, color.RGBA{A: 255})
	match, ok, err := FindTemplate(src, tpl, 0.99, mask)
	if err != nil {
		t.Fatalf("FindTemplate(mask) error = %v", err)
	}
	if !ok || match.X != 2 || match.Y != 1 {
		t.Fatalf("masked match ok=%v match=%#v", ok, match)
	}
}

func fill(img *image.RGBA, c color.RGBA) {
	drawRect(img, img.Bounds(), c)
}

func drawRect(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			img.SetRGBA(x, y, c)
		}
	}
}
