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
