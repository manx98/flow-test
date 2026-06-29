package ocr

import (
	"bytes"
	"fmt"
	"image"
	"image/png"
	"strings"

	"github.com/otiai10/gosseract/v2"
)

func RecognizeTesseract(img image.Image, cfg TesseractConfig) ([]TextBlock, error) {
	if img == nil {
		return nil, fmt.Errorf("image is required for tesseract OCR")
	}
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		return nil, err
	}
	client := gosseract.NewClient()
	defer client.Close()
	if lang := strings.TrimSpace(cfg.Lang); lang != "" {
		if err := client.SetLanguage(strings.Fields(lang)...); err != nil {
			return nil, err
		}
	}
	if prefix := strings.TrimSpace(cfg.TessdataPrefix); prefix != "" {
		if err := client.SetTessdataPrefix(prefix); err != nil {
			return nil, err
		}
	}
	for key, value := range parseTesseractConfig(cfg.Config) {
		if err := client.SetVariable(gosseract.SettableVariable(key), value); err != nil {
			return nil, err
		}
	}
	if err := client.SetImageFromBytes(buf.Bytes()); err != nil {
		return nil, err
	}
	boxes, err := client.GetBoundingBoxes(gosseract.RIL_WORD)
	if err != nil {
		return nil, err
	}
	blocks := make([]TextBlock, 0, len(boxes))
	minConfidence := normalizeConfidence(cfg.MinConfidence)
	for _, box := range boxes {
		text := strings.TrimSpace(box.Word)
		confidence := normalizeConfidence(box.Confidence)
		if text == "" || confidence < minConfidence {
			continue
		}
		blocks = append(blocks, TextBlock{
			Text:       text,
			Confidence: confidence,
			X:          box.Box.Min.X,
			Y:          box.Box.Min.Y,
			W:          box.Box.Dx(),
			H:          box.Box.Dy(),
		})
	}
	return blocks, nil
}

func normalizeConfidence(value float64) float64 {
	if value > 1 {
		return value / 100
	}
	if value < 0 {
		return 0
	}
	return value
}

func parseTesseractConfig(raw string) map[string]string {
	out := map[string]string{}
	for _, part := range strings.Fields(raw) {
		if key, value, ok := strings.Cut(part, "="); ok {
			key = strings.TrimSpace(key)
			value = strings.TrimSpace(value)
			if key != "" {
				out[key] = value
			}
		}
	}
	return out
}
