//go:build !linux || !cgo

package ocr

import (
	"fmt"
	"image"
)

func RecognizePaddle(image.Image, PaddleConfig) ([]TextBlock, error) {
	return nil, fmt.Errorf("paddle OCR requires linux with cgo")
}
