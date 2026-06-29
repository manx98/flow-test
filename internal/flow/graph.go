package flow

import (
	"encoding/json"
	"fmt"
)

type Graph struct {
	Nodes []Node `json:"nodes"`
	Links []Link `json:"links"`
}

type Node struct {
	ID         int64          `json:"id"`
	Type       string         `json:"type"`
	Title      string         `json:"title,omitempty"`
	Properties map[string]any `json:"properties,omitempty"`
	Inputs     []Port         `json:"inputs,omitempty"`
	Outputs    []Port         `json:"outputs,omitempty"`
}

type Port struct {
	Name  string  `json:"name"`
	Type  string  `json:"type,omitempty"`
	Link  *int64  `json:"link,omitempty"`
	Links []int64 `json:"links,omitempty"`
}

type Link struct {
	ID       int64  `json:"id,omitempty"`
	FromID   int64  `json:"from_id"`
	FromPort string `json:"from_port"`
	ToID     int64  `json:"to_id"`
	ToPort   string `json:"to_port"`
}

type OutputRef struct {
	NodeID int64
	Port   string
}

func (g *Graph) UnmarshalJSON(data []byte) error {
	var raw struct {
		Nodes []Node            `json:"nodes"`
		Links []json.RawMessage `json:"links"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	g.Nodes = raw.Nodes
	g.Links = nil
	for _, item := range raw.Links {
		if len(item) == 0 || string(item) == "null" {
			continue
		}
		var obj Link
		if err := json.Unmarshal(item, &obj); err == nil && obj.FromID != 0 && obj.ToID != 0 {
			g.Links = append(g.Links, obj)
			continue
		}
		var arr []any
		if err := json.Unmarshal(item, &arr); err != nil {
			return err
		}
		if len(arr) < 5 {
			continue
		}
		fromID := int64Of(arr[1])
		toID := int64Of(arr[3])
		fromSlot := int(int64Of(arr[2]))
		toSlot := int(int64Of(arr[4]))
		link := Link{
			ID:       int64Of(arr[0]),
			FromID:   fromID,
			FromPort: g.outputName(fromID, fromSlot),
			ToID:     toID,
			ToPort:   g.inputName(toID, toSlot),
		}
		g.Links = append(g.Links, link)
	}
	return nil
}

func (g Graph) NodeByID(id int64) (*Node, bool) {
	for i := range g.Nodes {
		if g.Nodes[i].ID == id {
			return &g.Nodes[i], true
		}
	}
	return nil, false
}

func (g Graph) StartNode() (*Node, error) {
	for i := range g.Nodes {
		if g.Nodes[i].Type == "flow/start" {
			return &g.Nodes[i], nil
		}
	}
	if len(g.Nodes) == 0 {
		return nil, fmt.Errorf("flow graph is empty")
	}
	return &g.Nodes[0], nil
}

func (g Graph) NextExec(nodeID int64, port string) (*Node, bool) {
	if port == "" {
		port = "out"
	}
	for _, link := range g.Links {
		if link.FromID == nodeID && link.FromPort == port {
			return g.NodeByID(link.ToID)
		}
	}
	return nil, false
}

func (g Graph) InputLink(nodeID int64, port string) (Link, bool) {
	for _, link := range g.Links {
		if link.ToID == nodeID && link.ToPort == port {
			return link, true
		}
	}
	return Link{}, false
}

func (g Graph) outputName(nodeID int64, slot int) string {
	if node, ok := g.NodeByID(nodeID); ok && slot >= 0 && slot < len(node.Outputs) {
		if node.Outputs[slot].Name != "" {
			return node.Outputs[slot].Name
		}
	}
	if slot == 0 {
		return "out"
	}
	return fmt.Sprintf("out%d", slot)
}

func (g Graph) inputName(nodeID int64, slot int) string {
	if node, ok := g.NodeByID(nodeID); ok && slot >= 0 && slot < len(node.Inputs) {
		if node.Inputs[slot].Name != "" {
			return node.Inputs[slot].Name
		}
	}
	if slot == 0 {
		return "in"
	}
	return fmt.Sprintf("in%d", slot)
}

func int64Of(v any) int64 {
	switch n := v.(type) {
	case float64:
		return int64(n)
	case int64:
		return n
	case int:
		return int64(n)
	case json.Number:
		i, _ := n.Int64()
		return i
	default:
		return 0
	}
}
