package flow

import (
	"context"
	"encoding/json"
	"testing"
)

type testRegistry map[string]Handler

func (r testRegistry) Handler(nodeType string) (Handler, bool) {
	h, ok := r[nodeType]
	return h, ok
}

type testHandler struct {
	out string
}

func (h testHandler) Eval(context.Context, *RunContext, *Node) (map[string]any, error) {
	return map[string]any{}, nil
}

func (h testHandler) Run(context.Context, *RunContext, *Node) (string, error) {
	if h.out == "" {
		return "out", nil
	}
	return h.out, nil
}

func TestRunnerExecutesLinearGraph(t *testing.T) {
	graph := Graph{
		Nodes: []Node{{ID: 1, Type: "flow/start"}, {ID: 2, Type: "util/log"}},
		Links: []Link{{FromID: 1, FromPort: "out", ToID: 2, ToPort: "in"}},
	}
	sink := &CollectingSink{}
	runner := NewRunner(graph, testRegistry{
		"flow/start": testHandler{},
		"util/log":   testHandler{},
	}, sink)
	if err := runner.Run(context.Background()); err != nil {
		t.Fatalf("Run() error = %v", err)
	}
	if got := sink.Events[len(sink.Events)-1]; got.Type != "run" || got.Status != "done" {
		t.Fatalf("last event = %#v, want run done", got)
	}
}

func TestGraphUnmarshalLiteGraphLinks(t *testing.T) {
	raw := []byte(`{
	  "nodes": [
	    {"id": 1, "type": "flow/start", "outputs": [{"name": "out", "type": "exec"}]},
	    {"id": 2, "type": "util/log", "inputs": [{"name": "in", "type": "exec", "link": 10}]}
	  ],
	  "links": [[10, 1, 0, 2, 0, "exec"]]
	}`)
	var graph Graph
	if err := json.Unmarshal(raw, &graph); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if len(graph.Links) != 1 {
		t.Fatalf("len(Links) = %d, want 1", len(graph.Links))
	}
	link := graph.Links[0]
	if link.FromPort != "out" || link.ToPort != "in" {
		t.Fatalf("link ports = %s -> %s, want out -> in", link.FromPort, link.ToPort)
	}
}
