package nodes

import (
	"context"
	"encoding/json"
	"fmt"
	"image"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"flow-test-go/internal/device"
	"flow-test-go/internal/flow"
	"flow-test-go/internal/jsplugin"
	"flow-test-go/internal/ocr"
	"flow-test-go/internal/vision"
)

type Registry struct {
	handlers map[string]flow.Handler
}

func NewRegistry() *Registry {
	r := &Registry{handlers: map[string]flow.Handler{}}
	r.Register("flow/start", ExecPass{})
	r.Register("flow/if", If{})
	r.Register("flow/loop", Loop{})
	r.Register("flow/sequence", Sequence{})
	r.Register("flow/try_catch", TryCatch{})
	r.Register("flow/raise", Raise{})
	r.Register("wait/delay", Delay{})
	r.Register("wait/appear", WaitAppear{})
	r.Register("wait/vanish", WaitVanish{})
	r.Register("const/text", Const{Output: "text", Property: "value"})
	r.Register("const/number", Const{Output: "number", Property: "value"})
	r.Register("const/bool", Const{Output: "bool", Property: "value"})
	r.Register("const/point", PointConst{})
	r.Register("const/image", ImageConst{})
	r.Register("vision/preview", Preview{})
	r.Register("vision/find_image", FindImage{})
	r.Register("vision/find_text", FindText{})
	r.Register("vision/find_all", FindAll{})
	r.Register("mask/create", MaskCreate{})
	r.Register("ocr/tesseract", OCREngine{Kind: "tesseract"})
	r.Register("ocr/paddle", OCREngine{Kind: "paddle", Unsupported: true})
	r.Register("geom/to_point", ToPoint{})
	r.Register("action/click", ActionClick{})
	r.Register("action/type", ActionType{})
	r.Register("action/hotkey", ActionHotkey{})
	r.Register("action/scroll", ActionScroll{})
	r.Register("action/drag", ActionDrag{})
	r.Register("var/get", VarGet{})
	r.Register("var/set", VarSet{})
	r.Register("assert/check", Assert{})
	r.Register("test/result", TestResult{})
	r.Register("api/json_serialize", JSONSerialize{})
	r.Register("api/form_serialize", FormSerialize{})
	r.Register("api/request", APIRequest{})
	r.Register("script/js", JSScript{})
	r.Register("script/js_exec", JSExec{})
	for _, nodeType := range []string{"device/rdp", "device/novnc", "device/pve", "device/vmware"} {
		r.Register(nodeType, DeviceSource{Kind: strings.TrimPrefix(nodeType, "device/")})
	}
	r.Register("device/attrs", DeviceAttrs{})
	r.Register("io/interaction", Interaction{})
	r.Register("util/log", Log{})
	r.Register("util/alert", Alert{})
	r.Register("data/text_display", TextDisplay{})
	return r
}

func (r *Registry) Register(nodeType string, handler flow.Handler) {
	r.handlers[nodeType] = handler
}

func (r *Registry) Handler(nodeType string) (flow.Handler, bool) {
	h, ok := r.handlers[nodeType]
	return h, ok
}

type ExecPass struct{}

func (ExecPass) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ExecPass) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type Const struct {
	Output   string
	Property string
}

func (h Const) Eval(_ context.Context, _ *flow.RunContext, node *flow.Node) (map[string]any, error) {
	if node.Properties == nil {
		return map[string]any{h.Output: nil}, nil
	}
	return map[string]any{h.Output: node.Properties[h.Property]}, nil
}

func (h Const) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type If struct{}

func (If) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (If) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "cond")
	if err != nil {
		return "", err
	}
	if boolOf(value) {
		return "true", nil
	}
	return "false", nil
}

type Loop struct{}

func (Loop) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Loop) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "count")
	if err != nil {
		return "", err
	}
	count := int(numberOf(value, 0))
	for i := 0; i < count; i++ {
		if err := rc.RunBranch(ctx, node, "body"); err != nil {
			return "", err
		}
	}
	return "done", nil
}

type Sequence struct{}

func (Sequence) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Sequence) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	for _, out := range node.Outputs {
		if out.Type == "exec" {
			if err := rc.RunBranch(ctx, node, out.Name); err != nil {
				return "", err
			}
		}
	}
	return "", nil
}

type TryCatch struct{}

func (TryCatch) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (TryCatch) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	err := rc.RunBranch(ctx, node, "try")
	if err == nil {
		rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok"})
		return "done", nil
	}
	rc.SetOutput(node, "error", err.Error())
	rc.SetOutput(node, "error_type", fmt.Sprintf("%T", err))
	if nodeErr, ok := err.(flow.NodeError); ok {
		rc.SetOutput(node, "error_node", nodeErr.NodeID)
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok", Info: "caught: " + err.Error()})
	if catchErr := rc.RunBranch(ctx, node, "catch"); catchErr != nil {
		return "", catchErr
	}
	return "done", nil
}

type Raise struct{}

func (Raise) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Raise) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	message, err := inputString(ctx, rc, node, "message", "message", "主动抛出异常")
	if err != nil {
		return "", err
	}
	if message == "" {
		message = "主动抛出异常"
	}
	return "", fmt.Errorf("%s", message)
}

type Delay struct{}

func (Delay) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Delay) Run(ctx context.Context, _ *flow.RunContext, node *flow.Node) (string, error) {
	seconds := numberFloatProp(node, "seconds", 1)
	timer := time.NewTimer(time.Duration(seconds * float64(time.Second)))
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-timer.C:
		return "out", nil
	}
}

type WaitAppear struct{}

func (WaitAppear) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (WaitAppear) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	match, ok, observed, err := waitForImageState(ctx, rc, node, true)
	if err != nil {
		return "", err
	}
	if observed && ok {
		rc.SetOutput(node, "match", match)
		if source, sourceOK, _, err := imageInputs(ctx, rc, node); err == nil && sourceOK {
			emitNodeShot(rc, node, source, []vision.Match{match})
		}
		return "out", nil
	}
	rc.SetOutput(node, "match", nil)
	return "timeout", nil
}

type WaitVanish struct{}

func (WaitVanish) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (WaitVanish) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	_, ok, observed, err := waitForImageState(ctx, rc, node, false)
	if err != nil {
		return "", err
	}
	if observed && !ok {
		return "out", nil
	}
	return "timeout", nil
}

type PointConst struct{}

func (PointConst) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	xValue, _, err := rc.EvalInput(ctx, node, "x")
	if err != nil {
		return nil, err
	}
	yValue, _, err := rc.EvalInput(ctx, node, "y")
	if err != nil {
		return nil, err
	}
	x := numberOf(xValue, numberFloatProp(node, "x", 0))
	y := numberOf(yValue, numberFloatProp(node, "y", 0))
	return map[string]any{"point": map[string]any{"x": int(x), "y": int(y)}}, nil
}

func (PointConst) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type DeviceSource struct {
	Kind string
}

func (h DeviceSource) Eval(_ context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	if rc != nil && rc.Runner != nil && rc.Runner.DeviceResolver != nil {
		if value, ok := rc.Runner.DeviceResolver(node); ok {
			if ref, ok := value.(device.Ref); ok {
				return map[string]any{"device": ref}, nil
			}
			return map[string]any{"device": value}, nil
		}
	}
	config := map[string]any{}
	for key, value := range node.Properties {
		if key != "password" {
			config[key] = value
		}
	}
	ref := device.NewUnsupportedRef(h.Kind, config, numberProp(node, "width", 0), numberProp(node, "height", 0))
	return map[string]any{"device": ref}, nil
}

func (h DeviceSource) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type ImageConst struct{}

func (ImageConst) Eval(_ context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	name := stringProp(node, "name", "")
	if name == "" {
		return map[string]any{"picture": nil}, nil
	}
	if rc != nil && rc.Runner != nil && rc.Runner.ImageResolver != nil {
		value, ok, err := rc.Runner.ImageResolver(name)
		if err != nil {
			return nil, err
		}
		if ok {
			return map[string]any{"picture": value}, nil
		}
	}
	return map[string]any{"picture": map[string]any{"name": name}}, nil
}

func (ImageConst) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type Preview struct{}

func (Preview) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	value, _, err := rc.EvalInput(ctx, node, "picture")
	if err != nil {
		return nil, err
	}
	return map[string]any{"picture": value}, nil
}

func (Preview) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type MaskCreate struct{}

func (MaskCreate) Eval(_ context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	name := stringProp(node, "mask", "")
	if name == "" {
		return map[string]any{"mask": nil}, nil
	}
	if rc != nil && rc.Runner != nil && rc.Runner.ImageResolver != nil {
		value, ok, err := rc.Runner.ImageResolver(name)
		if err != nil {
			return nil, err
		}
		if ok {
			return map[string]any{"mask": value}, nil
		}
	}
	return map[string]any{"mask": map[string]any{"name": name}}, nil
}

func (MaskCreate) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type FindImage struct{}

func (FindImage) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (FindImage) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	video, _, err := rc.EvalInput(ctx, node, "video")
	if err != nil {
		return "", err
	}
	template, _, err := rc.EvalInput(ctx, node, "template")
	if err != nil {
		return "", err
	}
	mask, _, err := rc.EvalInput(ctx, node, "mask")
	if err != nil {
		return "", err
	}
	sourceImage, sourceOK, err := imageFromValue(ctx, video)
	if err != nil {
		return "", err
	}
	templateImage, templateOK, err := imageFromValue(ctx, template)
	if err != nil {
		return "", err
	}
	maskImage, maskOK, err := imageFromValue(ctx, mask)
	if err != nil {
		return "", err
	}
	if sourceOK && templateOK {
		var masks []image.Image
		if maskOK {
			masks = append(masks, maskImage)
		}
		match, ok, err := vision.FindTemplate(sourceImage, templateImage, imageSimilarityProp(node), masks...)
		if err != nil {
			return "", err
		}
		if ok {
			rc.SetOutput(node, "match", match)
			rc.SetOutput(node, "ok", true)
			emitNodeShot(rc, node, sourceImage, []vision.Match{match})
			return "found", nil
		}
	}
	rc.SetOutput(node, "match", nil)
	rc.SetOutput(node, "ok", false)
	return "notFound", nil
}

type FindAll struct{}

func (FindAll) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (FindAll) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	video, _, err := rc.EvalInput(ctx, node, "video")
	if err != nil {
		return "", err
	}
	template, _, err := rc.EvalInput(ctx, node, "template")
	if err != nil {
		return "", err
	}
	mask, _, err := rc.EvalInput(ctx, node, "mask")
	if err != nil {
		return "", err
	}
	sourceImage, sourceOK, err := imageFromValue(ctx, video)
	if err != nil {
		return "", err
	}
	templateImage, templateOK, err := imageFromValue(ctx, template)
	if err != nil {
		return "", err
	}
	maskImage, maskOK, err := imageFromValue(ctx, mask)
	if err != nil {
		return "", err
	}
	if sourceOK && templateOK {
		var masks []image.Image
		if maskOK {
			masks = append(masks, maskImage)
		}
		matches, err := vision.FindAllTemplates(sourceImage, templateImage, imageSimilarityProp(node), masks...)
		if err != nil {
			return "", err
		}
		rc.SetOutput(node, "matches", matches)
		rc.SetOutput(node, "count", len(matches))
		emitNodeShot(rc, node, sourceImage, matches)
		return "out", nil
	}
	rc.SetOutput(node, "matches", []vision.Match{})
	rc.SetOutput(node, "count", 0)
	return "out", nil
}

type OCREngine struct {
	Kind        string
	Unsupported bool
}

func (h OCREngine) Eval(_ context.Context, _ *flow.RunContext, node *flow.Node) (map[string]any, error) {
	config := map[string]any{}
	for key, value := range node.Properties {
		config[key] = value
	}
	return map[string]any{"ocr": map[string]any{
		"kind":        h.Kind,
		"config":      config,
		"unsupported": h.Unsupported,
	}}, nil
}

func (h OCREngine) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type FindText struct{}

func (FindText) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (FindText) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	video, _, err := rc.EvalInput(ctx, node, "video")
	if err != nil {
		return "", err
	}
	textValue, _, err := rc.EvalInput(ctx, node, "text")
	if err != nil {
		return "", err
	}
	ocrValue, _, err := rc.EvalInput(ctx, node, "ocr")
	if err != nil {
		return "", err
	}
	target := fmt.Sprint(textValue)
	blocks := textBlocksFromValue(video)
	minConfidence := ocrMinConfidence(ocrValue)
	if len(blocks) == 0 && isTesseractOCR(ocrValue) {
		sourceImage, ok, err := imageFromValue(ctx, video)
		if err != nil {
			return "", err
		}
		if ok {
			blocks, err = ocr.RecognizeTesseract(sourceImage, tesseractConfig(ocrValue))
			if err != nil {
				return "", err
			}
		}
	}
	match, found, err := findTextBlock(blocks, target, boolProp(node, "regex", false), minConfidence)
	if err != nil {
		return "", err
	}
	if found {
		rc.SetOutput(node, "match", match)
		rc.SetOutput(node, "ok", true)
		return "found", nil
	}
	rc.SetOutput(node, "match", nil)
	rc.SetOutput(node, "ok", false)
	return "notFound", nil
}

type ToPoint struct{}

func (ToPoint) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	value, _, err := rc.EvalInput(ctx, node, "match")
	if err != nil {
		return nil, err
	}
	match, err := matchFromValue(value)
	if err != nil {
		return nil, err
	}
	point := match.Point(stringProp(node, "anchor", "center"), numberProp(node, "dx", 0), numberProp(node, "dy", 0))
	return map[string]any{"point": point}, nil
}

func (ToPoint) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type ActionClick struct{}

func (ActionClick) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ActionClick) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	point, err := pointInput(ctx, rc, node, "target")
	if err != nil {
		return "", err
	}
	mouse, err := deviceInput(ctx, rc, node, "mouse")
	if err != nil {
		return "", err
	}
	button := device.Button(stringProp(node, "button", string(device.ButtonLeft)))
	if mouse != nil {
		if err := mouse.MouseMove(ctx, point.X, point.Y); err != nil {
			return "", err
		}
		if err := mouse.MouseDown(ctx, button, point.X, point.Y); err != nil {
			return "", err
		}
		if err := mouse.MouseUp(ctx, button, point.X, point.Y); err != nil {
			return "", err
		}
		if boolProp(node, "double", false) {
			if err := mouse.MouseDown(ctx, button, point.X, point.Y); err != nil {
				return "", err
			}
			if err := mouse.MouseUp(ctx, button, point.X, point.Y); err != nil {
				return "", err
			}
		}
		return "out", nil
	}
	message := fmt.Sprintf("planned click %s at (%d,%d)", button, point.X, point.Y)
	if boolProp(node, "double", false) {
		message = fmt.Sprintf("planned double click at (%d,%d)", point.X, point.Y)
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: message})
	return "out", nil
}

type ActionType struct{}

func (ActionType) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ActionType) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	text, _, err := rc.EvalInput(ctx, node, "text")
	if err != nil {
		return "", err
	}
	keyboard, err := deviceInput(ctx, rc, node, "keyboard")
	if err != nil {
		return "", err
	}
	if keyboard != nil {
		if err := keyboard.TypeText(ctx, fmt.Sprint(text)); err != nil {
			return "", err
		}
		return "out", nil
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: fmt.Sprintf("planned type %q", fmt.Sprint(text))})
	return "out", nil
}

type ActionHotkey struct{}

func (ActionHotkey) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ActionHotkey) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	keys, err := inputString(ctx, rc, node, "keys", "keys", "")
	if err != nil {
		return "", err
	}
	keys = strings.TrimSpace(keys)
	if keys == "" {
		return "", fmt.Errorf("hotkey missing keys")
	}
	keyboard, err := deviceInput(ctx, rc, node, "keyboard")
	if err != nil {
		return "", err
	}
	parts := parseHotkey(keys)
	if keyboard != nil {
		for _, key := range parts {
			if err := keyboard.KeyDown(ctx, device.Key(key)); err != nil {
				return "", err
			}
		}
		if err := rc.RunBranch(ctx, node, "hold"); err != nil {
			for i := len(parts) - 1; i >= 0; i-- {
				_ = keyboard.KeyUp(ctx, device.Key(parts[i]))
			}
			return "", err
		}
		for i := len(parts) - 1; i >= 0; i-- {
			if err := keyboard.KeyUp(ctx, device.Key(parts[i])); err != nil {
				return "", err
			}
		}
		return "out", nil
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: "planned hotkey " + keys})
	if err := rc.RunBranch(ctx, node, "hold"); err != nil {
		return "", err
	}
	return "out", nil
}

type ActionScroll struct{}

func (ActionScroll) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ActionScroll) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	point, err := pointInput(ctx, rc, node, "target")
	if err != nil {
		return "", err
	}
	mouse, err := deviceInput(ctx, rc, node, "mouse")
	if err != nil {
		return "", err
	}
	dy := numberProp(node, "dy", -1)
	if mouse != nil {
		if err := mouse.MouseMove(ctx, point.X, point.Y); err != nil {
			return "", err
		}
		if err := mouse.MouseWheel(ctx, dy); err != nil {
			return "", err
		}
		return "out", nil
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: fmt.Sprintf("planned scroll at (%d,%d) dy=%d", point.X, point.Y, dy)})
	return "out", nil
}

type ActionDrag struct{}

func (ActionDrag) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (ActionDrag) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	src, err := pointInput(ctx, rc, node, "src")
	if err != nil {
		return "", err
	}
	dst, err := pointInput(ctx, rc, node, "dst")
	if err != nil {
		return "", err
	}
	mouse, err := deviceInput(ctx, rc, node, "mouse")
	if err != nil {
		return "", err
	}
	if mouse != nil {
		if err := mouse.MouseMove(ctx, src.X, src.Y); err != nil {
			return "", err
		}
		if err := mouse.MouseDown(ctx, device.ButtonLeft, src.X, src.Y); err != nil {
			return "", err
		}
		if err := mouse.MouseMove(ctx, dst.X, dst.Y); err != nil {
			_ = mouse.MouseUp(ctx, device.ButtonLeft, dst.X, dst.Y)
			return "", err
		}
		if err := mouse.MouseUp(ctx, device.ButtonLeft, dst.X, dst.Y); err != nil {
			return "", err
		}
		return "out", nil
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: fmt.Sprintf("planned drag (%d,%d)->(%d,%d)", src.X, src.Y, dst.X, dst.Y)})
	return "out", nil
}

type DeviceAttrs struct{}

func (DeviceAttrs) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	value, _, err := rc.EvalInput(ctx, node, "device")
	if err != nil {
		return nil, err
	}
	width, height := deviceSize(value)
	return map[string]any{
		"video":    value,
		"mouse":    value,
		"keyboard": value,
		"width":    int(width),
		"height":   int(height),
	}, nil
}

func (DeviceAttrs) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type Interaction struct{}

func (Interaction) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	if _, _, err := rc.EvalInput(ctx, node, "device"); err != nil {
		return nil, err
	}
	return map[string]any{}, nil
}

func (Interaction) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, ok, err := rc.EvalInput(ctx, node, "device")
	if err != nil {
		return "", err
	}
	if !ok || value == nil {
		return "", fmt.Errorf("interaction node missing device input")
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok", Info: "interaction device attached"})
	return "", nil
}

type Log struct{}

func (Log) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Log) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "value")
	if err != nil {
		return "", err
	}
	label := stringProp(node, "label", "")
	message := fmt.Sprint(value)
	if label != "" {
		message = label + ": " + message
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok", Info: message})
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: message})
	return "out", nil
}

type Alert struct{}

func (Alert) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Alert) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "text")
	if err != nil {
		return "", err
	}
	message := fmt.Sprint(value)
	if value == nil || message == "" {
		message = stringProp(node, "message", "")
	}
	level := stringProp(node, "level", "info")
	rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: level, Message: message})
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok", Info: message})
	return "out", nil
}

type TextDisplay struct{}

func (TextDisplay) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	text, err := textDisplayValue(ctx, rc, node)
	if err != nil {
		return nil, err
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "node_text", ID: node.ID, Text: text})
	return map[string]any{"text": text}, nil
}

func (TextDisplay) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	text, err := textDisplayValue(ctx, rc, node)
	if err != nil {
		return "", err
	}
	rc.SetOutput(node, "text", text)
	rc.Runner.Sink.Emit(flow.Event{Type: "node_text", ID: node.ID, Text: text})
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: "ok", Info: text})
	return "out", nil
}

type VarGet struct{}

func (VarGet) Eval(_ context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	name := stringProp(node, "name", "v")
	value, ok := rc.Runner.Vars[name]
	if !ok {
		return nil, fmt.Errorf("variable %q is not set", name)
	}
	return map[string]any{"value": value}, nil
}

func (VarGet) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type VarSet struct{}

func (VarSet) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (VarSet) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	for _, input := range node.Inputs {
		if input.Name == "" || input.Type == "exec" {
			continue
		}
		value, _, err := rc.EvalInput(ctx, node, input.Name)
		if err != nil {
			return "", err
		}
		rc.Runner.Vars[input.Name] = value
	}
	return "out", nil
}

type Assert struct{}

func (Assert) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (Assert) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "cond")
	if err != nil {
		return "", err
	}
	ok := boolOf(value)
	message := stringProp(node, "message", "")
	status := "fail"
	port := "fail"
	if ok {
		status = "ok"
		port = "pass"
	}
	evidence := ""
	if !ok && rc.Runner != nil {
		evidence = rc.Runner.LastShotURL
	}
	rc.Runner.Sink.Emit(flow.Event{Type: "node", ID: node.ID, Status: status, Info: message})
	rc.Runner.Sink.Emit(flow.Event{Type: "assert", ID: node.ID, Status: status, Info: message, URL: evidence})
	return port, nil
}

type TestResult struct{}

func (TestResult) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (TestResult) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "", nil
}

type JSONSerialize struct{}

func (JSONSerialize) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	value, ok, err := rc.EvalInput(ctx, node, "value")
	if err != nil {
		return nil, err
	}
	if !ok || value == nil {
		raw := stringProp(node, "value", "")
		if strings.TrimSpace(raw) != "" {
			var parsed any
			if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
				return nil, fmt.Errorf("invalid JSON input: %w", err)
			}
			value = parsed
		}
	}
	var data []byte
	if boolProp(node, "pretty", false) {
		data, err = json.MarshalIndent(value, "", "  ")
	} else {
		data, err = json.Marshal(value)
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"text": string(data)}, nil
}

func (JSONSerialize) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type FormSerialize struct{}

func (FormSerialize) Eval(ctx context.Context, rc *flow.RunContext, node *flow.Node) (map[string]any, error) {
	value, _, err := rc.EvalInput(ctx, node, "value")
	if err != nil {
		return nil, err
	}
	if value == nil {
		raw := strings.TrimSpace(stringProp(node, "value", ""))
		if raw != "" {
			var parsed any
			if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
				return nil, fmt.Errorf("invalid form JSON input: %w", err)
			}
			value = parsed
		}
	}
	values := url.Values{}
	switch v := value.(type) {
	case map[string]any:
		for key, item := range v {
			addFormValue(values, key, item)
		}
	case nil:
	default:
		return nil, fmt.Errorf("form serialize expects object input")
	}
	return map[string]any{"text": values.Encode()}, nil
}

func (FormSerialize) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type APIRequest struct{}

func (APIRequest) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (APIRequest) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	method := strings.ToUpper(stringProp(node, "method", "GET"))
	switch method {
	case "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD":
	default:
		return "", fmt.Errorf("unsupported HTTP method: %s", method)
	}
	reqURL, err := inputString(ctx, rc, node, "url", "url", "")
	if err != nil {
		return "", err
	}
	reqURL = strings.TrimSpace(reqURL)
	if reqURL == "" {
		return "", fmt.Errorf("HTTP request missing URL")
	}
	headersText, err := inputString(ctx, rc, node, "headers", "headers", "{}")
	if err != nil {
		return "", err
	}
	headers, err := parseHeaders(headersText)
	if err != nil {
		return "", err
	}
	bodyText, err := inputString(ctx, rc, node, "body", "body", "")
	if err != nil {
		return "", err
	}
	var body io.Reader
	if bodyText != "" && method != "GET" && method != "HEAD" {
		body = strings.NewReader(bodyText)
		if !hasHeader(headers, "content-type") {
			contentType := strings.TrimSpace(stringProp(node, "content_type", "application/json; charset=utf-8"))
			if contentType != "" {
				headers["Content-Type"] = contentType
			}
		}
	}
	timeout := time.Duration(numberProp(node, "timeout", 15)) * time.Second
	if timeout <= 0 {
		timeout = 15 * time.Second
	}
	request, err := http.NewRequestWithContext(ctx, method, reqURL, body)
	if err != nil {
		return "", err
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	client := &http.Client{Timeout: timeout}
	status := 0
	text := ""
	ok := false
	response, err := client.Do(request)
	if err != nil {
		text = err.Error()
	} else {
		defer response.Body.Close()
		status = response.StatusCode
		payload, readErr := io.ReadAll(response.Body)
		if readErr != nil {
			return "", readErr
		}
		text = string(payload)
		ok = status >= 200 && status < 400
	}
	rc.SetOutput(node, "status", status)
	rc.SetOutput(node, "body", text)
	rc.SetOutput(node, "ok", ok)
	if boolProp(node, "fail_on_error", false) && !ok {
		return "", fmt.Errorf("HTTP request failed: %d %s", status, truncate(text, 300))
	}
	if ok {
		return "success", nil
	}
	return "fail", nil
}

type JSScript struct{}

func (JSScript) Eval(_ context.Context, _ *flow.RunContext, node *flow.Node) (map[string]any, error) {
	return map[string]any{"script": stringProp(node, "code", "")}, nil
}

func (JSScript) Run(context.Context, *flow.RunContext, *flow.Node) (string, error) {
	return "out", nil
}

type JSExec struct{}

func (JSExec) Eval(context.Context, *flow.RunContext, *flow.Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (JSExec) Run(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	scriptValue, _, err := rc.EvalInput(ctx, node, "script")
	if err != nil {
		return "", err
	}
	code := fmt.Sprint(scriptValue)
	if code == "" {
		return "", fmt.Errorf("JS exec missing script input")
	}
	args := map[string]any{}
	for _, input := range node.Inputs {
		if input.Name == "" || input.Type == "exec" || input.Name == "script" {
			continue
		}
		value, _, err := rc.EvalInput(ctx, node, input.Name)
		if err != nil {
			return "", err
		}
		args[input.Name] = value
	}
	response, err := jsplugin.NewRuntime().Run(ctx, jsplugin.Request{Code: code, Args: args})
	if err != nil {
		return "", err
	}
	allowedResults := dataOutputPorts(node)
	for name, value := range response.Results {
		if _, ok := allowedResults[name]; !ok {
			return "", fmt.Errorf("JS result %q is not declared on node outputs", name)
		}
		rc.SetOutput(node, name, value)
	}
	for _, line := range response.Logs {
		rc.Runner.Sink.Emit(flow.Event{Type: "alert", ID: node.ID, Level: "log", Message: line})
	}
	return "out", nil
}

func numberProp(node *flow.Node, name string, fallback int) int {
	return int(numberFloatProp(node, name, float64(fallback)))
}

func numberFloatProp(node *flow.Node, name string, fallback float64) float64 {
	if node.Properties == nil {
		return fallback
	}
	switch v := node.Properties[name].(type) {
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case float64:
		return v
	default:
		return fallback
	}
}

func imageSimilarityProp(node *flow.Node) float64 {
	if node != nil && node.Properties != nil {
		if _, ok := node.Properties["threshold"]; ok {
			return numberFloatProp(node, "threshold", 0.7)
		}
	}
	return numberFloatProp(node, "similarity", 0.7)
}

func stringProp(node *flow.Node, name string, fallback string) string {
	if node.Properties == nil {
		return fallback
	}
	value, ok := node.Properties[name]
	if !ok || value == nil {
		return fallback
	}
	return fmt.Sprint(value)
}

func stringOr(value any, fallback string) string {
	if value == nil {
		return fallback
	}
	text := fmt.Sprint(value)
	if text == "" {
		return fallback
	}
	return text
}

func boolProp(node *flow.Node, name string, fallback bool) bool {
	if node.Properties == nil {
		return fallback
	}
	value, ok := node.Properties[name]
	if !ok {
		return fallback
	}
	return boolOf(value)
}

func textDisplayValue(ctx context.Context, rc *flow.RunContext, node *flow.Node) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, "text")
	if err != nil {
		return "", err
	}
	if value == nil || fmt.Sprint(value) == "" {
		value = stringProp(node, "placeholder", "")
	}
	if value == nil {
		return "", nil
	}
	return fmt.Sprint(value), nil
}

func boolOf(value any) bool {
	switch v := value.(type) {
	case bool:
		return v
	case string:
		return v != "" && v != "false" && v != "0"
	case float64:
		return v != 0
	case int:
		return v != 0
	case int64:
		return v != 0
	default:
		return value != nil
	}
}

func numberOf(value any, fallback float64) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case json.Number:
		f, err := v.Float64()
		if err == nil {
			return f
		}
		return fallback
	default:
		return fallback
	}
}

func addFormValue(values url.Values, key string, value any) {
	switch v := value.(type) {
	case []any:
		for _, item := range v {
			values.Add(key, fmt.Sprint(item))
		}
	case []string:
		for _, item := range v {
			values.Add(key, item)
		}
	default:
		values.Add(key, fmt.Sprint(value))
	}
}

func inputString(ctx context.Context, rc *flow.RunContext, node *flow.Node, inputName, propName, fallback string) (string, error) {
	value, _, err := rc.EvalInput(ctx, node, inputName)
	if err != nil {
		return "", err
	}
	if value == nil || fmt.Sprint(value) == "" {
		return stringProp(node, propName, fallback), nil
	}
	return fmt.Sprint(value), nil
}

func parseHeaders(raw string) (map[string]string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return map[string]string{}, nil
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		return nil, fmt.Errorf("invalid headers JSON: %w", err)
	}
	out := map[string]string{}
	for key, value := range parsed {
		if value != nil {
			out[key] = fmt.Sprint(value)
		}
	}
	return out, nil
}

func hasHeader(headers map[string]string, name string) bool {
	for key := range headers {
		if strings.EqualFold(key, name) {
			return true
		}
	}
	return false
}

func truncate(text string, max int) string {
	if len(text) <= max {
		return text
	}
	return text[:max]
}

func matchFromValue(value any) (vision.Match, error) {
	switch v := value.(type) {
	case vision.Match:
		return v, nil
	case *vision.Match:
		if v == nil {
			return vision.Match{}, fmt.Errorf("match input is nil")
		}
		return *v, nil
	case map[string]any:
		return vision.Match{
			X:     int(numberOf(v["x"], 0)),
			Y:     int(numberOf(v["y"], 0)),
			W:     int(numberOf(v["w"], 0)),
			H:     int(numberOf(v["h"], 0)),
			Score: numberOf(v["score"], 0),
		}, nil
	default:
		return vision.Match{}, fmt.Errorf("unsupported match value %T", value)
	}
}

func textBlocksFromValue(value any) []ocr.TextBlock {
	switch v := value.(type) {
	case []ocr.TextBlock:
		return v
	case []any:
		return textBlocksFromList(v)
	case map[string]any:
		for _, key := range []string{"blocks", "text_blocks", "ocr_blocks"} {
			if blocks := textBlocksFromValue(v[key]); len(blocks) > 0 {
				return blocks
			}
		}
		if text, ok := v["text"].(string); ok && text != "" {
			return []ocr.TextBlock{blockFromMap(v, text)}
		}
	}
	return nil
}

func textBlocksFromList(values []any) []ocr.TextBlock {
	blocks := make([]ocr.TextBlock, 0, len(values))
	for _, value := range values {
		switch v := value.(type) {
		case ocr.TextBlock:
			blocks = append(blocks, v)
		case map[string]any:
			text := fmt.Sprint(v["text"])
			if strings.TrimSpace(text) != "" {
				blocks = append(blocks, blockFromMap(v, text))
			}
		}
	}
	return blocks
}

func blockFromMap(value map[string]any, text string) ocr.TextBlock {
	confidence := numberOf(value["confidence"], numberOf(value["score"], 1))
	return ocr.TextBlock{
		Text:       text,
		Confidence: confidence,
		X:          int(numberOf(value["x"], 0)),
		Y:          int(numberOf(value["y"], 0)),
		W:          int(numberOf(value["w"], numberOf(value["width"], 0))),
		H:          int(numberOf(value["h"], numberOf(value["height"], 0))),
	}
}

func ocrMinConfidence(value any) float64 {
	config := map[string]any{}
	if m, ok := value.(map[string]any); ok {
		if cfg, ok := m["config"].(map[string]any); ok {
			config = cfg
		}
	}
	min := numberOf(config["min_confidence"], 0)
	if min > 1 {
		min = min / 100
	}
	return min
}

func isTesseractOCR(value any) bool {
	m, ok := value.(map[string]any)
	if !ok {
		return false
	}
	return fmt.Sprint(m["kind"]) == "tesseract" && !boolOf(m["unsupported"])
}

func tesseractConfig(value any) ocr.TesseractConfig {
	m, _ := value.(map[string]any)
	config, _ := m["config"].(map[string]any)
	return ocr.TesseractConfig{
		Lang:           stringOr(config["lang"], "eng"),
		Config:         stringOr(config["config"], ""),
		TessdataPrefix: stringOr(config["tessdata_prefix"], ""),
		MinConfidence:  numberOf(config["min_confidence"], 0),
	}
}

func findTextBlock(blocks []ocr.TextBlock, target string, regex bool, minConfidence float64) (map[string]any, bool, error) {
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
	for _, block := range blocks {
		if block.Confidence < minConfidence {
			continue
		}
		if !textMatches(block.Text, target, pattern) {
			continue
		}
		return map[string]any{
			"x":     block.X,
			"y":     block.Y,
			"w":     block.W,
			"h":     block.H,
			"score": block.Confidence,
			"text":  block.Text,
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

func requiredInput(ctx context.Context, rc *flow.RunContext, node *flow.Node, port string) (any, error) {
	value, ok, err := rc.EvalInput(ctx, node, port)
	if err != nil {
		return nil, err
	}
	if !ok || value == nil {
		return nil, fmt.Errorf("%s missing required input %q", node.Type, port)
	}
	return value, nil
}

func pointInput(ctx context.Context, rc *flow.RunContext, node *flow.Node, port string) (vision.Point, error) {
	value, err := requiredInput(ctx, rc, node, port)
	if err != nil {
		return vision.Point{}, err
	}
	return pointFromValue(value)
}

func deviceInput(ctx context.Context, rc *flow.RunContext, node *flow.Node, port string) (device.Device, error) {
	value, err := requiredInput(ctx, rc, node, port)
	if err != nil {
		return nil, err
	}
	switch v := value.(type) {
	case device.Ref:
		return v.Device, nil
	case *device.Ref:
		if v == nil {
			return nil, nil
		}
		return v.Device, nil
	default:
		return nil, nil
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

func imageFromValue(ctx context.Context, value any) (image.Image, bool, error) {
	switch v := value.(type) {
	case nil:
		return nil, false, nil
	case image.Image:
		return v, true, nil
	case device.Ref:
		if v.Device == nil {
			return nil, false, nil
		}
		img, err := device.CaptureImage(ctx, v.Device)
		if err != nil {
			return nil, false, err
		}
		return img, img != nil, nil
	case *device.Ref:
		if v == nil || v.Device == nil {
			return nil, false, nil
		}
		img, err := device.CaptureImage(ctx, v.Device)
		if err != nil {
			return nil, false, err
		}
		return img, img != nil, nil
	default:
		return nil, false, nil
	}
}

func imageInputs(ctx context.Context, rc *flow.RunContext, node *flow.Node) (image.Image, bool, image.Image, error) {
	video, _, err := rc.EvalInput(ctx, node, "video")
	if err != nil {
		return nil, false, nil, err
	}
	mask, _, err := rc.EvalInput(ctx, node, "mask")
	if err != nil {
		return nil, false, nil, err
	}
	sourceImage, sourceOK, err := imageFromValue(ctx, video)
	if err != nil {
		return nil, false, nil, err
	}
	maskImage, _, err := imageFromValue(ctx, mask)
	return sourceImage, sourceOK, maskImage, err
}

func emitNodeShot(rc *flow.RunContext, node *flow.Node, img image.Image, matches []vision.Match) {
	if rc == nil || rc.Runner == nil || rc.Runner.ShotSink == nil || img == nil {
		return
	}
	rects := make([]image.Rectangle, 0, len(matches))
	for _, match := range matches {
		if match.W <= 0 || match.H <= 0 {
			continue
		}
		rects = append(rects, image.Rect(match.X, match.Y, match.X+match.W, match.Y+match.H))
	}
	url, err := rc.Runner.ShotSink(node.ID, img, rects)
	if err != nil || url == "" {
		return
	}
	rc.Runner.LastShotURL = url
	rc.Runner.Sink.Emit(flow.Event{Type: "node_shot", ID: node.ID, URL: url})
}

func waitForImageState(ctx context.Context, rc *flow.RunContext, node *flow.Node, wantAppear bool) (vision.Match, bool, bool, error) {
	timeout := numberFloatProp(node, "timeout", 10)
	deadline := time.Now().Add(time.Duration(timeout * float64(time.Second)))
	for {
		match, found, observed, err := findImageOnce(ctx, rc, node)
		if err != nil {
			return vision.Match{}, false, false, err
		}
		if observed {
			if wantAppear && found {
				return match, true, true, nil
			}
			if !wantAppear && !found {
				return vision.Match{}, false, true, nil
			}
		}
		if timeout <= 0 || time.Now().After(deadline) {
			return match, found, observed, nil
		}
		timer := time.NewTimer(100 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return vision.Match{}, false, false, ctx.Err()
		case <-timer.C:
		}
	}
}

func findImageOnce(ctx context.Context, rc *flow.RunContext, node *flow.Node) (vision.Match, bool, bool, error) {
	video, _, err := rc.EvalInput(ctx, node, "video")
	if err != nil {
		return vision.Match{}, false, false, err
	}
	template, _, err := rc.EvalInput(ctx, node, "template")
	if err != nil {
		return vision.Match{}, false, false, err
	}
	mask, _, err := rc.EvalInput(ctx, node, "mask")
	if err != nil {
		return vision.Match{}, false, false, err
	}
	sourceImage, sourceOK, err := imageFromValue(ctx, video)
	if err != nil {
		return vision.Match{}, false, false, err
	}
	templateImage, templateOK, err := imageFromValue(ctx, template)
	if err != nil {
		return vision.Match{}, false, false, err
	}
	if !sourceOK || !templateOK {
		return vision.Match{}, false, false, nil
	}
	maskImage, maskOK, err := imageFromValue(ctx, mask)
	if err != nil {
		return vision.Match{}, false, false, err
	}
	var masks []image.Image
	if maskOK {
		masks = append(masks, maskImage)
	}
	match, found, err := vision.FindTemplate(sourceImage, templateImage, imageSimilarityProp(node), masks...)
	return match, found, true, err
}

func pointFromValue(value any) (vision.Point, error) {
	switch v := value.(type) {
	case vision.Point:
		return v, nil
	case *vision.Point:
		if v == nil {
			return vision.Point{}, fmt.Errorf("point input is nil")
		}
		return *v, nil
	case map[string]any:
		return vision.Point{X: int(numberOf(v["x"], 0)), Y: int(numberOf(v["y"], 0))}, nil
	case []any:
		if len(v) < 2 {
			return vision.Point{}, fmt.Errorf("point array requires two values")
		}
		return vision.Point{X: int(numberOf(v[0], 0)), Y: int(numberOf(v[1], 0))}, nil
	default:
		match, err := matchFromValue(value)
		if err == nil {
			return match.Point("center", 0, 0), nil
		}
		return vision.Point{}, fmt.Errorf("unsupported point value %T", value)
	}
}

func dataOutputPorts(node *flow.Node) map[string]struct{} {
	out := map[string]struct{}{}
	for _, port := range node.Outputs {
		if port.Name == "" || port.Type == "exec" {
			continue
		}
		out[port.Name] = struct{}{}
	}
	return out
}

func deviceSize(value any) (float64, float64) {
	switch v := value.(type) {
	case device.Ref:
		return float64(v.Width), float64(v.Height)
	case *device.Ref:
		if v == nil {
			return 0, 0
		}
		return float64(v.Width), float64(v.Height)
	case map[string]any:
		return numberOf(v["width"], 0), numberOf(v["height"], 0)
	default:
		return 0, 0
	}
}
