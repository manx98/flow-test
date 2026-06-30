package aibuilder

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"flow-test-go/internal/catalog"

	"github.com/dop251/goja/parser"
)

var allowedDynamicPortTypes = map[string]bool{
	"match": true, "point": true, "text": true, "number": true, "bool": true,
	"picture": true, "mask": true, "ocr": true, "device": true, "script": true,
}

var catalogCache struct {
	once  sync.Once
	ports map[string]struct {
		inputs  map[string]bool
		outputs map[string]bool
	}
}

type draftNode struct {
	ID         any            `json:"id"`
	Type       string         `json:"type"`
	Properties map[string]any `json:"properties"`
	Inputs     []draftPort    `json:"inputs"`
	Outputs    []draftPort    `json:"outputs"`
}

type draftPort struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type draftLink struct {
	From string `json:"from"`
	Out  string `json:"out"`
	To   string `json:"to"`
	In   string `json:"in"`
}

type draftShape struct {
	Nodes []draftNode `json:"nodes"`
	Links []draftLink `json:"links"`
}

func CompileDraft(draft map[string]any) (map[string]any, error) {
	data, err := json.Marshal(draft)
	if err != nil {
		return nil, err
	}
	var parsed draftShape
	if err := json.Unmarshal(data, &parsed); err != nil {
		return nil, err
	}
	nodes := map[string]draftNode{}
	for _, node := range parsed.Nodes {
		id := draftNodeID(node.ID)
		if id == "" {
			return nil, fmt.Errorf("draft node missing id")
		}
		if node.Type == "" {
			return nil, fmt.Errorf("draft node %s missing type", id)
		}
		if _, exists := nodes[id]; exists {
			return nil, fmt.Errorf("duplicate draft node id %s", id)
		}
		if err := validateDraftNode(id, node); err != nil {
			return nil, err
		}
		nodes[id] = node
	}
	for _, link := range parsed.Links {
		from, ok := nodes[link.From]
		if !ok {
			return nil, fmt.Errorf("link references missing source node %s", link.From)
		}
		to, ok := nodes[link.To]
		if !ok {
			return nil, fmt.Errorf("link references missing target node %s", link.To)
		}
		if !hasOutputPort(from, link.Out) {
			return nil, fmt.Errorf("link references missing output port %s.%s", link.From, link.Out)
		}
		if !hasInputPort(to, link.In) {
			return nil, fmt.Errorf("link references missing input port %s.%s", link.To, link.In)
		}
	}
	return draft, nil
}

func validateDraftNode(id string, node draftNode) error {
	if node.Type == "script/js" {
		if code, ok := node.Properties["code"].(string); ok {
			if _, err := parser.ParseFile(nil, id+".js", code, 0); err != nil {
				return fmt.Errorf("script/js %s syntax error: %w", id, err)
			}
		}
	}
	if err := validatePortList(id, node.Type, "input", node.Inputs); err != nil {
		return err
	}
	if err := validatePortList(id, node.Type, "output", node.Outputs); err != nil {
		return err
	}
	return nil
}

func validatePortList(nodeID, nodeType, dir string, ports []draftPort) error {
	seen := map[string]bool{}
	for _, port := range ports {
		name := strings.TrimSpace(port.Name)
		typ := strings.TrimSpace(port.Type)
		if name == "" || typ == "" {
			return fmt.Errorf("%s %s has invalid %s port", nodeType, nodeID, dir)
		}
		if seen[name] {
			return fmt.Errorf("%s %s has duplicate %s port %s", nodeType, nodeID, dir, name)
		}
		seen[name] = true
		if isDynamicScriptPort(nodeType, dir, name) && !allowedDynamicPortTypes[typ] {
			return fmt.Errorf("%s %s dynamic %s port %s has unsupported type %s", nodeType, nodeID, dir, name, typ)
		}
		if nodeType != "script/js_exec" && isUnknownDynamicPort(nodeType, dir, name) {
			return fmt.Errorf("%s %s cannot declare dynamic %s port %s", nodeType, nodeID, dir, name)
		}
	}
	return nil
}

func hasInputPort(node draftNode, name string) bool {
	return portSet(node, true)[name]
}

func hasOutputPort(node draftNode, name string) bool {
	return portSet(node, false)[name]
}

func portSet(node draftNode, input bool) map[string]bool {
	out := defaultPorts(node.Type, input)
	var ports []draftPort
	if input {
		ports = node.Inputs
	} else {
		ports = node.Outputs
	}
	for _, port := range ports {
		if port.Name != "" {
			out[port.Name] = true
		}
	}
	return out
}

func defaultPorts(nodeType string, input bool) map[string]bool {
	ports := map[string]bool{}
	switch nodeType {
	case "flow/start":
		if !input {
			ports["out"] = true
		}
	case "script/js":
		if !input {
			ports["script"] = true
		}
	case "script/js_exec":
		if input {
			ports["in"] = true
			ports["script"] = true
		} else {
			ports["out"] = true
		}
	case "assert/check":
		if input {
			ports["in"] = true
			ports["cond"] = true
		} else {
			ports["pass"] = true
			ports["fail"] = true
		}
	case "test/result":
		if input {
			ports["in"] = true
		}
	}
	for name := range catalogDefaultPorts(nodeType, input) {
		ports[name] = true
	}
	return ports
}

func catalogDefaultPorts(nodeType string, input bool) map[string]bool {
	catalogCache.once.Do(func() {
		catalogCache.ports = loadCatalogPorts()
	})
	spec := catalogCache.ports[nodeType]
	if input {
		return spec.inputs
	}
	return spec.outputs
}

func loadCatalogPorts() map[string]struct {
	inputs  map[string]bool
	outputs map[string]bool
} {
	root := findGraphSkillsRoot()
	if root == "" {
		return nil
	}
	loaded, err := catalog.NewLoader(root).Load()
	if err != nil {
		return nil
	}
	nodes, _ := loaded["nodes"].([]map[string]any)
	if nodes == nil {
		if raw, ok := loaded["nodes"].([]any); ok {
			nodes = make([]map[string]any, 0, len(raw))
			for _, item := range raw {
				if node, ok := item.(map[string]any); ok {
					nodes = append(nodes, node)
				}
			}
		}
	}
	out := map[string]struct {
		inputs  map[string]bool
		outputs map[string]bool
	}{}
	for _, node := range nodes {
		nodeType, _ := node["type"].(string)
		if nodeType == "" {
			continue
		}
		out[nodeType] = struct {
			inputs  map[string]bool
			outputs map[string]bool
		}{
			inputs:  portNames(node["inputs"]),
			outputs: portNames(node["outputs"]),
		}
	}
	return out
}

func portNames(value any) map[string]bool {
	out := map[string]bool{}
	for _, item := range anySlice(value) {
		port, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name, _ := port["name"].(string)
		if name != "" {
			out[name] = true
		}
	}
	return out
}

func anySlice(value any) []any {
	if items, ok := value.([]any); ok {
		return items
	}
	if maps, ok := value.([]map[string]any); ok {
		out := make([]any, 0, len(maps))
		for _, item := range maps {
			out = append(out, item)
		}
		return out
	}
	return nil
}

func findGraphSkillsRoot() string {
	candidates := []string{
		filepath.Join("server", "flow", "graph_skills"),
		filepath.Join("..", "server", "flow", "graph_skills"),
		filepath.Join("..", "..", "server", "flow", "graph_skills"),
		filepath.Join("..", "..", "..", "server", "flow", "graph_skills"),
	}
	if repo := os.Getenv("FLOW_REPO_ROOT"); repo != "" {
		candidates = append([]string{filepath.Join(repo, "server", "flow", "graph_skills")}, candidates...)
	}
	for _, candidate := range candidates {
		if st, err := os.Stat(candidate); err == nil && st.IsDir() {
			return candidate
		}
	}
	return ""
}

func isDynamicScriptPort(nodeType, dir, name string) bool {
	if nodeType != "script/js_exec" {
		return false
	}
	return !isFixedScriptPort(dir, name)
}

func isFixedScriptPort(dir, name string) bool {
	if dir == "input" {
		return name == "in" || name == "script"
	}
	return name == "out"
}

func isUnknownDynamicPort(nodeType, dir, name string) bool {
	return !defaultPorts(nodeType, dir == "input")[name]
}

func draftNodeID(value any) string {
	switch v := value.(type) {
	case string:
		return strings.TrimSpace(v)
	case float64:
		return fmt.Sprintf("%.0f", v)
	case int:
		return fmt.Sprintf("%d", v)
	case int64:
		return fmt.Sprintf("%d", v)
	default:
		return strings.TrimSpace(fmt.Sprint(v))
	}
}
