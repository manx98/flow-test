package catalog

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
)

type Loader struct {
	root string
}

func NewLoader(root string) *Loader {
	return &Loader{root: root}
}

func (l *Loader) Load() (map[string]any, error) {
	nodes := make([]map[string]any, 0)
	err := filepath.WalkDir(l.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || filepath.Base(path) != "node.json" {
			return nil
		}
		node, err := loadNode(path)
		if err != nil {
			return err
		}
		annotateSupport(node)
		if node["type"] == "device/local" {
			return nil
		}
		nodes = append(nodes, node)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.SliceStable(nodes, func(i, j int) bool {
		oi := orderOf(nodes[i])
		oj := orderOf(nodes[j])
		if oi != oj {
			return oi < oj
		}
		return stringOf(nodes[i]["type"]) < stringOf(nodes[j]["type"])
	})
	for _, node := range nodes {
		delete(node, "order")
	}
	return map[string]any{"types": TypeColors(), "nodes": nodes}, nil
}

func loadNode(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var node map[string]any
	if err := json.Unmarshal(data, &node); err != nil {
		return nil, err
	}
	if _, ok := node["inputs"]; !ok {
		node["inputs"] = []any{}
	}
	if _, ok := node["outputs"]; !ok {
		node["outputs"] = []any{}
	}
	if _, ok := node["properties"]; !ok {
		node["properties"] = []any{}
	}
	return node, nil
}

func annotateSupport(node map[string]any) {
	t := stringOf(node["type"])
	switch t {
	case "script/python", "script/exec":
		node["supported"] = false
		node["legacy"] = true
		node["reason"] = "Python script nodes are legacy in the Go runtime; migrate to script/js and script/js_exec."
	case "ocr/paddle":
		node["supported"] = false
		node["legacy"] = false
		node["reason"] = "PaddleOCR is not implemented in the Go runtime yet."
	default:
		node["supported"] = true
		node["legacy"] = false
	}
}

func orderOf(node map[string]any) int {
	switch v := node["order"].(type) {
	case float64:
		return int(v)
	case int:
		return v
	default:
		return 10000
	}
}

func stringOf(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
