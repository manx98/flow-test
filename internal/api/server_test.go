package api

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"image"
	"image/color"
	"image/png"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"flow-test-go/internal/flow"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

func TestProjectRunCreatesReport(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	graph := map[string]any{
		"nodes": []any{
			map[string]any{
				"id":      1,
				"type":    "flow/start",
				"outputs": []any{map[string]any{"name": "out", "type": "exec"}},
			},
			map[string]any{
				"id":         2,
				"type":       "const/bool",
				"properties": map[string]any{"value": true},
				"outputs":    []any{map[string]any{"name": "bool", "type": "bool"}},
			},
			map[string]any{
				"id":     3,
				"type":   "assert/check",
				"inputs": []any{map[string]any{"name": "in", "type": "exec"}, map[string]any{"name": "cond", "type": "bool"}},
				"outputs": []any{
					map[string]any{"name": "pass", "type": "exec"},
					map[string]any{"name": "fail", "type": "exec"},
				},
			},
			map[string]any{
				"id":     4,
				"type":   "test/result",
				"inputs": []any{map[string]any{"name": "in", "type": "exec"}},
			},
		},
		"links": []any{
			[]any{1, 1, 0, 3, 0, "exec"},
			[]any{2, 2, 0, 3, 1, "bool"},
			[]any{3, 3, 0, 4, 0, "exec"},
		},
	}
	body := doJSON(t, server, http.MethodPost, "/api/projects/demo/run", map[string]any{"graph": graph}, http.StatusOK)
	if body["ok"] != true {
		t.Fatalf("run ok = %#v, response = %#v", body["ok"], body)
	}
	run, ok := body["run"].(string)
	if !ok || run == "" {
		t.Fatalf("missing run in response: %#v", body)
	}
	if body["report_url"] != "/api/projects/demo/results/"+run+"/report.json" ||
		body["junit_url"] != "/api/projects/demo/results/"+run+"/report.junit.xml" {
		t.Fatalf("result urls = %#v / %#v", body["report_url"], body["junit_url"])
	}
	report := doRequest(t, server, http.MethodGet, "/api/projects/demo/results/"+run+"/report.json", nil, "", http.StatusOK)
	var parsed map[string]any
	if err := json.Unmarshal(report.Body.Bytes(), &parsed); err != nil {
		t.Fatalf("report JSON error = %v", err)
	}
	if parsed["passed"] != true {
		t.Fatalf("report passed = %#v, report = %#v", parsed["passed"], parsed)
	}
	junit := doRequest(t, server, http.MethodGet, "/api/projects/demo/results/"+run+"/report.junit.xml", nil, "", http.StatusOK)
	if !strings.Contains(junit.Body.String(), "<testsuite") {
		t.Fatalf("junit body = %s", junit.Body.String())
	}
}

func TestImageUploadRenameAndList(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	upload := doMultipart(t, server, "/api/projects/demo/images", "file", "pic.png", []byte("png"), http.StatusOK)
	if upload["name"] != "pic.png" {
		t.Fatalf("upload name = %#v", upload["name"])
	}
	rename := doJSON(t, server, http.MethodPost, "/api/projects/demo/images/pic.png/rename", map[string]any{"name": "renamed.png"}, http.StatusOK)
	if rename["name"] != "renamed.png" {
		t.Fatalf("rename name = %#v", rename["name"])
	}
	list := doRequest(t, server, http.MethodGet, "/api/projects/demo/images", nil, "", http.StatusOK)
	var body map[string][]string
	if err := json.Unmarshal(list.Body.Bytes(), &body); err != nil {
		t.Fatalf("list JSON error = %v", err)
	}
	if len(body["images"]) != 1 || body["images"][0] != "renamed.png" {
		t.Fatalf("images = %#v", body["images"])
	}
}

func TestAISessionCRUD(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	created := doJSON(t, server, http.MethodPost, "/api/projects/demo/ai/sessions", map[string]any{
		"session": map[string]any{"title": "Plan"},
	}, http.StatusOK)
	session := created["session"].(map[string]any)
	id := session["id"].(string)
	if session["title"] != "Plan" {
		t.Fatalf("title = %#v", session["title"])
	}
	updated := doJSON(t, server, http.MethodPut, "/api/projects/demo/ai/sessions/"+id, map[string]any{
		"session": map[string]any{"title": "Updated", "messages": []any{map[string]any{"role": "user"}}},
	}, http.StatusOK)
	if updated["session"].(map[string]any)["title"] != "Updated" {
		t.Fatalf("updated = %#v", updated)
	}
	loaded := doRequest(t, server, http.MethodGet, "/api/projects/demo/ai/sessions/"+id, nil, "", http.StatusOK)
	var loadBody map[string]map[string]any
	if err := json.Unmarshal(loaded.Body.Bytes(), &loadBody); err != nil {
		t.Fatalf("load JSON error = %v", err)
	}
	if loadBody["session"]["title"] != "Updated" {
		t.Fatalf("loaded = %#v", loadBody)
	}
	list := doRequest(t, server, http.MethodGet, "/api/projects/demo/ai/sessions", nil, "", http.StatusOK)
	var listBody map[string][]map[string]any
	if err := json.Unmarshal(list.Body.Bytes(), &listBody); err != nil {
		t.Fatalf("list JSON error = %v", err)
	}
	if len(listBody["sessions"]) != 1 || listBody["sessions"][0]["id"] != id {
		t.Fatalf("sessions = %#v", listBody["sessions"])
	}
	doRequest(t, server, http.MethodDelete, "/api/projects/demo/ai/sessions/"+id, nil, "", http.StatusOK)
	doRequest(t, server, http.MethodDelete, "/api/projects/demo/ai/sessions", nil, "", http.StatusOK)
}

func TestAIDraftFallback(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPut, "/api/settings", map[string]any{
		"settings": map[string]any{
			"ai_builder": map[string]any{
				"provider": "ollama",
				"base_url": "http://127.0.0.1:11434",
				"model":    "qwen2.5",
			},
		},
	}, http.StatusOK)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	draftBody := doJSON(t, server, http.MethodPost, "/api/projects/demo/ai/draft", map[string]any{
		"message": "check login",
	}, http.StatusOK)
	draft := draftBody["draft"].(map[string]any)
	if draft["title"] == "" || len(draft["nodes"].([]any)) == 0 || len(draft["links"].([]any)) == 0 {
		t.Fatalf("draft = %#v", draft)
	}
	modelMeta := draft["metadata"].(map[string]any)["model"].(map[string]any)
	if modelMeta["provider"] != "ollama" || modelMeta["model_ready"] != true {
		t.Fatalf("draft metadata = %#v", draft["metadata"])
	}
	created := doJSON(t, server, http.MethodPost, "/api/projects/demo/ai/sessions", map[string]any{
		"session": map[string]any{"title": "AI"},
	}, http.StatusOK)
	sessionID := created["session"].(map[string]any)["id"].(string)
	streamBody, err := json.Marshal(map[string]any{"message": "stream login"})
	if err != nil {
		t.Fatal(err)
	}
	stream := doRequest(t, server, http.MethodPost, "/api/projects/demo/ai/sessions/"+sessionID+"/draft/stream", bytes.NewReader(streamBody), "application/json", http.StatusOK)
	if !strings.Contains(stream.Body.String(), "event: draft") {
		t.Fatalf("stream body = %s", stream.Body.String())
	}
	if !strings.Contains(stream.Body.String(), "event: done") {
		t.Fatalf("stream did not complete = %s", stream.Body.String())
	}
	if !strings.Contains(stream.Body.String(), `"metadata"`) {
		t.Fatalf("stream did not include metadata = %s", stream.Body.String())
	}
	loaded := doRequest(t, server, http.MethodGet, "/api/projects/demo/ai/sessions/"+sessionID, nil, "", http.StatusOK)
	var loadBody map[string]map[string]any
	if err := json.Unmarshal(loaded.Body.Bytes(), &loadBody); err != nil {
		t.Fatalf("load JSON error = %v", err)
	}
	if loadBody["session"]["draft"] == nil {
		t.Fatalf("session draft was not saved: %#v", loadBody["session"])
	}
	buildState := loadBody["session"]["build_state"].(map[string]any)
	if buildState["last_init_summary"] == "" {
		t.Fatalf("session build_state summary was not saved: %#v", loadBody["session"])
	}
}

func TestCodeCheckAndComplete(t *testing.T) {
	server := newTestServer(t)
	ok := doJSON(t, server, http.MethodPost, "/api/check", map[string]any{
		"code": "const value = getArg('value');\nsetResult('ok', value > 0);",
	}, http.StatusOK)
	if len(ok["errors"].([]any)) != 0 {
		t.Fatalf("valid script errors = %#v", ok["errors"])
	}
	bad := doJSON(t, server, http.MethodPost, "/api/check", map[string]any{
		"code": "const value = ;",
	}, http.StatusOK)
	errors := bad["errors"].([]any)
	if len(errors) == 0 {
		t.Fatalf("bad script errors = %#v", bad["errors"])
	}
	first := errors[0].(map[string]any)
	if first["line"] == nil || first["col"] == nil || first["message"] == "" {
		t.Fatalf("bad script error shape = %#v", first)
	}
	complete := doJSON(t, server, http.MethodPost, "/api/complete", map[string]any{
		"code":   "pc.fi",
		"line":   1,
		"column": 5,
	}, http.StatusOK)
	items := complete["completions"].([]any)
	if !completionNamesContain(items, "findAll") || !completionNamesContain(items, "findImage") {
		t.Fatalf("pc completions = %#v", items)
	}
}

func TestUnsupportedDeviceSessionAndStreamOffer(t *testing.T) {
	server := newTestServer(t)
	connect := doJSON(t, server, http.MethodPost, "/api/devices/connect", map[string]any{
		"kind": "unknown",
		"config": map[string]any{
			"host":   "127.0.0.1",
			"width":  1440,
			"height": 900,
		},
		"project": "demo",
		"node_id": 1,
	}, http.StatusOK)
	if connect["kind"] != "unknown" || connect["session_id"] == "" || connect["unsupported"] != true {
		t.Fatalf("connect response = %#v", connect)
	}
	if connect["width"] != float64(1440) || connect["height"] != float64(900) {
		t.Fatalf("connect size = %#v x %#v", connect["width"], connect["height"])
	}
	if connect["stream_mode"] != nil || connect["capture_url"] != nil || connect["input_url"] != nil {
		t.Fatalf("unsupported connect should not advertise capture stream: %#v", connect)
	}
	offer := doJSON(t, server, http.MethodPost, "/api/webrtc/offer", map[string]any{
		"session_id": connect["session_id"],
		"sdp":        "v=0",
		"type":       "offer",
	}, http.StatusNotImplemented)
	if offer["session_id"] != connect["session_id"] {
		t.Fatalf("offer response = %#v", offer)
	}
	disconnect := doJSON(t, server, http.MethodPost, "/api/devices/"+connect["session_id"].(string)+"/disconnect", nil, http.StatusOK)
	if disconnect["deleted"] != true {
		t.Fatalf("disconnect response = %#v", disconnect)
	}
	doRequest(t, server, http.MethodPost, "/api/webrtc/offer", strings.NewReader(`{"session_id":"missing","sdp":"v=0","type":"offer"}`), "application/json", http.StatusNotFound)
}

func TestRDPConnectFailureReturnsBadRequest(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/devices/connect", map[string]any{
		"kind":   "rdp",
		"config": map[string]any{"host": "127.0.0.1", "port": 1, "connect_timeout": 1},
	}, http.StatusBadRequest)
}

func TestConnectStaticImageDevice(t *testing.T) {
	server := newTestServer(t)
	img := image.NewRGBA(image.Rect(0, 0, 2, 2))
	img.Set(1, 1, color.RGBA{R: 180, A: 255})
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatal(err)
	}
	connect := doJSON(t, server, http.MethodPost, "/api/devices/connect", map[string]any{
		"kind": "static_image",
		"config": map[string]any{
			"image_base64": base64.StdEncoding.EncodeToString(buf.Bytes()),
			"width":        2,
			"height":       2,
		},
		"project": "demo",
		"node_id": 2,
	}, http.StatusOK)
	if connect["kind"] != "static_image" || connect["unsupported"] != false {
		t.Fatalf("connect response = %#v", connect)
	}
	if connect["stream_mode"] != "webrtc" || connect["capture_url"] == "" || connect["input_url"] == "" || connect["webrtc_url"] == "" {
		t.Fatalf("connect stream response = %#v", connect)
	}
	ref, ok := server.devices.RefByProjectNode("demo", 2)
	if !ok || ref.Unsupported || ref.Device == nil {
		t.Fatalf("ref = %#v ok=%v", ref, ok)
	}
	capture := doRequest(t, server, http.MethodGet, "/api/devices/"+connect["session_id"].(string)+"/capture", nil, "", http.StatusOK)
	if capture.Header().Get("Content-Type") != "image/png" {
		t.Fatalf("capture content type = %q", capture.Header().Get("Content-Type"))
	}
	decoded, _, err := image.Decode(bytes.NewReader(capture.Body.Bytes()))
	if err != nil {
		t.Fatalf("capture decode error = %v", err)
	}
	if decoded.Bounds().Dx() != 2 || decoded.Bounds().Dy() != 2 {
		t.Fatalf("capture bounds = %v", decoded.Bounds())
	}
	offer := doJSON(t, server, http.MethodPost, "/api/webrtc/offer", map[string]any{
		"session_id": connect["session_id"],
		"sdp":        "v=0",
		"type":       "offer",
	}, http.StatusBadRequest)
	if offer["session_id"] != connect["session_id"] || offer["detail"] == "" {
		t.Fatalf("offer response = %#v", offer)
	}
	input := doJSON(t, server, http.MethodPost, "/api/devices/"+connect["session_id"].(string)+"/input", map[string]any{
		"t": "move",
		"x": 1,
		"y": 1,
	}, http.StatusOK)
	if input["ok"] != true {
		t.Fatalf("input response = %#v", input)
	}
}

func TestCaptureUnsupportedDevice(t *testing.T) {
	server := newTestServer(t)
	connect := doJSON(t, server, http.MethodPost, "/api/devices/connect", map[string]any{
		"kind":   "unknown",
		"config": map[string]any{"host": "127.0.0.1"},
	}, http.StatusOK)
	doRequest(t, server, http.MethodGet, "/api/devices/"+connect["session_id"].(string)+"/capture", nil, "", http.StatusNotImplemented)
}

func TestRunGraphUsesConnectedDeviceSession(t *testing.T) {
	server := newTestServer(t)
	project, err := server.projects.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := project.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	if _, err := server.devices.Create("unknown", map[string]any{"host": "live", "width": 1600, "height": 900}, "demo", 10); err != nil {
		t.Fatalf("Create device session error = %v", err)
	}
	graph, err := decodeGraph(map[string]any{
		"nodes": []any{
			map[string]any{"id": 1, "type": "flow/start", "outputs": []any{map[string]any{"name": "out", "type": "exec"}}},
			map[string]any{"id": 10, "type": "device/rdp", "properties": map[string]any{"host": "static", "width": 1024, "height": 768}, "outputs": []any{map[string]any{"name": "device", "type": "device"}}},
			map[string]any{
				"id":      11,
				"type":    "device/attrs",
				"inputs":  []any{map[string]any{"name": "device", "type": "device"}},
				"outputs": []any{map[string]any{"name": "width", "type": "number"}},
			},
			map[string]any{
				"id":     12,
				"type":   "data/text_display",
				"inputs": []any{map[string]any{"name": "in", "type": "exec"}, map[string]any{"name": "text", "type": "text"}},
			},
		},
		"links": []any{
			[]any{1, 1, 0, 12, 0, "exec"},
			[]any{2, 10, 0, 11, 0, "device"},
			[]any{3, 11, 0, 12, 1, "number"},
		},
	})
	if err != nil {
		t.Fatalf("decodeGraph() error = %v", err)
	}
	result := server.runGraphForProject(context.Background(), "demo", project, "", graph)
	if result.Err != nil {
		t.Fatalf("runGraphForProject() error = %v", result.Err)
	}
	for _, event := range result.Events {
		if event.Type == "node_text" && event.ID == 12 && event.Text == "1600" {
			return
		}
	}
	t.Fatalf("missing live width node_text, events = %#v", result.Events)
}

func TestRunGraphLoadsProjectImagesForVision(t *testing.T) {
	server := newTestServer(t)
	project, err := server.projects.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := project.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	source := image.NewRGBA(image.Rect(0, 0, 8, 8))
	fillTestImage(source, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	fillTestImageRect(source, image.Rect(4, 3, 6, 5), color.RGBA{R: 240, G: 20, B: 30, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillTestImage(template, color.RGBA{R: 240, G: 20, B: 30, A: 255})
	savePNGImage(t, project, "source.png", source)
	savePNGImage(t, project, "template.png", template)
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "const/image", Properties: map[string]any{"name": "source.png"}},
			{ID: 3, Type: "const/image", Properties: map[string]any{"name": "template.png"}},
			{ID: 4, Type: "vision/find_image", Properties: map[string]any{"threshold": 0.99}},
			{ID: 5, Type: "assert/check", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "cond", Type: "bool"}}},
			{ID: 6, Type: "test/result"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 4, ToPort: "in"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "video"},
			{FromID: 3, FromPort: "picture", ToID: 4, ToPort: "template"},
			{FromID: 4, FromPort: "found", ToID: 5, ToPort: "in"},
			{FromID: 4, FromPort: "ok", ToID: 5, ToPort: "cond"},
			{FromID: 5, FromPort: "pass", ToID: 6, ToPort: "in"},
		},
	}
	runName, err := project.CreateRun()
	if err != nil {
		t.Fatalf("CreateRun() error = %v", err)
	}
	result := server.runGraphForProject(context.Background(), "demo", project, runName, graph)
	if result.Err != nil {
		t.Fatalf("runGraphForProject() error = %v", result.Err)
	}
	if !result.Report.Passed || result.Report.Total != 1 || result.Report.Failed != 0 {
		t.Fatalf("report = %#v", result.Report)
	}
	for _, event := range result.Events {
		if event.Type == "node_shot" && event.ID == 4 {
			doRequest(t, server, http.MethodGet, event.URL, nil, "", http.StatusOK)
			return
		}
	}
	t.Fatalf("missing node_shot event: %#v", result.Events)
}

func TestRunGraphUsesNodeShotAsFailedAssertEvidence(t *testing.T) {
	server := newTestServer(t)
	project, err := server.projects.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := project.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	source := image.NewRGBA(image.Rect(0, 0, 6, 6))
	fillTestImage(source, color.RGBA{R: 1, G: 1, B: 1, A: 255})
	fillTestImageRect(source, image.Rect(2, 2, 4, 4), color.RGBA{R: 200, A: 255})
	template := image.NewRGBA(image.Rect(0, 0, 2, 2))
	fillTestImage(template, color.RGBA{R: 200, A: 255})
	savePNGImage(t, project, "source.png", source)
	savePNGImage(t, project, "template.png", template)
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "const/image", Properties: map[string]any{"name": "source.png"}},
			{ID: 3, Type: "const/image", Properties: map[string]any{"name": "template.png"}},
			{ID: 4, Type: "vision/find_image", Properties: map[string]any{"threshold": 0.99}},
			{ID: 5, Type: "const/bool", Properties: map[string]any{"value": false}},
			{ID: 6, Type: "assert/check", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "cond", Type: "bool"}}},
			{ID: 7, Type: "test/result"},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 4, ToPort: "in"},
			{FromID: 2, FromPort: "picture", ToID: 4, ToPort: "video"},
			{FromID: 3, FromPort: "picture", ToID: 4, ToPort: "template"},
			{FromID: 4, FromPort: "found", ToID: 6, ToPort: "in"},
			{FromID: 5, FromPort: "bool", ToID: 6, ToPort: "cond"},
			{FromID: 6, FromPort: "fail", ToID: 7, ToPort: "in"},
		},
	}
	runName, err := project.CreateRun()
	if err != nil {
		t.Fatalf("CreateRun() error = %v", err)
	}
	result := server.runGraphForProject(context.Background(), "demo", project, runName, graph)
	if result.Err != nil {
		t.Fatalf("runGraphForProject() error = %v", result.Err)
	}
	var shotURL string
	for _, event := range result.Events {
		if event.Type == "node_shot" && event.ID == 4 {
			shotURL = event.URL
			break
		}
	}
	if shotURL == "" {
		t.Fatalf("missing node_shot event: %#v", result.Events)
	}
	if len(result.Report.Assert) != 1 || result.Report.Assert[0].Evidence != shotURL {
		t.Fatalf("assert evidence = %#v, shot = %s", result.Report.Assert, shotURL)
	}
}

func TestRunGraphMissingProjectImageFallsBackToRef(t *testing.T) {
	server := newTestServer(t)
	project, err := server.projects.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := project.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	graph := flow.Graph{
		Nodes: []flow.Node{
			{ID: 1, Type: "flow/start"},
			{ID: 2, Type: "const/image", Properties: map[string]any{"name": "missing.png"}},
			{ID: 3, Type: "data/text_display", Inputs: []flow.Port{{Name: "in", Type: "exec"}, {Name: "text", Type: "text"}}},
		},
		Links: []flow.Link{
			{FromID: 1, FromPort: "out", ToID: 3, ToPort: "in"},
			{FromID: 2, FromPort: "picture", ToID: 3, ToPort: "text"},
		},
	}
	result := server.runGraphForProject(context.Background(), "demo", project, "", graph)
	if result.Err != nil {
		t.Fatalf("runGraphForProject() error = %v", result.Err)
	}
	for _, event := range result.Events {
		if event.Type == "node_text" && event.ID == 3 && strings.Contains(event.Text, "missing.png") {
			return
		}
	}
	t.Fatalf("missing fallback node_text, events = %#v", result.Events)
}

func TestRunWebSocket(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/run/demo"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	graph := map[string]any{
		"nodes": []any{
			map[string]any{"id": 1, "type": "flow/start", "outputs": []any{map[string]any{"name": "out", "type": "exec"}}},
			map[string]any{"id": 2, "type": "test/result", "inputs": []any{map[string]any{"name": "in", "type": "exec"}}},
		},
		"links": []any{[]any{1, 1, 0, 2, 0, "exec"}},
	}
	if err := conn.WriteJSON(map[string]any{"cmd": "run", "graph": graph}); err != nil {
		t.Fatalf("WriteJSON() error = %v", err)
	}
	sawRunning := false
	for i := 0; i < 10; i++ {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("ReadJSON() error = %v", err)
		}
		if msg["type"] == "node" && msg["status"] == "running" {
			sawRunning = true
		}
		if msg["type"] == "run" && msg["status"] == "done" {
			if !sawRunning {
				t.Fatalf("missing live node running before done")
			}
			if msg["report"] == nil {
				t.Fatalf("missing report in done message: %#v", msg)
			}
			if msg["report_url"] == "" || msg["junit_url"] == "" {
				t.Fatalf("missing result urls in done message: %#v", msg)
			}
			return
		}
	}
	t.Fatalf("did not receive run done")
}

func TestRunWebSocketStop(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/run/demo"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	graph := map[string]any{
		"nodes": []any{
			map[string]any{"id": 1, "type": "flow/start", "outputs": []any{map[string]any{"name": "out", "type": "exec"}}},
			map[string]any{
				"id":         2,
				"type":       "wait/delay",
				"properties": map[string]any{"seconds": 5},
				"inputs":     []any{map[string]any{"name": "in", "type": "exec"}},
			},
		},
		"links": []any{[]any{1, 1, 0, 2, 0, "exec"}},
	}
	if err := conn.WriteJSON(map[string]any{"cmd": "run", "graph": graph}); err != nil {
		t.Fatalf("WriteJSON(run) error = %v", err)
	}
	var first map[string]any
	if err := conn.ReadJSON(&first); err != nil {
		t.Fatalf("ReadJSON(start) error = %v", err)
	}
	if first["type"] != "run" || first["status"] != "start" {
		t.Fatalf("first message = %#v", first)
	}
	if err := conn.WriteJSON(map[string]any{"cmd": "stop"}); err != nil {
		t.Fatalf("WriteJSON(stop) error = %v", err)
	}
	for i := 0; i < 10; i++ {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("ReadJSON() error = %v", err)
		}
		if msg["type"] == "run" && msg["status"] == "error" {
			return
		}
	}
	t.Fatalf("did not receive run error after stop")
}

func TestAIBuildWebSocketFallbackDraft(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/ai-build/demo/session-1"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	if err := conn.WriteJSON(map[string]any{"type": "init", "message": "build"}); err != nil {
		t.Fatalf("WriteJSON(init) error = %v", err)
	}
	var sawDraft bool
	for i := 0; i < 5; i++ {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("ReadJSON() error = %v", err)
		}
		if msg["type"] == "status" && !toolMetadataContains(msg["tools"], "set_node_ports") {
			t.Fatalf("status tools = %#v", msg["tools"])
		}
		if msg["type"] == "status" && msg["tool_calling_supported"] != true {
			t.Fatalf("status tool_calling_supported = %#v", msg)
		}
		if msg["type"] == "draft" {
			sawDraft = true
			draft := msg["draft"].(map[string]any)
			if draft["title"] == "" || len(draft["nodes"].([]any)) == 0 {
				t.Fatalf("draft message = %#v", msg)
			}
		}
		if msg["type"] == "done" {
			if msg["status"] != "completed" {
				t.Fatalf("done message = %#v", msg)
			}
			if !sawDraft {
				t.Fatalf("done before draft")
			}
			return
		}
	}
	t.Fatalf("did not receive completed done")
}

func TestAIBuildWebSocketToolLoop(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	session := doJSON(t, server, http.MethodPost, "/api/projects/demo/ai/sessions", map[string]any{
		"session": map[string]any{"title": "AI"},
	}, http.StatusOK)
	sessionID := session["session"].(map[string]any)["id"].(string)
	var modelCalls int
	modelServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		modelCalls++
		if r.URL.Path != "/chat/completions" {
			t.Fatalf("model path = %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte(`data: {"choices":[{"delta":{"content":"building "}}]}

data: {"choices":[{"delta":{"content":"flow"}}]}

data: {"choices":[{"delta":{"tool_calls":[{"id":"call_finish","type":"function","function":{"name":"finish_build","arguments":"{\"summary\":\"ready\"}"}}]}}]}

data: [DONE]

`))
	}))
	defer modelServer.Close()
	doJSON(t, server, http.MethodPut, "/api/settings", map[string]any{
		"settings": map[string]any{
			"ai_builder": map[string]any{
				"provider":       "custom",
				"base_url":       modelServer.URL,
				"model":          "test-model",
				"max_tool_calls": 4,
			},
		},
	}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/ai-build/demo/" + sessionID
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	if err := conn.WriteJSON(map[string]any{"type": "init", "message": "build"}); err != nil {
		t.Fatalf("WriteJSON(init) error = %v", err)
	}
	var sawToolCall bool
	var streamText string
	for i := 0; i < 10; i++ {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("ReadJSON() error = %v", err)
		}
		switch msg["type"] {
		case "delta":
			streamText += msg["text"].(string)
		case "tool_call":
			sawToolCall = true
			if msg["tool"] != "finish_build" || msg["risk"] != "read" {
				t.Fatalf("tool call = %#v", msg)
			}
			if err := conn.WriteJSON(map[string]any{
				"type":         "tool_result",
				"tool_call_id": msg["id"],
				"tool":         msg["tool"],
				"status":       "ok",
				"result":       map[string]any{"ok": true},
			}); err != nil {
				t.Fatalf("WriteJSON(tool_result) error = %v", err)
			}
		case "done":
			if !sawToolCall || streamText != "building flow" || msg["status"] != "completed" || msg["summary"] != "ready" {
				t.Fatalf("done = %#v sawToolCall=%v streamText=%q", msg, sawToolCall, streamText)
			}
			if modelCalls != 1 {
				t.Fatalf("modelCalls = %d", modelCalls)
			}
			return
		}
	}
	t.Fatalf("did not receive completed done")
}

func TestAIBuildWebSocketToolLoopStop(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	session := doJSON(t, server, http.MethodPost, "/api/projects/demo/ai/sessions", map[string]any{
		"session": map[string]any{"title": "AI"},
	}, http.StatusOK)
	sessionID := session["session"].(map[string]any)["id"].(string)
	modelServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte(`data: {"choices":[{"delta":{"tool_calls":[{"id":"call_create","type":"function","function":{"name":"create_node","arguments":"{\"type\":\"script/js\"}"}}]}}]}

data: [DONE]

`))
	}))
	defer modelServer.Close()
	doJSON(t, server, http.MethodPut, "/api/settings", map[string]any{
		"settings": map[string]any{
			"ai_builder": map[string]any{
				"provider":       "custom",
				"base_url":       modelServer.URL,
				"model":          "test-model",
				"max_tool_calls": 4,
			},
		},
	}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/ai-build/demo/" + sessionID
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	if err := conn.WriteJSON(map[string]any{"type": "init", "message": "build"}); err != nil {
		t.Fatalf("WriteJSON(init) error = %v", err)
	}
	for i := 0; i < 6; i++ {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			t.Fatalf("ReadJSON() error = %v", err)
		}
		switch msg["type"] {
		case "tool_call":
			if err := conn.WriteJSON(map[string]any{"type": "stop", "reason": "user_stop"}); err != nil {
				t.Fatalf("WriteJSON(stop) error = %v", err)
			}
		case "done":
			if msg["status"] != "stopped" || msg["reason"] != "user_stop" {
				t.Fatalf("done = %#v", msg)
			}
			return
		}
	}
	t.Fatalf("did not receive stopped done")
}

func toolMetadataContains(value any, name string) bool {
	items, _ := value.([]any)
	for _, item := range items {
		m, _ := item.(map[string]any)
		if m["name"] == name {
			return true
		}
	}
	return false
}

func TestAIBuildWebSocketStop(t *testing.T) {
	server := newTestServer(t)
	doJSON(t, server, http.MethodPost, "/api/projects", map[string]any{"name": "demo"}, http.StatusOK)
	httpServer := httptest.NewServer(server.router)
	defer httpServer.Close()
	wsURL := "ws" + strings.TrimPrefix(httpServer.URL, "http") + "/ws/ai-build/demo/session-1"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	defer conn.Close()
	if err := conn.WriteJSON(map[string]any{"type": "stop"}); err != nil {
		t.Fatalf("WriteJSON(stop) error = %v", err)
	}
	var msg map[string]any
	if err := conn.ReadJSON(&msg); err != nil {
		t.Fatalf("ReadJSON() error = %v", err)
	}
	if msg["type"] != "done" || msg["status"] != "stopped" {
		t.Fatalf("stop message = %#v", msg)
	}
}

func TestStaticSPAFallback(t *testing.T) {
	server := newTestServerWithRepoRoot(t, testRepoWithFrontend(t, "frontend index"))

	root := doRequest(t, server, http.MethodGet, "/", nil, "", http.StatusOK)
	if strings.TrimSpace(root.Body.String()) != "frontend index" {
		t.Fatalf("root body = %q", root.Body.String())
	}
	spa := doRequest(t, server, http.MethodGet, "/projects/demo", nil, "", http.StatusOK)
	if strings.TrimSpace(spa.Body.String()) != "frontend index" {
		t.Fatalf("spa body = %q", spa.Body.String())
	}
	doRequest(t, server, http.MethodGet, "/api/missing", nil, "", http.StatusNotFound)
	doRequest(t, server, http.MethodGet, "/ws/missing", nil, "", http.StatusNotFound)
	doRequest(t, server, http.MethodPost, "/projects/demo", nil, "", http.StatusNotFound)
}

func TestStaticSPAFallbackMissingBuild(t *testing.T) {
	server := newTestServer(t)
	body := doRequest(t, server, http.MethodGet, "/projects/demo", nil, "", http.StatusNotFound)
	if !strings.Contains(body.Body.String(), "frontend build not found") {
		t.Fatalf("missing build response = %s", body.Body.String())
	}
}

func newTestServer(t *testing.T) *Server {
	t.Helper()
	return newTestServerWithRepoRoot(t, t.TempDir())
}

func newTestServerWithRepoRoot(t *testing.T, repoRoot string) *Server {
	t.Helper()
	gin.SetMode(gin.TestMode)
	t.Setenv("FLOW_WORKSPACE", t.TempDir())
	t.Setenv("FLOW_SETTINGS_PATH", filepath.Join(t.TempDir(), "settings.json"))
	server, err := NewServer(Config{RepoRoot: repoRoot})
	if err != nil {
		t.Fatalf("NewServer() error = %v", err)
	}
	return server
}

func testRepoWithFrontend(t *testing.T, index string) string {
	t.Helper()
	repo := t.TempDir()
	dist := filepath.Join(repo, "web", "dist")
	if err := os.MkdirAll(filepath.Join(dist, "assets"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dist, "index.html"), []byte(index), 0o644); err != nil {
		t.Fatal(err)
	}
	return repo
}

func savePNGImage(t *testing.T, p interface {
	SaveImage(string, io.Reader) (string, error)
}, name string, img image.Image) {
	t.Helper()
	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		t.Fatalf("png encode error = %v", err)
	}
	if _, err := p.SaveImage(name, &buf); err != nil {
		t.Fatalf("SaveImage(%s) error = %v", name, err)
	}
}

func fillTestImage(img *image.RGBA, c color.RGBA) {
	fillTestImageRect(img, img.Bounds(), c)
}

func fillTestImageRect(img *image.RGBA, rect image.Rectangle, c color.RGBA) {
	for y := rect.Min.Y; y < rect.Max.Y; y++ {
		for x := rect.Min.X; x < rect.Max.X; x++ {
			img.SetRGBA(x, y, c)
		}
	}
}

func doJSON(t *testing.T, server *Server, method, path string, value any, want int) map[string]any {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	rec := doRequest(t, server, method, path, bytes.NewReader(data), "application/json", want)
	var out map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("response JSON error = %v, body = %s", err, rec.Body.String())
	}
	return out
}

func doMultipart(t *testing.T, server *Server, path, field, filename string, data []byte, want int) map[string]any {
	t.Helper()
	var buf bytes.Buffer
	writer := multipart.NewWriter(&buf)
	part, err := writer.CreateFormFile(field, filename)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(data); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	rec := doRequest(t, server, http.MethodPost, path, &buf, writer.FormDataContentType(), want)
	var out map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &out); err != nil {
		t.Fatalf("response JSON error = %v, body = %s", err, rec.Body.String())
	}
	return out
}

func doRequest(t *testing.T, server *Server, method, path string, body io.Reader, contentType string, want int) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, body)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	rec := httptest.NewRecorder()
	server.router.ServeHTTP(rec, req)
	if rec.Code != want {
		t.Fatalf("%s %s status = %d, want %d, body = %s", method, path, rec.Code, want, rec.Body.String())
	}
	return rec
}

func completionNamesContain(items []any, want string) bool {
	for _, item := range items {
		m, ok := item.(map[string]any)
		if ok && m["name"] == want {
			return true
		}
	}
	return false
}
