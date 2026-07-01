package nodes

import (
	"context"
	"fmt"
	"image"
	"image/color"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"flow-test-go/internal/device"
	"flow-test-go/internal/flow"
	"flow-test-go/internal/vision"
)

func TestIfAssertAndTextDisplayFlow(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "flow/if", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "cond", Type: "bool"}}},
			{ID: 3, Type: "const/bool", Properties: map[string]any{"value": true}},
			{ID: 4, Type: "assert/check", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "cond", Type: "bool"}}},
			{ID: 5, Type: "test/result"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 2, ToPort: "in"},
			{FromID: 3, FromPort: "bool", ToID: 2, ToPort: "cond"},
			{FromID: 2, FromPort: "true", ToID: 4, ToPort: "in"},
			{FromID: 3, FromPort: "bool", ToID: 4, ToPort: "cond"},
			{FromID: 4, FromPort: "pass", ToID: 5, ToPort: "in"},
		},
	}
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, NewRegistry(), sink)
	if err := runner.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if got := sink.Events[len(sink.Events)-1]; got.Type != "run" || got.Status != "done" {
		t.Fatalf("last event = %#v, want run done", got)
	}
	foundAssertOK := false
	for _, event := range sink.Events {
		if event.ID == 4 && event.Status == "ok" {
			foundAssertOK = true
		}
	}
	if !foundAssertOK {
		t.Fatalf("assert/check ok event not found in %#v", sink.Events)
	}
}

func TestJSONAndFormSerialize(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "api/json_serialize", Properties: map[string]any{"value": `{"a":1}`, "pretty": false}},
			{ID: 2, Type: "api/form_serialize", Properties: map[string]any{"value": `{"q":"hello world"}`}},
		},
	}
	runner := flow.NewRunner(graph, NewRegistry(), &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	jsonOut, err := NewRegistry().handlers["api/json_serialize"].Eval(context.Background(), rc, &graph.Nodes[0])
	if err != nil {
		t.Fatalf("json serialize error = %v", err)
	}
	if jsonOut["text"] != `{"a":1}` {
		t.Fatalf("json text = %q", jsonOut["text"])
	}
	formOut, err := NewRegistry().handlers["api/form_serialize"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("form serialize error = %v", err)
	}
	if formOut["text"] != "q=hello+world" {
		t.Fatalf("form text = %q", formOut["text"])
	}
}

func TestRegexFind(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "regex/find", Properties: map[string]any{"text": "order id: A-42", "pattern": `([A-Z])-(\d+)`}},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["regex/find"].Run(context.Background(), rc, &graph.Nodes[0])
	if err != nil {
		t.Fatalf("regex find error = %v", err)
	}
	if port != "found" {
		t.Fatalf("port = %s, want found", port)
	}
	if runner.Values[flow.OutputRef{NodeID: 1, Port: "ok"}] != true ||
		runner.Values[flow.OutputRef{NodeID: 1, Port: "match"}] != "A" {
		t.Fatalf("regex outputs = %#v", runner.Values)
	}
	graph.Nodes[0].Properties["pattern"] = "["
	if _, err := registry.handlers["regex/find"].Run(context.Background(), rc, &graph.Nodes[0]); err == nil {
		t.Fatal("invalid regex error = nil")
	}
}

func TestAPIRequestSetsOutputsAndSuccessBranch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("method = %s, want POST", r.Method)
		}
		if r.Header.Get("X-Test") != "yes" {
			t.Fatalf("X-Test = %q, want yes", r.Header.Get("X-Test"))
		}
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte("created"))
	}))
	defer server.Close()

	graph := flow.Graph{
		Nodes: []flow.Node{
			{
				ID:   1,
				Type: "api/request",
				Properties: map[string]any{
					"method":  "POST",
					"url":     server.URL,
					"headers": `{"X-Test":"yes"}`,
					"body":    `{"ok":true}`,
				},
			},
		},
	}
	runner := flow.NewRunner(graph, NewRegistry(), &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	port, err := NewRegistry().handlers["api/request"].Run(context.Background(), rc, &graph.Nodes[0])
	if err != nil {
		t.Fatalf("api request error = %v", err)
	}
	if port != "success" {
		t.Fatalf("port = %s, want success", port)
	}
	if runner.Values[flow.OutputRef{NodeID: 1, Port: "status"}] != 201 {
		t.Fatalf("status output = %#v", runner.Values[flow.OutputRef{NodeID: 1, Port: "status"}])
	}
	if runner.Values[flow.OutputRef{NodeID: 1, Port: "body"}] != "created" {
		t.Fatalf("body output = %#v", runner.Values[flow.OutputRef{NodeID: 1, Port: "body"}])
	}
	if runner.Values[flow.OutputRef{NodeID: 1, Port: "ok"}] != true {
		t.Fatalf("ok output = %#v", runner.Values[flow.OutputRef{NodeID: 1, Port: "ok"}])
	}
}

func TestTryCatchCapturesRaiseAndContinuesDone(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "flow/try_catch"},
			{ID: 3, Type: "flow/raise", Properties: map[string]any{"message": "boom"}},
			{ID: 4, Type: "util/alert", Properties: map[string]any{"message": "handled"}},
			{ID: 5, Type: "test/result"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 2, ToPort: "in"},
			{FromID: 2, FromPort: "try", ToID: 3, ToPort: "in"},
			{FromID: 2, FromPort: "catch", ToID: 4, ToPort: "in"},
			{FromID: 2, FromPort: "done", ToID: 5, ToPort: "in"},
		},
	}
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, NewRegistry(), sink)
	if err := runner.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if runner.Values[flow.OutputRef{NodeID: 2, Port: "error"}] != "boom" {
		t.Fatalf("caught error = %#v", runner.Values[flow.OutputRef{NodeID: 2, Port: "error"}])
	}
	if runner.Values[flow.OutputRef{NodeID: 2, Port: "error_node"}] != int64(3) {
		t.Fatalf("error node = %#v", runner.Values[flow.OutputRef{NodeID: 2, Port: "error_node"}])
	}
	if got := sink.Events[len(sink.Events)-1]; got.Type != "run" || got.Status != "done" {
		t.Fatalf("last event = %#v, want run done", got)
	}
}

func TestPointConstUsesInputBeforeProperties(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "const/number", Properties: map[string]any{"value": 9}},
			{ID: 2, Type: "const/point", Properties: map[string]any{"x": 1, "y": 2}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "number", ToID: 2, ToPort: "x"},
		},
	}
	runner := flow.NewRunner(graph, NewRegistry(), &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	out, err := NewRegistry().handlers["const/point"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("point eval error = %v", err)
	}
	point := out["point"].(map[string]any)
	if point["x"] != 9 || point["y"] != 2 {
		t.Fatalf("point = %#v, want x=9 y=2", point)
	}
}

func TestJSScriptEvalAndExecRuntimeBoundary(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "script/js", Properties: map[string]any{"code": "setResult('ok', true)"}},
			{
				ID:      2,
				Type:    "script/js_exec",
				Inputs:  []flow.Port{{Name: "in", Type: "exec"}, {Name: "script", Type: "script"}, {Name: "name", Type: "text"}},
				Outputs: []flow.Port{{Name: "out", Type: "exec"}, {Name: "ok", Type: "bool"}},
			},
			{ID: 3, Type: "const/text", Properties: map[string]any{"value": "alice"}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "script", ToID: 2, ToPort: "script"},
			{FromID: 3, FromPort: "text", ToID: 2, ToPort: "name"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	out, err := registry.handlers["script/js"].Eval(context.Background(), rc, &graph.Nodes[0])
	if err != nil {
		t.Fatalf("script eval error = %v", err)
	}
	if out["script"] != "setResult('ok', true)" {
		t.Fatalf("script output = %#v", out["script"])
	}
	_, err = registry.handlers["script/js_exec"].Run(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("js exec error = %v", err)
	}
	if runner.Values[flow.OutputRef{NodeID: 2, Port: "ok"}] != true {
		t.Fatalf("js ok result = %#v", runner.Values[flow.OutputRef{NodeID: 2, Port: "ok"}])
	}
}

func TestJSExecResultFeedsAssertInFlow(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "script/js", Properties: map[string]any{"code": "setResult('ok', getArg('name') === 'alice')"}},
			{
				ID:      3,
				Type:    "script/js_exec",
				Inputs:  []flow.Port{{Name: "in", Type: "exec"}, {Name: "script", Type: "script"}, {Name: "name", Type: "text"}},
				Outputs: []flow.Port{{Name: "out", Type: "exec"}, {Name: "ok", Type: "bool"}},
			},
			{ID: 4, Type: "const/text", Properties: map[string]any{"value": "alice"}},
			{ID: 5, Type: "assert/check", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "cond", Type: "bool"}}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 3, ToPort: "in"},
			{FromID: 2, FromPort: "script", ToID: 3, ToPort: "script"},
			{FromID: 4, FromPort: "text", ToID: 3, ToPort: "name"},
			{FromID: 3, FromPort: "out", ToID: 5, ToPort: "in"},
			{FromID: 3, FromPort: "ok", ToID: 5, ToPort: "cond"},
		},
	}
	sink := &flow.CollectingSink{}
	if err := flow.NewRunner(graph, NewRegistry(), sink).Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	foundAssertOK := false
	for _, event := range sink.Events {
		if event.Type == "assert" && event.ID == 5 && event.Status == "ok" {
			foundAssertOK = true
		}
	}
	if !foundAssertOK {
		t.Fatalf("assert ok event not found: %#v", sink.Events)
	}
}

func TestJSExecLogEmitsAlertEvent(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "script/js", Properties: map[string]any{"code": "log('hello'); setResult('ok', true)"}},
			{ID: 2, Type: "script/js_exec", Inputs: []flow.Port{{Name: "script", Type: "script"}}, Outputs: []flow.Port{{Name: "ok", Type: "bool"}}},
		},
		Links: []flow.Link{{FromID: 1, FromPort: "script", ToID: 2, ToPort: "script"}},
	}
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, NewRegistry(), sink)
	rc := &flow.RunContext{Runner: runner}
	if _, err := NewRegistry().handlers["script/js_exec"].Run(context.Background(), rc, &graph.Nodes[1]); err != nil {
		t.Fatalf("JS exec error = %v", err)
	}
	found := false
	for _, event := range sink.Events {
		if event.Type == "alert" && event.Level == "log" && event.Message == "hello" {
			found = true
		}
	}
	if !found {
		t.Fatalf("log alert not found: %#v", sink.Events)
	}
}

func TestJSExecRejectsUndeclaredResult(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "script/js", Properties: map[string]any{"code": "setResult('secret', true)"}},
			{
				ID:      2,
				Type:    "script/js_exec",
				Inputs:  []flow.Port{{Name: "script", Type: "script"}},
				Outputs: []flow.Port{{Name: "out", Type: "exec"}},
			},
		},
		Links: []flow.Link{{FromID: 1, FromPort: "script", ToID: 2, ToPort: "script"}},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	_, err := registry.handlers["script/js_exec"].Run(context.Background(), rc, &graph.Nodes[1])
	if err == nil {
		t.Fatalf("JS exec error = nil, want undeclared result error")
	}
}

func TestDeviceAttrsFromDevicePlaceholder(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "device/rdp", Properties: map[string]any{"host": "127.0.0.1", "width": 1024, "height": 768}},
			{ID: 2, Type: "device/attrs"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "device", ToID: 2, ToPort: "device"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	out, err := registry.handlers["device/attrs"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("device attrs error = %v", err)
	}
	video := out["video"].(device.Ref)
	if video.Resource != "device" {
		t.Fatalf("device resource marker = %#v", video.Resource)
	}
	if out["width"] != 1024 || out["height"] != 768 {
		t.Fatalf("attrs width/height = %#v/%#v", out["width"], out["height"])
	}
	if out["video"] == nil || out["mouse"] == nil || out["keyboard"] == nil {
		t.Fatalf("device capability outputs missing: %#v", out)
	}
}

func TestInteractionConsumesDevice(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "device/rdp", Properties: map[string]any{"host": "127.0.0.1", "width": 1024, "height": 768}},
			{ID: 2, Type: "io/interaction"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "device", ToID: 2, ToPort: "device"},
		},
	}
	registry := NewRegistry()
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, registry, sink)
	rc := &flow.RunContext{Runner: runner}
	next, err := registry.handlers["io/interaction"].Run(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("interaction error = %v", err)
	}
	if next != "" {
		t.Fatalf("interaction next = %q", next)
	}
	if len(sink.Events) != 1 || sink.Events[0].Info != "interaction device attached" {
		t.Fatalf("events = %#v", sink.Events)
	}
}

func TestDeviceSourceUsesRunnerResolver(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "device/rdp", Properties: map[string]any{"host": "127.0.0.1", "width": 1024, "height": 768}},
			{ID: 2, Type: "device/attrs"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "device", ToID: 2, ToPort: "device"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.DeviceResolver = func(node *flow.Node) (any, bool) {
		if node.ID != 1 {
			return nil, false
		}
		return device.NewUnsupportedRef("rdp", map[string]any{"host": "live"}, 1600, 900), true
	}
	rc := &flow.RunContext{Runner: runner}
	out, err := registry.handlers["device/attrs"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("device attrs error = %v", err)
	}
	if out["width"] != 1600 || out["height"] != 900 {
		t.Fatalf("attrs width/height = %#v/%#v", out["width"], out["height"])
	}
	ref := out["video"].(device.Ref)
	if ref.Config["host"] != "live" {
		t.Fatalf("resolved ref config = %#v", ref.Config)
	}
}

func TestImagePreviewAndMaskResourceRefs(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "const/image", Properties: map[string]any{"name": "button.png"}},
			{ID: 2, Type: "vision/preview"},
			{ID: 3, Type: "mask/create", Properties: map[string]any{"mask": "button.mask.png"}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "picture", ToID: 2, ToPort: "picture"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	rc := &flow.RunContext{Runner: runner}
	preview, err := registry.handlers["vision/preview"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("preview eval error = %v", err)
	}
	picture := preview["picture"].(map[string]any)
	if picture["name"] != "button.png" {
		t.Fatalf("picture = %#v", picture)
	}
	mask, err := registry.handlers["mask/create"].Eval(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("mask eval error = %v", err)
	}
	maskRef := mask["mask"].(map[string]any)
	if maskRef["name"] != "button.mask.png" {
		t.Fatalf("mask = %#v", maskRef)
	}
}

func TestImageConstUsesRunnerResolver(t *testing.T) {
	img := image.NewRGBA(image.Rect(0, 0, 2, 2))
	graph := flow.Graph{Nodes: []flow.Node{
		{ID: 1, Type: "const/image", Properties: map[string]any{"name": "button.png"}},
	}}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.ImageResolver = func(name string) (any, bool, error) {
		if name != "button.png" {
			return nil, false, nil
		}
		return img, true, nil
	}
	rc := &flow.RunContext{Runner: runner}
	out, err := registry.handlers["const/image"].Eval(context.Background(), rc, &graph.Nodes[0])
	if err != nil {
		t.Fatalf("image const eval error = %v", err)
	}
	if out["picture"] != img {
		t.Fatalf("picture = %#v", out["picture"])
	}
}

func TestToPointFromMatch(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "match/source"},
			{ID: 2, Type: "geom/to_point", Properties: map[string]any{"anchor": "bottom-right", "dx": 2, "dy": -3}},
		},
		Links: []flow.Link{{FromID: 1, FromPort: "match", ToID: 2, ToPort: "match"}},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "match"}] = vision.Match{X: 10, Y: 20, W: 30, H: 40}
	rc := &flow.RunContext{Runner: runner}
	out, err := registry.handlers["geom/to_point"].Eval(context.Background(), rc, &graph.Nodes[1])
	if err != nil {
		t.Fatalf("to_point eval error = %v", err)
	}
	point := out["point"].(vision.Point)
	if point.X != 42 || point.Y != 57 {
		t.Fatalf("point = %#v", point)
	}
}

func TestVisionFindPlaceholders(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "picture/source"},
			{ID: 3, Type: "vision/find_image"},
			{ID: 4, Type: "vision/find_all"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 3, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 3, ToPort: "template"},
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "template"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = map[string]any{"kind": "placeholder"}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "picture"}] = map[string]any{"name": "button.png"}
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_image"].Run(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("find_image error = %v", err)
	}
	if port != "notFound" || runner.Values[flow.OutputRef{NodeID: 3, Port: "ok"}] != false {
		t.Fatalf("find_image port/ok = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 3, Port: "ok"}])
	}
	port, err = registry.handlers["vision/find_all"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_all error = %v", err)
	}
	if port != "out" || runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}] != 0 {
		t.Fatalf("find_all port/count = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}])
	}
}

func TestVisionFindImageWithImages(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 8, 8))
	fillImage(source, color.RGBA{R: 5, G: 5, B: 5, A: 255})
	fillImageRect(source, image.Rect(4, 3, 6, 5), color.RGBA{R: 240, G: 20, B: 30, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillImage(template, color.RGBA{R: 240, G: 20, B: 30, A: 255})
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "picture/source"},
			{ID: 3, Type: "vision/find_image", Properties: map[string]any{"threshold": 0.99}},
			{ID: 4, Type: "vision/find_all", Properties: map[string]any{"threshold": 0.99}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 3, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 3, ToPort: "template"},
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "template"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = source
	runner.Values[flow.OutputRef{NodeID: 2, Port: "picture"}] = template
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_image"].Run(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("find_image error = %v", err)
	}
	if port != "found" || runner.Values[flow.OutputRef{NodeID: 3, Port: "ok"}] != true {
		t.Fatalf("find_image port/ok = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 3, Port: "ok"}])
	}
	match := runner.Values[flow.OutputRef{NodeID: 3, Port: "match"}].(vision.Match)
	if match.X != 4 || match.Y != 3 || match.W != 2 || match.H != 2 {
		t.Fatalf("match = %#v", match)
	}
	port, err = registry.handlers["vision/find_all"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_all error = %v", err)
	}
	if port != "out" || runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}] != 1 {
		t.Fatalf("find_all port/count = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}])
	}
}

func TestVisionFindImageWithMask(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 6, 4))
	fillImage(source, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	source.SetRGBA(2, 1, color.RGBA{R: 220, A: 255})
	source.SetRGBA(3, 1, color.RGBA{B: 220, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 1))
	template.SetRGBA(0, 0, color.RGBA{R: 220, A: 255})
	template.SetRGBA(1, 0, color.RGBA{G: 220, A: 255})
	mask := image.NewRGBA(image.Rect(0, 0, 2, 1))
	mask.SetRGBA(0, 0, color.RGBA{R: 255, G: 255, B: 255, A: 255})
	mask.SetRGBA(1, 0, color.RGBA{A: 255})
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "const/image", Properties: map[string]any{"name": "source.png"}},
			{ID: 2, Type: "const/image", Properties: map[string]any{"name": "template.png"}},
			{ID: 3, Type: "mask/create", Properties: map[string]any{"mask": "mask.png"}},
			{ID: 4, Type: "vision/find_image", Properties: map[string]any{"threshold": 0.99}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "picture", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "template"},
			{FromID: 3, FromPort: "mask", ToID: 4, ToPort: "mask"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.ImageResolver = func(name string) (any, bool, error) {
		switch name {
		case "source.png":
			return source, true, nil
		case "template.png":
			return template, true, nil
		case "mask.png":
			return mask, true, nil
		default:
			return nil, false, nil
		}
	}
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_image"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_image error = %v", err)
	}
	if port != "found" {
		t.Fatalf("find_image port = %s", port)
	}
	match := runner.Values[flow.OutputRef{NodeID: 4, Port: "match"}].(vision.Match)
	if match.X != 2 || match.Y != 1 {
		t.Fatalf("match = %#v", match)
	}
}

func TestVisionFindAllWithMask(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 6, 4))
	fillImage(source, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	source.SetRGBA(2, 1, color.RGBA{R: 220, A: 255})
	source.SetRGBA(3, 1, color.RGBA{B: 220, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 1))
	template.SetRGBA(0, 0, color.RGBA{R: 220, A: 255})
	template.SetRGBA(1, 0, color.RGBA{G: 220, A: 255})
	mask := image.NewRGBA(image.Rect(0, 0, 2, 1))
	mask.SetRGBA(0, 0, color.RGBA{R: 255, G: 255, B: 255, A: 255})
	mask.SetRGBA(1, 0, color.RGBA{A: 255})
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "const/image", Properties: map[string]any{"name": "source.png"}},
			{ID: 2, Type: "const/image", Properties: map[string]any{"name": "template.png"}},
			{ID: 3, Type: "mask/create", Properties: map[string]any{"mask": "mask.png"}},
			{ID: 4, Type: "vision/find_all", Properties: map[string]any{"threshold": 0.99}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "picture", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "template"},
			{FromID: 3, FromPort: "mask", ToID: 4, ToPort: "mask"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.ImageResolver = func(name string) (any, bool, error) {
		switch name {
		case "source.png":
			return source, true, nil
		case "template.png":
			return template, true, nil
		case "mask.png":
			return mask, true, nil
		default:
			return nil, false, nil
		}
	}
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_all"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_all error = %v", err)
	}
	if port != "out" || runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}] != 1 {
		t.Fatalf("find_all port/count = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 4, Port: "count"}])
	}
	matches := runner.Values[flow.OutputRef{NodeID: 4, Port: "matches"}].([]vision.Match)
	if len(matches) != 1 || matches[0].X != 2 || matches[0].Y != 1 {
		t.Fatalf("matches = %#v", matches)
	}
}

func TestWaitAppearAndVanishWithImages(t *testing.T) {
	source := image.NewRGBA(image.Rect(0, 0, 5, 5))
	fillImage(source, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	fillImageRect(source, image.Rect(2, 2, 4, 4), color.RGBA{R: 200, A: 255})
	empty := image.NewRGBA(image.Rect(0, 0, 5, 5))
	fillImage(empty, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillImage(template, color.RGBA{R: 200, A: 255})
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "picture/source"},
			{ID: 3, Type: "wait/appear", Properties: map[string]any{"timeout": 0}},
			{ID: 4, Type: "wait/vanish", Properties: map[string]any{"timeout": 0}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 3, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 3, ToPort: "template"},
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "template"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = source
	runner.Values[flow.OutputRef{NodeID: 2, Port: "picture"}] = template
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["wait/appear"].Run(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("wait appear error = %v", err)
	}
	if port != "out" {
		t.Fatalf("wait appear port = %s", port)
	}
	if _, ok := runner.Values[flow.OutputRef{NodeID: 3, Port: "match"}].(vision.Match); !ok {
		t.Fatalf("wait appear match missing: %#v", runner.Values)
	}
	port, err = registry.handlers["wait/vanish"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("wait vanish error = %v", err)
	}
	if port != "timeout" {
		t.Fatalf("wait vanish present port = %s", port)
	}
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = empty
	port, err = registry.handlers["wait/appear"].Run(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("wait appear missing error = %v", err)
	}
	if port != "timeout" {
		t.Fatalf("wait appear missing port = %s", port)
	}
	port, err = registry.handlers["wait/vanish"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("wait vanish missing error = %v", err)
	}
	if port != "out" {
		t.Fatalf("wait vanish missing port = %s", port)
	}
}

func TestOCREngineAndFindTextWithoutBlocks(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "const/text", Properties: map[string]any{"value": "Login"}},
			{ID: 3, Type: "ocr/tesseract", Properties: map[string]any{"lang": "eng", "min_confidence": 50}},
			{ID: 4, Type: "vision/find_text"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "text", ToID: 4, ToPort: "text"},
			{FromID: 3, FromPort: "ocr", ToID: 4, ToPort: "ocr"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = map[string]any{"kind": "placeholder"}
	rc := &flow.RunContext{Runner: runner}
	ocrOut, err := registry.handlers["ocr/tesseract"].Eval(context.Background(), rc, &graph.Nodes[2])
	if err != nil {
		t.Fatalf("ocr eval error = %v", err)
	}
	ocrRef := ocrOut["ocr"].(map[string]any)
	if ocrRef["kind"] != "tesseract" {
		t.Fatalf("ocr ref = %#v", ocrRef)
	}
	port, err := registry.handlers["vision/find_text"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_text error = %v", err)
	}
	if port != "notFound" || runner.Values[flow.OutputRef{NodeID: 4, Port: "ok"}] != false {
		t.Fatalf("find_text port/ok = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 4, Port: "ok"}])
	}
}

func TestFindTextMatchesOCRBlocks(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "const/text", Properties: map[string]any{"value": "Login"}},
			{ID: 3, Type: "ocr/tesseract", Properties: map[string]any{"min_confidence": 50}},
			{ID: 4, Type: "vision/find_text"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "text", ToID: 4, ToPort: "text"},
			{FromID: 3, FromPort: "ocr", ToID: 4, ToPort: "ocr"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = map[string]any{
		"blocks": []any{
			map[string]any{"text": "Cancel", "confidence": 0.99, "x": 1, "y": 2, "w": 30, "h": 10},
			map[string]any{"text": "Login now", "confidence": 0.91, "x": 10, "y": 20, "w": 80, "h": 24},
		},
	}
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_text"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_text error = %v", err)
	}
	if port != "found" || runner.Values[flow.OutputRef{NodeID: 4, Port: "ok"}] != true {
		t.Fatalf("find_text port/ok = %s/%#v", port, runner.Values[flow.OutputRef{NodeID: 4, Port: "ok"}])
	}
	match := runner.Values[flow.OutputRef{NodeID: 4, Port: "match"}].(map[string]any)
	if match["text"] != "Login now" || match["x"] != 10 || match["score"] != 0.91 {
		t.Fatalf("match = %#v", match)
	}
}

func TestFindTextRegexAndMinConfidence(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "video/source"},
			{ID: 2, Type: "text/source"},
			{ID: 3, Type: "ocr/source"},
			{ID: 4, Type: "vision/find_text", Properties: map[string]any{"regex": true}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "video", ToID: 4, ToPort: "video"},
			{FromID: 2, FromPort: "text", ToID: 4, ToPort: "text"},
			{FromID: 3, FromPort: "ocr", ToID: 4, ToPort: "ocr"},
		},
	}
	registry := NewRegistry()
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "video"}] = map[string]any{
		"blocks": []any{
			map[string]any{"text": "Build 42", "confidence": 0.2, "x": 1, "y": 2},
			map[string]any{"text": "Build 84", "confidence": 0.8, "x": 3, "y": 4},
		},
	}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "text"}] = `Build \d+`
	runner.Values[flow.OutputRef{NodeID: 3, Port: "ocr"}] = map[string]any{"config": map[string]any{"min_confidence": 50}}
	rc := &flow.RunContext{Runner: runner}
	port, err := registry.handlers["vision/find_text"].Run(context.Background(), rc, &graph.Nodes[3])
	if err != nil {
		t.Fatalf("find_text error = %v", err)
	}
	match := runner.Values[flow.OutputRef{NodeID: 4, Port: "match"}].(map[string]any)
	if port != "found" || match["text"] != "Build 84" {
		t.Fatalf("find_text port/match = %s/%#v", port, match)
	}
}

func TestActionPlaceholders(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "point/source"},
			{ID: 2, Type: "device/source"},
			{ID: 3, Type: "action/click", Properties: map[string]any{"button": "right"}},
			{ID: 4, Type: "action/type"},
			{ID: 5, Type: "const/text", Properties: map[string]any{"value": "hello"}},
			{ID: 6, Type: "action/scroll", Properties: map[string]any{"dy": -3}},
			{ID: 7, Type: "action/drag"},
			{ID: 8, Type: "action/hotkey", Properties: map[string]any{"keys": "ctrl+c"}},
			{ID: 9, Type: "util/alert", Properties: map[string]any{"message": "held"}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "point", ToID: 3, ToPort: "target"},
			{FromID: 2, FromPort: "mouse", ToID: 3, ToPort: "mouse"},
			{FromID: 5, FromPort: "text", ToID: 4, ToPort: "text"},
			{FromID: 2, FromPort: "keyboard", ToID: 4, ToPort: "keyboard"},
			{FromID: 1, FromPort: "point", ToID: 6, ToPort: "target"},
			{FromID: 2, FromPort: "mouse", ToID: 6, ToPort: "mouse"},
			{FromID: 1, FromPort: "point", ToID: 7, ToPort: "src"},
			{FromID: 1, FromPort: "point", ToID: 7, ToPort: "dst"},
			{FromID: 2, FromPort: "mouse", ToID: 7, ToPort: "mouse"},
			{FromID: 2, FromPort: "keyboard", ToID: 8, ToPort: "keyboard"},
			{FromID: 8, FromPort: "hold", ToID: 9, ToPort: "in"},
		},
	}
	registry := NewRegistry()
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, registry, sink)
	runner.Values[flow.OutputRef{NodeID: 1, Port: "point"}] = vision.Point{X: 11, Y: 22}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "mouse"}] = map[string]any{"kind": "placeholder"}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "keyboard"}] = map[string]any{"kind": "placeholder"}
	rc := &flow.RunContext{Runner: runner}
	for _, id := range []int{3, 4, 6, 7, 8} {
		if _, err := registry.handlers[graph.Nodes[id-1].Type].Run(context.Background(), rc, &graph.Nodes[id-1]); err != nil {
			t.Fatalf("run node %d error = %v", id, err)
		}
	}
	if len(sink.Events) == 0 {
		t.Fatalf("expected planned action events")
	}
	foundHold := false
	for _, event := range sink.Events {
		if event.Type == "alert" && event.Message == "held" {
			foundHold = true
		}
	}
	if !foundHold {
		t.Fatalf("hotkey hold branch did not run: %#v", sink.Events)
	}
}

func TestActionNodesUseRealDevice(t *testing.T) {
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "point/source"},
			{ID: 2, Type: "device/source"},
			{ID: 3, Type: "action/click", Properties: map[string]any{"button": "right", "double": true}},
			{ID: 4, Type: "action/type"},
			{ID: 5, Type: "const/text", Properties: map[string]any{"value": "hello"}},
			{ID: 6, Type: "action/scroll", Properties: map[string]any{"dy": -3}},
			{ID: 7, Type: "action/drag"},
			{ID: 8, Type: "action/hotkey", Properties: map[string]any{"keys": "ctrl+c"}},
			{ID: 9, Type: "util/alert", Properties: map[string]any{"message": "held"}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "point", ToID: 3, ToPort: "target"},
			{FromID: 2, FromPort: "mouse", ToID: 3, ToPort: "mouse"},
			{FromID: 5, FromPort: "text", ToID: 4, ToPort: "text"},
			{FromID: 2, FromPort: "keyboard", ToID: 4, ToPort: "keyboard"},
			{FromID: 1, FromPort: "point", ToID: 6, ToPort: "target"},
			{FromID: 2, FromPort: "mouse", ToID: 6, ToPort: "mouse"},
			{FromID: 1, FromPort: "point", ToID: 7, ToPort: "src"},
			{FromID: 1, FromPort: "point", ToID: 7, ToPort: "dst"},
			{FromID: 2, FromPort: "mouse", ToID: 7, ToPort: "mouse"},
			{FromID: 2, FromPort: "keyboard", ToID: 8, ToPort: "keyboard"},
			{FromID: 8, FromPort: "hold", ToID: 9, ToPort: "in"},
		},
	}
	registry := NewRegistry()
	dev := &fakeDevice{}
	runner := flow.NewRunner(graph, registry, &flow.CollectingSink{})
	runner.Values[flow.OutputRef{NodeID: 1, Port: "point"}] = vision.Point{X: 11, Y: 22}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "mouse"}] = device.Ref{Resource: "device", Device: dev}
	runner.Values[flow.OutputRef{NodeID: 2, Port: "keyboard"}] = device.Ref{Resource: "device", Device: dev}
	rc := &flow.RunContext{Runner: runner}
	for _, id := range []int{3, 4, 6, 7, 8} {
		if _, err := registry.handlers[graph.Nodes[id-1].Type].Run(context.Background(), rc, &graph.Nodes[id-1]); err != nil {
			t.Fatalf("run node %d error = %v", id, err)
		}
	}
	log := strings.Join(dev.calls, "|")
	for _, want := range []string{
		"move 11 22",
		"down right 11 22",
		"up right 11 22",
		"type hello",
		"wheel -3",
		"down left 11 22",
		"keyDown ctrl",
		"keyDown c",
		"keyUp c",
		"keyUp ctrl",
	} {
		if !strings.Contains(log, want) {
			t.Fatalf("device calls missing %q: %s", want, log)
		}
	}
}

func fillImage(img *image.RGBA, c color.RGBA) {
	fillImageRect(img, img.Bounds(), c)
}

func fillImageRect(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			img.SetRGBA(x, y, c)
		}
	}
}

type fakeDevice struct {
	calls []string
}

func (d *fakeDevice) Capture(_ context.Context, dst **image.RGBA) error {
	d.calls = append(d.calls, "capture")
	img := device.EnsureRGBA(dst, image.Rect(0, 0, 1, 1))
	img.SetRGBA(0, 0, color.RGBA{A: 255})
	return nil
}

func (d *fakeDevice) MouseMove(_ context.Context, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("move %d %d", x, y))
	return nil
}

func (d *fakeDevice) MouseDown(_ context.Context, button device.Button, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("down %s %d %d", button, x, y))
	return nil
}

func (d *fakeDevice) MouseUp(_ context.Context, button device.Button, x int, y int) error {
	d.calls = append(d.calls, fmt.Sprintf("up %s %d %d", button, x, y))
	return nil
}

func (d *fakeDevice) MouseWheel(_ context.Context, delta int) error {
	d.calls = append(d.calls, fmt.Sprintf("wheel %d", delta))
	return nil
}

func (d *fakeDevice) KeyDown(_ context.Context, key device.Key) error {
	d.calls = append(d.calls, fmt.Sprintf("keyDown %s", key))
	return nil
}

func (d *fakeDevice) KeyUp(_ context.Context, key device.Key) error {
	d.calls = append(d.calls, fmt.Sprintf("keyUp %s", key))
	return nil
}

func (d *fakeDevice) TypeText(_ context.Context, text string) error {
	d.calls = append(d.calls, "type "+text)
	return nil
}

func (d *fakeDevice) Close() error {
	d.calls = append(d.calls, "close")
	return nil
}
