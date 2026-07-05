package catalog

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoaderAnnotatesAndFiltersNodes(t *testing.T) {
	root := t.TempDir()
	writeNode(t, root, "device/local", `{"type":"device/local","title":"Local","order":2}`)
	writeNode(t, root, "script/js", `{"type":"script/js","title":"JS","order":1}`)
	writeNode(t, root, "const/text", `{"type":"const/text","title":"Text","order":3}`)

	data, err := NewLoader(root).Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	nodes := data["nodes"].([]map[string]any)
	if len(nodes) != 2 {
		t.Fatalf("len(nodes) = %d, want 2", len(nodes))
	}
	if nodes[0]["type"] != "script/js" {
		t.Fatalf("nodes[0].type = %v, want script/js", nodes[0]["type"])
	}
	if nodes[0]["legacy"] != false || nodes[0]["supported"] != true {
		t.Fatalf("script annotations = %#v", nodes[0])
	}
	if nodes[1]["supported"] != true || nodes[1]["legacy"] != false {
		t.Fatalf("supported annotations = %#v", nodes[1])
	}
	if _, ok := nodes[1]["order"]; ok {
		t.Fatalf("order should be removed from catalog response")
	}
}

func TestLoaderInjectsPaddleModelOptions(t *testing.T) {
	root := t.TempDir()
	graphRoot := filepath.Join(root, "server", "flow", "graph_skills")
	writeNode(t, graphRoot, "ocr/ocr_paddle", `{
		"type":"ocr/paddle",
		"title":"Paddle",
		"properties":[
			{"name":"det_model","type":"enum","default":"missing","options":[]},
			{"name":"rec_model","type":"enum","default":"PP_OCRv6_small_rec","options":[]},
			{"name":"textline_model","type":"enum","default":"PP_LCNet_x0_25_textline_ori","options":[]}
		]
	}`)
	for _, name := range []string{
		"PP_OCRv6_small_det.param", "PP_OCRv6_small_det.bin",
		"PP_OCRv6_small_rec.param", "PP_OCRv6_small_rec.bin",
		"PP_LCNet_x0_25_textline_ori.param", "PP_LCNet_x0_25_textline_ori.bin",
		"PP_OCRv6_broken_det.param",
	} {
		path := filepath.Join(root, "libs", "models", name)
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte("x"), 0o644); err != nil {
			t.Fatal(err)
		}
	}

	data, err := NewLoader(graphRoot).Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	node := data["nodes"].([]map[string]any)[0]
	if node["supported"] != true {
		t.Fatalf("paddle support = %#v", node)
	}
	if got := enumOptions(t, node, "det_model"); len(got) != 1 || got[0] != "PP_OCRv6_small_det" {
		t.Fatalf("det options = %#v", got)
	}
	if got := enumDefault(t, node, "det_model"); got != "PP_OCRv6_small_det" {
		t.Fatalf("det default = %q", got)
	}
	if got := enumOptions(t, node, "textline_model"); len(got) != 1 || got[0] != "PP_LCNet_x0_25_textline_ori" {
		t.Fatalf("textline options = %#v", got)
	}
}

func enumOptions(t *testing.T, node map[string]any, name string) []string {
	t.Helper()
	prop := enumProp(t, node, name)
	raw := prop["options"].([]string)
	return raw
}

func enumDefault(t *testing.T, node map[string]any, name string) string {
	t.Helper()
	return enumProp(t, node, name)["default"].(string)
}

func enumProp(t *testing.T, node map[string]any, name string) map[string]any {
	t.Helper()
	for _, prop := range node["properties"].([]any) {
		m := prop.(map[string]any)
		if m["name"] == name {
			return m
		}
	}
	t.Fatalf("property %s not found", name)
	return nil
}

func writeNode(t *testing.T, root, typ, body string) {
	t.Helper()
	path := filepath.Join(root, typ, "node.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}
