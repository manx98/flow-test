package catalog

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
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
		l.injectPaddleModels(node)
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
	default:
		node["supported"] = true
		node["legacy"] = false
	}
}

func (l *Loader) injectPaddleModels(node map[string]any) {
	if stringOf(node["type"]) != "ocr/paddle" {
		return
	}
	modelsDir := l.modelsDir()
	setEnumOptions(node, "det_model", modelPrefixes(modelsDir, "_det", ""))
	setEnumOptions(node, "rec_model", modelPrefixes(modelsDir, "_rec", ""))
	setEnumOptions(node, "textline_model", modelPrefixes(modelsDir, "", "textline"))
}

func (l *Loader) modelsDir() string {
	for dir := filepath.Clean(l.root); ; dir = filepath.Dir(dir) {
		path := filepath.Join(dir, "libs", "models")
		if info, err := os.Stat(path); err == nil && info.IsDir() {
			return path
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return ""
		}
	}
}

func modelPrefixes(dir, suffix, contains string) []string {
	if dir == "" {
		return nil
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil
	}
	seen := map[string]map[string]bool{}
	for _, entry := range entries {
		name := entry.Name()
		ext := filepath.Ext(name)
		if ext != ".param" && ext != ".bin" {
			continue
		}
		prefix := strings.TrimSuffix(name, ext)
		if suffix != "" && !strings.HasSuffix(prefix, suffix) {
			continue
		}
		if contains != "" && !strings.Contains(prefix, contains) {
			continue
		}
		if seen[prefix] == nil {
			seen[prefix] = map[string]bool{}
		}
		seen[prefix][ext] = true
	}
	out := make([]string, 0, len(seen))
	for prefix, exts := range seen {
		if exts[".param"] && exts[".bin"] {
			out = append(out, prefix)
		}
	}
	sort.Strings(out)
	return out
}

func setEnumOptions(node map[string]any, name string, options []string) {
	if len(options) == 0 {
		return
	}
	props, _ := node["properties"].([]any)
	for _, prop := range props {
		m, ok := prop.(map[string]any)
		if ok && stringOf(m["name"]) == name {
			m["options"] = options
			if !containsString(options, stringOf(m["default"])) {
				m["default"] = options[0]
			}
			return
		}
	}
}

func containsString(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
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
