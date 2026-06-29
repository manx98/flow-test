package flow

import (
	"context"
	"fmt"
	"image"
)

type Handler interface {
	Eval(context.Context, *RunContext, *Node) (map[string]any, error)
	Run(context.Context, *RunContext, *Node) (string, error)
}

type Registry interface {
	Handler(nodeType string) (Handler, bool)
}

type Runner struct {
	Graph          Graph
	Registry       Registry
	Sink           EventSink
	Values         map[OutputRef]any
	Vars           map[string]any
	DeviceResolver func(*Node) (any, bool)
	ImageResolver  func(string) (any, bool, error)
	ShotSink       func(nodeID int64, img image.Image, rects []image.Rectangle) (string, error)
	LastShotURL    string
}

type RunContext struct {
	Runner *Runner
}

func NewRunner(graph Graph, registry Registry, sink EventSink) *Runner {
	if sink == nil {
		sink = &CollectingSink{}
	}
	return &Runner{
		Graph:    graph,
		Registry: registry,
		Sink:     sink,
		Values:   map[OutputRef]any{},
		Vars:     map[string]any{},
	}
}

func (r *Runner) Run(ctx context.Context) error {
	current, err := r.Graph.StartNode()
	if err != nil {
		r.Sink.Emit(Event{Type: "run", Status: "error", Info: err.Error()})
		return err
	}
	rc := &RunContext{Runner: r}
	if err := rc.runChainFrom(ctx, current, true); err != nil {
		r.Sink.Emit(Event{Type: "run", Status: "error", Info: err.Error()})
		return err
	}
	r.Sink.Emit(Event{Type: "run", Status: "done", Report: map[string]any{}})
	return nil
}

func (rc *RunContext) runChainFrom(ctx context.Context, current *Node, emitRunDone bool) error {
	for current != nil {
		if err := ctx.Err(); err != nil {
			return err
		}
		handler, ok := rc.Runner.Registry.Handler(current.Type)
		if !ok {
			err := fmt.Errorf("node type %q is not implemented in Go runtime", current.Type)
			rc.Runner.Sink.Emit(Event{Type: "node", ID: current.ID, Status: "fail", Info: err.Error()})
			return err
		}
		rc.Runner.Sink.Emit(Event{Type: "node", ID: current.ID, Status: "running"})
		nextPort, err := handler.Run(ctx, rc, current)
		if err != nil {
			rc.Runner.Sink.Emit(Event{Type: "node", ID: current.ID, Status: "fail", Info: err.Error()})
			return WrapNodeError(current, err)
		}
		if !selfReportingNode(current.Type) {
			rc.Runner.Sink.Emit(Event{Type: "node", ID: current.ID, Status: "ok"})
		}
		if nextPort == "" {
			break
		}
		next, ok := rc.Runner.Graph.NextExec(current.ID, nextPort)
		if !ok {
			break
		}
		current = next
	}
	return nil
}

func (rc *RunContext) RunBranch(ctx context.Context, node *Node, port string) error {
	next, ok := rc.Runner.Graph.NextExec(node.ID, port)
	if !ok {
		return nil
	}
	return rc.runChainFrom(ctx, next, false)
}

func (rc *RunContext) EvalInput(ctx context.Context, node *Node, port string) (any, bool, error) {
	link, ok := rc.Runner.Graph.InputLink(node.ID, port)
	if !ok {
		return nil, false, nil
	}
	ref := OutputRef{NodeID: link.FromID, Port: link.FromPort}
	if value, ok := rc.Runner.Values[ref]; ok {
		return value, true, nil
	}
	source, ok := rc.Runner.Graph.NodeByID(link.FromID)
	if !ok {
		return nil, false, fmt.Errorf("input %s source node %d not found", port, link.FromID)
	}
	handler, ok := rc.Runner.Registry.Handler(source.Type)
	if !ok {
		return nil, false, fmt.Errorf("node type %q is not implemented in Go runtime", source.Type)
	}
	values, err := handler.Eval(ctx, rc, source)
	if err != nil {
		return nil, false, WrapNodeError(source, err)
	}
	for name, value := range values {
		rc.Runner.Values[OutputRef{NodeID: source.ID, Port: name}] = value
	}
	value, ok := rc.Runner.Values[ref]
	return value, ok, nil
}

func (rc *RunContext) SetOutput(node *Node, port string, value any) {
	rc.Runner.Values[OutputRef{NodeID: node.ID, Port: port}] = value
}

func selfReportingNode(nodeType string) bool {
	switch nodeType {
	case "assert/check", "util/log", "util/alert", "data/text_display", "flow/try_catch", "io/interaction":
		return true
	default:
		return false
	}
}
