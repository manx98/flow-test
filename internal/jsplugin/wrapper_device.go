package jsplugin

import (
	"context"
	"fmt"
	"image"
	"regexp"
	"strings"
	"time"

	"flow-test-go/internal/device"
	"flow-test-go/internal/ocr"
	"flow-test-go/internal/vision"

	"github.com/dop251/goja"
)

type bindings struct {
	ctx  context.Context
	vm   *goja.Runtime
	logs *[]string
}

func (b bindings) wrapArg(value any) goja.Value {
	if isDeviceRef(value) {
		return b.deviceWrapper(toDeviceRef(value))
	}
	return b.vm.ToValue(value)
}

func isDeviceRef(value any) bool {
	switch v := value.(type) {
	case device.Ref:
		return v.Resource == "device"
	case *device.Ref:
		return v != nil && v.Resource == "device"
	case map[string]any:
		return v["resource"] == "device"
	default:
		return false
	}
}

func toDeviceRef(value any) device.Ref {
	switch v := value.(type) {
	case device.Ref:
		return v
	case *device.Ref:
		if v == nil {
			return device.Ref{Resource: "device", Unsupported: true}
		}
		return *v
	case map[string]any:
		return device.Ref{
			Resource:    fmt.Sprint(v["resource"]),
			Kind:        fmt.Sprint(v["kind"]),
			Config:      mapFromAny(v["config"]),
			Width:       int(numberFromAny(v["width"])),
			Height:      int(numberFromAny(v["height"])),
			Unsupported: boolFromAny(v["unsupported"]),
		}
	default:
		return device.Ref{Resource: "device", Unsupported: true}
	}
}

func (b bindings) deviceWrapper(ref device.Ref) goja.Value {
	obj := b.vm.NewObject()
	_ = obj.Set("kind", ref.Kind)
	_ = obj.Set("unsupported", ref.Unsupported)
	_ = obj.Set("config", ref.Config)
	_ = obj.Set("findImage", func(call goja.FunctionCall) goja.Value {
		template, ok := imageFromAny(call.Argument(0).Export())
		if ref.Device != nil && ok {
			source, err := device.CaptureImage(b.ctx, ref.Device)
			if err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			threshold := thresholdFromCall(call)
			masks := masksFromCall(call)
			match, found, err := vision.FindTemplate(source, template, threshold, masks...)
			if err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			if found {
				return b.vm.ToValue(map[string]any{
					"ok":          true,
					"point":       match.Point("center", 0, 0),
					"rect":        map[string]any{"x": match.X, "y": match.Y, "w": match.W, "h": match.H},
					"score":       match.Score,
					"unsupported": false,
				})
			}
			return b.vm.ToValue(map[string]any{
				"ok":          false,
				"point":       nil,
				"rect":        nil,
				"score":       0,
				"unsupported": false,
			})
		}
		return b.vm.ToValue(map[string]any{
			"ok":          false,
			"point":       nil,
			"rect":        nil,
			"score":       0,
			"unsupported": true,
		})
	})
	_ = obj.Set("findAll", func(call goja.FunctionCall) goja.Value {
		template, ok := imageFromAny(call.Argument(0).Export())
		if ref.Device != nil && ok {
			source, err := device.CaptureImage(b.ctx, ref.Device)
			if err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			threshold := thresholdFromCall(call)
			masks := masksFromCall(call)
			matches, err := vision.FindAllTemplates(source, template, threshold, masks...)
			if err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			out := make([]map[string]any, 0, len(matches))
			for _, match := range matches {
				out = append(out, map[string]any{
					"point": match.Point("center", 0, 0),
					"rect":  map[string]any{"x": match.X, "y": match.Y, "w": match.W, "h": match.H},
					"score": match.Score,
				})
			}
			return b.vm.ToValue(out)
		}
		return b.vm.ToValue([]any{})
	})
	_ = obj.Set("findText", func(call goja.FunctionCall) goja.Value {
		target := call.Argument(0).String()
		options := mapFromAny(call.Argument(1).Export())
		regex := boolFromAny(options["regex"])
		minConfidence := numberFromAny(options["minConfidence"])
		trimmedTarget := strings.TrimSpace(target)
		blocks := textBlocksFromAny(firstAny(options["blocks"], ref.Config["blocks"]))
		unsupported := false
		if len(blocks) == 0 && trimmedTarget != "" {
			if ref.Device == nil {
				unsupported = true
			} else {
				var pattern *regexp.Regexp
				if regex {
					var err error
					pattern, err = regexp.Compile(trimmedTarget)
					if err != nil {
						panic(b.vm.ToValue(err.Error()))
					}
				}
				blocks, unsupported = b.recognizeDeviceOCR(ref, options, func(block ocr.TextBlock) bool {
					return block.Confidence >= normalizeConfidence(minConfidence) && textMatches(block.Text, trimmedTarget, pattern)
				})
			}
		}
		match, ok, err := findTextInBlocks(blocks, target, regex, minConfidence)
		if err != nil {
			panic(b.vm.ToValue(err.Error()))
		}
		if ok {
			return b.vm.ToValue(match)
		}
		return b.vm.ToValue(map[string]any{
			"ok":          false,
			"point":       nil,
			"rect":        nil,
			"text":        target,
			"score":       0,
			"unsupported": unsupported,
		})
	})
	_ = obj.Set("ocr", func(call goja.FunctionCall) goja.Value {
		options := mapFromAny(call.Argument(0).Export())
		blocks, unsupported := b.ocrBlocks(ref, options)
		if unsupported {
			return b.vm.ToValue(map[string]any{"ok": false, "blocks": []any{}, "unsupported": true})
		}
		return b.vm.ToValue(map[string]any{"ok": true, "blocks": textBlocksToMaps(blocks), "unsupported": false})
	})
	_ = obj.Set("click", func(call goja.FunctionCall) goja.Value {
		point := call.Argument(0).Export()
		x, y, ok := pointXY(point)
		if ref.Device != nil && ok {
			if err := ref.Device.MouseMove(b.ctx, x, y); err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			if err := ref.Device.MouseDown(b.ctx, device.ButtonLeft, x, y); err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			if err := ref.Device.MouseUp(b.ctx, device.ButtonLeft, x, y); err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			return goja.Undefined()
		}
		*b.logs = append(*b.logs, "planned device.click "+formatPoint(point))
		return goja.Undefined()
	})
	_ = obj.Set("type", func(call goja.FunctionCall) goja.Value {
		text := call.Argument(0).String()
		if ref.Device != nil {
			if err := ref.Device.TypeText(b.ctx, text); err != nil {
				panic(b.vm.ToValue(err.Error()))
			}
			return goja.Undefined()
		}
		*b.logs = append(*b.logs, fmt.Sprintf("planned device.type %q", text))
		return goja.Undefined()
	})
	_ = obj.Set("hotkey", func(call goja.FunctionCall) goja.Value {
		keys := call.Argument(0).String()
		parts := parseHotkey(keys)
		if ref.Device != nil {
			for _, key := range parts {
				if err := ref.Device.KeyDown(b.ctx, device.Key(key)); err != nil {
					panic(b.vm.ToValue(err.Error()))
				}
			}
			for i := len(parts) - 1; i >= 0; i-- {
				if err := ref.Device.KeyUp(b.ctx, device.Key(parts[i])); err != nil {
					panic(b.vm.ToValue(err.Error()))
				}
			}
			return goja.Undefined()
		}
		*b.logs = append(*b.logs, "planned device.hotkey "+keys)
		return goja.Undefined()
	})
	_ = obj.Set("wait", func(call goja.FunctionCall) goja.Value {
		ms := call.Argument(0).ToInteger()
		if ms < 0 {
			ms = 0
		}
		timer := time.NewTimer(time.Duration(ms) * time.Millisecond)
		defer timer.Stop()
		select {
		case <-b.ctx.Done():
			b.vm.Interrupt(b.ctx.Err())
		case <-timer.C:
		}
		return goja.Undefined()
	})
	return obj
}

func (b bindings) ocrBlocks(ref device.Ref, options map[string]any) ([]textBlock, bool) {
	if blocks := textBlocksFromAny(firstAny(options["blocks"], ref.Config["blocks"])); len(blocks) > 0 {
		return blocks, false
	}
	if ref.Device == nil {
		return nil, true
	}
	return b.recognizeDeviceOCR(ref, options, nil)
}

func (b bindings) recognizeDeviceOCR(ref device.Ref, options map[string]any, accept func(ocr.TextBlock) bool) ([]textBlock, bool) {
	source, err := device.CaptureImage(b.ctx, ref.Device)
	if err != nil {
		panic(b.vm.ToValue(err.Error()))
	}
	var raw []ocr.TextBlock
	switch strings.ToLower(stringFromAny(firstAny(options["engine"], ref.Config["ocr_engine"], "paddle"))) {
	case "tesseract":
		raw, err = ocr.RecognizeTesseract(source, ocr.TesseractConfig{
			Lang:           stringDefault(stringFromAny(options["lang"]), "eng"),
			Config:         stringFromAny(options["config"]),
			TessdataPrefix: stringFromAny(options["tessdataPrefix"]),
			MinConfidence:  numberFromAny(options["minConfidence"]),
		})
	default:
		raw, err = ocr.RecognizePaddleUntil(source, ocr.PaddleConfig{
			DetModel:      stringFromAny(options["detModel"]),
			RecModel:      stringFromAny(options["recModel"]),
			TextlineModel: stringFromAny(options["textlineModel"]),
			MinConfidence: numberFromAny(options["minConfidence"]),
			UseAngleCls:   !hasOption(options, "useAngleCls") || boolFromAny(options["useAngleCls"]),
			UseVulkan:     boolFromAny(options["useGpu"]),
			Redetect:      !hasOption(options, "redetect") || boolFromAny(options["redetect"]),
		}, accept)
	}
	if err != nil {
		panic(b.vm.ToValue(err.Error()))
	}
	return textBlocksFromOCR(raw), false
}

func formatPoint(value any) string {
	switch v := value.(type) {
	case map[string]any:
		return fmt.Sprintf("(%v,%v)", v["x"], v["y"])
	default:
		return fmt.Sprint(value)
	}
}

type textBlock struct {
	Text       string
	Confidence float64
	X          int
	Y          int
	W          int
	H          int
}

func textBlocksFromAny(value any) []textBlock {
	switch v := value.(type) {
	case []ocr.TextBlock:
		return textBlocksFromOCR(v)
	case []any:
		out := make([]textBlock, 0, len(v))
		for _, item := range v {
			if block, ok := textBlockFromAny(item); ok {
				out = append(out, block)
			}
		}
		return out
	case []map[string]any:
		out := make([]textBlock, 0, len(v))
		for _, item := range v {
			if block, ok := textBlockFromAny(item); ok {
				out = append(out, block)
			}
		}
		return out
	case map[string]any:
		for _, key := range []string{"blocks", "text_blocks", "ocr_blocks"} {
			if blocks := textBlocksFromAny(v[key]); len(blocks) > 0 {
				return blocks
			}
		}
		if block, ok := textBlockFromAny(v); ok {
			return []textBlock{block}
		}
	}
	return nil
}

func textBlocksFromOCR(values []ocr.TextBlock) []textBlock {
	out := make([]textBlock, 0, len(values))
	for _, block := range values {
		out = append(out, textBlock{
			Text:       block.Text,
			Confidence: block.Confidence,
			X:          block.X,
			Y:          block.Y,
			W:          block.W,
			H:          block.H,
		})
	}
	return out
}

func textBlocksToMaps(blocks []textBlock) []map[string]any {
	out := make([]map[string]any, 0, len(blocks))
	for _, block := range blocks {
		out = append(out, map[string]any{
			"text":       block.Text,
			"confidence": block.Confidence,
			"x":          block.X,
			"y":          block.Y,
			"w":          block.W,
			"h":          block.H,
		})
	}
	return out
}

func textBlockFromAny(value any) (textBlock, bool) {
	m := mapFromAny(value)
	text := strings.TrimSpace(fmt.Sprint(m["text"]))
	if text == "" {
		return textBlock{}, false
	}
	return textBlock{
		Text:       text,
		Confidence: numberFromAny(firstAny(m["confidence"], m["score"], 1)),
		X:          int(numberFromAny(m["x"])),
		Y:          int(numberFromAny(m["y"])),
		W:          int(numberFromAny(firstAny(m["w"], m["width"], 0))),
		H:          int(numberFromAny(firstAny(m["h"], m["height"], 0))),
	}, true
}

func findTextInBlocks(blocks []textBlock, target string, regex bool, minConfidence float64) (map[string]any, bool, error) {
	target = strings.TrimSpace(target)
	if target == "" {
		return nil, false, nil
	}
	var pattern *regexp.Regexp
	var err error
	if regex {
		pattern, err = regexp.Compile(target)
		if err != nil {
			return nil, false, err
		}
	}
	minConfidence = normalizeConfidence(minConfidence)
	for _, block := range blocks {
		if block.Confidence < minConfidence {
			continue
		}
		if pattern != nil {
			if !pattern.MatchString(block.Text) {
				continue
			}
		} else if !strings.Contains(block.Text, target) {
			continue
		}
		return map[string]any{
			"ok":    true,
			"point": map[string]any{"x": block.X + block.W/2, "y": block.Y + block.H/2},
			"rect":  map[string]any{"x": block.X, "y": block.Y, "w": block.W, "h": block.H},
			"text":  block.Text,
			"score": block.Confidence,
		}, true, nil
	}
	return nil, false, nil
}

func textMatches(text string, target string, pattern *regexp.Regexp) bool {
	if pattern != nil {
		return pattern.MatchString(text)
	}
	return strings.Contains(text, target)
}

func normalizeConfidence(value float64) float64 {
	if value > 1 {
		return value / 100
	}
	return value
}

func firstAny(values ...any) any {
	for _, value := range values {
		if value != nil {
			return value
		}
	}
	return nil
}

func pointXY(value any) (int, int, bool) {
	switch v := value.(type) {
	case map[string]any:
		return int(numberFromAny(v["x"])), int(numberFromAny(v["y"])), true
	case map[string]float64:
		return int(v["x"]), int(v["y"]), true
	default:
		return 0, 0, false
	}
}

func parseHotkey(keys string) []string {
	parts := strings.FieldsFunc(keys, func(r rune) bool {
		return r == '+' || r == ' ' || r == ','
	})
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

func mapFromAny(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func numberFromAny(value any) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case int64:
		return float64(v)
	default:
		return 0
	}
}

func boolFromAny(value any) bool {
	b, _ := value.(bool)
	return b
}

func stringFromAny(value any) string {
	if value == nil {
		return ""
	}
	return fmt.Sprint(value)
}

func stringDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func hasOption(options map[string]any, key string) bool {
	_, ok := options[key]
	return ok
}

func imageFromAny(value any) (image.Image, bool) {
	switch v := value.(type) {
	case image.Image:
		return v, true
	default:
		return nil, false
	}
}

func thresholdFromCall(call goja.FunctionCall) float64 {
	if len(call.Arguments) < 2 || goja.IsUndefined(call.Argument(1)) || goja.IsNull(call.Argument(1)) {
		return 0.85
	}
	options := call.Argument(1).Export()
	if m, ok := options.(map[string]any); ok {
		if v := numberFromAny(m["threshold"]); v > 0 {
			return v
		}
		if v := numberFromAny(m["similarity"]); v > 0 {
			return v
		}
	}
	return 0.85
}

func masksFromCall(call goja.FunctionCall) []image.Image {
	if len(call.Arguments) < 2 || goja.IsUndefined(call.Argument(1)) || goja.IsNull(call.Argument(1)) {
		return nil
	}
	options := call.Argument(1).Export()
	if m, ok := options.(map[string]any); ok {
		if mask, ok := imageFromAny(m["mask"]); ok {
			return []image.Image{mask}
		}
	}
	return nil
}
