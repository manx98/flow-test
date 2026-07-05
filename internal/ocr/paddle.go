//go:build linux && cgo

package ocr

/*
#cgo linux CFLAGS: -I${SRCDIR}/../../libs/include
#cgo linux LDFLAGS: -L${SRCDIR}/../../libs/lib -Wl,--disable-new-dtags -Wl,-rpath,${SRCDIR}/../../libs/lib -lpaddle_ocr_engine -lncnn -lopencv_imgproc -lopencv_core -lgomp -lstdc++
#include <stdlib.h>
#include "paddle_ocr_engine.h"
*/
import "C"

import (
	"fmt"
	"image"
	"os"
	"path/filepath"
	"strings"
	"unsafe"
)

func RecognizePaddle(img image.Image, cfg PaddleConfig) ([]TextBlock, error) {
	if img == nil {
		return nil, fmt.Errorf("image is required for paddle OCR")
	}
	data, width, height, err := imageBGR(img)
	if err != nil {
		return nil, err
	}
	models, err := libsPath("models")
	if err != nil {
		return nil, err
	}
	engine := C.paddle_ocr_engine_create()
	if engine == nil {
		return nil, fmt.Errorf("failed to create paddle OCR engine")
	}
	defer C.paddle_ocr_engine_destroy(engine)

	detName := stringDefault(cfg.DetModel, "PP_OCRv6_small_det")
	recName := stringDefault(cfg.RecModel, "PP_OCRv6_small_rec")
	textlineName := stringDefault(cfg.TextlineModel, "PP_LCNet_x0_25_textline_ori")
	detModel := cString(filepath.Join(models, detName))
	clsModel := cString(filepath.Join(models, textlineName))
	recModel := cString(filepath.Join(models, recName))
	keysPath := cString(filepath.Join(models, paddleKeysFile(recName)))
	defer freeStrings(detModel, clsModel, recModel, keysPath)

	det := C.PaddleOCRDetConfig{
		infer_threads: C.int(-1),
		model_path:    detModel,
		max_side_len:  C.int(768),
		box_thres:     C.float(paddleDetectThreshold(cfg.MinConfidence)),
		bitmap_thres:  C.float(0.2),
		unclip_ratio:  C.float(1.4),
		use_vulkan:    cBool(cfg.UseVulkan),
	}
	cls := C.PaddleOCRClsConfig{
		infer_threads: C.int(1),
		reco_threads:  C.int(-1),
		model_path:    clsModel,
		enable:        cBool(cfg.UseAngleCls),
		most_angle:    C.int(1),
		use_vulkan:    cBool(cfg.UseVulkan),
	}
	rec := C.PaddleOCRRecConfig{
		infer_threads: C.int(1),
		reco_threads:  C.int(-1),
		model_path:    recModel,
		keys_path:     keysPath,
		use_vulkan:    cBool(cfg.UseVulkan),
	}
	if code := C.paddle_ocr_engine_init(engine, &det, &cls, &rec); code != 0 {
		return nil, fmt.Errorf("paddle OCR init failed: %d", int(code))
	}

	boxes, err := detectPaddleBoxes(engine, data, width, height, nil)
	if err != nil {
		return nil, err
	}
	defer C.paddle_ocr_engine_free_boxes(boxes)

	firstPass := unsafe.Slice(boxes.data, int(boxes.count))
	blocks := make([]TextBlock, 0, len(firstPass))
	for i := range firstPass {
		if !cfg.Redetect {
			block, ok, err := recognizePaddleBox(engine, data, width, height, &firstPass[i])
			if err != nil {
				return nil, err
			}
			if ok {
				blocks = append(blocks, block)
			}
			continue
		}
		refined, err := detectPaddleBoxes(engine, data, width, height, &firstPass[i])
		if err != nil {
			return nil, err
		}
		refinedItems := unsafe.Slice(refined.data, int(refined.count))
		if len(refinedItems) == 0 {
			refinedItems = firstPass[i : i+1]
		}
		for j := range refinedItems {
			block, ok, err := recognizePaddleBox(engine, data, width, height, &refinedItems[j])
			if err != nil {
				C.paddle_ocr_engine_free_boxes(refined)
				return nil, err
			}
			if ok {
				blocks = append(blocks, block)
			}
		}
		C.paddle_ocr_engine_free_boxes(refined)
	}
	return blocks, nil
}

func detectPaddleBoxes(engine *C.PaddleOCREngine, data []byte, width, height int, region *C.PaddleOCRBox) (*C.PaddleOCRBoxList, error) {
	boxes := new(C.PaddleOCRBoxList)
	if code := C.paddle_ocr_engine_detect(engine, (*C.uchar)(unsafe.Pointer(&data[0])), C.int(width), C.int(height), C.int(width*3), region, boxes); code != 0 {
		C.paddle_ocr_engine_free_boxes(boxes)
		return nil, fmt.Errorf("paddle OCR detect failed: %d", int(code))
	}
	return boxes, nil
}

func recognizePaddleBox(engine *C.PaddleOCREngine, data []byte, width, height int, box *C.PaddleOCRBox) (TextBlock, bool, error) {
	var result C.PaddleOCRResult
	if code := C.paddle_ocr_engine_recognize(engine, (*C.uchar)(unsafe.Pointer(&data[0])), C.int(width), C.int(height), C.int(width*3), box, &result); code != 0 {
		return TextBlock{}, false, fmt.Errorf("paddle OCR recognize failed: %d", int(code))
	}
	block, ok := paddleBlock(*box, result)
	C.paddle_ocr_engine_free_result(&result)
	return block, ok, nil
}

func imageBGR(img image.Image) ([]byte, int, int, error) {
	bounds := img.Bounds()
	width, height := bounds.Dx(), bounds.Dy()
	if width <= 0 || height <= 0 {
		return nil, 0, 0, fmt.Errorf("image is empty")
	}
	data := make([]byte, 0, width*height*3)
	for y := bounds.Min.Y; y < bounds.Max.Y; y++ {
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			r, g, b, _ := img.At(x, y).RGBA()
			data = append(data, byte(b>>8), byte(g>>8), byte(r>>8))
		}
	}
	return data, width, height, nil
}

func paddleBlock(box C.PaddleOCRBox, result C.PaddleOCRResult) (TextBlock, bool) {
	text := C.GoString(result.text)
	if text == "" {
		return TextBlock{}, false
	}
	minX, maxX := int(box.points[0].x), int(box.points[0].x)
	minY, maxY := int(box.points[0].y), int(box.points[0].y)
	for i := 1; i < 4; i++ {
		x, y := int(box.points[i].x), int(box.points[i].y)
		minX, maxX = min(minX, x), max(maxX, x)
		minY, maxY = min(minY, y), max(maxY, y)
	}
	return TextBlock{
		Text:       text,
		Confidence: float64(result.text_score),
		X:          minX,
		Y:          minY,
		W:          maxX - minX,
		H:          maxY - minY,
	}, true
}

func libsPath(name string) (string, error) {
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		path := filepath.Join(dir, "libs", name)
		if _, err := os.Stat(path); err == nil {
			return path, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", fmt.Errorf("libs/%s not found", name)
		}
		dir = parent
	}
}

func cString(s string) *C.char {
	return C.CString(s)
}

func freeStrings(values ...*C.char) {
	for _, value := range values {
		C.free(unsafe.Pointer(value))
	}
}

func cBool(value bool) C.int {
	if value {
		return 1
	}
	return 0
}

func stringDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func paddleDetectThreshold(value float64) float64 {
	if value <= 0 {
		return 0.45
	}
	if value > 1 {
		return value / 100
	}
	return value
}

func paddleKeysFile(recModel string) string {
	switch {
	case recModel == "PP_OCRv6_tiny_rec":
		return "ppocr_keys_v6_tiny.txt"
	case strings.HasPrefix(recModel, "PP_OCRv6"):
		return "ppocr_keys_v6.txt"
	case strings.HasPrefix(recModel, "PP_OCRv5"):
		return "ppocr_keys_v5.txt"
	default:
		return "ppocr_keys_v1.txt"
	}
}
