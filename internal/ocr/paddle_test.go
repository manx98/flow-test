//go:build linux && cgo

package ocr

import (
	"image"
	"os"
	"path/filepath"
	"testing"
)

func TestRecognizePaddleBlankImage(t *testing.T) {
	if _, err := os.Stat(filepath.Join("..", "..", "libs", "models")); err != nil {
		t.Skip("libs/models not available")
	}
	_, err := RecognizePaddle(image.NewRGBA(image.Rect(0, 0, 32, 16)), PaddleConfig{UseAngleCls: true})
	if err != nil {
		t.Fatalf("RecognizePaddle error = %v", err)
	}
}

func TestPaddleKeysFileTinyV6(t *testing.T) {
	if got := paddleKeysFile("PP_OCRv6_tiny_rec"); got != "ppocr_keys_v6_tiny.txt" {
		t.Fatalf("tiny keys = %q", got)
	}
	if got := paddleKeysFile("PP_OCRv6_small_rec"); got != "ppocr_keys_v6.txt" {
		t.Fatalf("small keys = %q", got)
	}
}

func TestPaddleDetectThreshold(t *testing.T) {
	if got := paddleDetectThreshold(0); got != 0.45 {
		t.Fatalf("default threshold = %v", got)
	}
	if got := paddleDetectThreshold(50); got != 0.5 {
		t.Fatalf("percent threshold = %v", got)
	}
	if got := paddleDetectThreshold(0.8); got != 0.8 {
		t.Fatalf("fraction threshold = %v", got)
	}
}
