package aibuilder

import (
	"context"
	"testing"
)

type fakeToolStepClient struct {
	steps []ToolStep
	calls int
}

func (c *fakeToolStepClient) GenerateToolStep(context.Context, []ChatMessage) (ToolStep, error) {
	if c.calls >= len(c.steps) {
		return ToolStep{Content: "done"}, nil
	}
	step := c.steps[c.calls]
	c.calls++
	return step, nil
}

func TestRunToolLoopCompletesOnFinishBuild(t *testing.T) {
	client := &fakeToolStepClient{steps: []ToolStep{
		{Content: "creating", ToolCalls: []ToolCall{{ID: "call_1", Name: "create_node", Arguments: map[string]any{"type": "script/js"}}}},
		{ToolCalls: []ToolCall{{ID: "call_2", Name: "finish_build", Arguments: map[string]any{"summary": "ready"}}}},
	}}
	var sent []ToolCallEvent
	result, err := RunToolLoop(context.Background(), client, []ChatMessage{{Role: "user", Content: "build"}}, 4, ToolLoopCallbacks{
		SendToolCall: func(_ context.Context, event ToolCallEvent) error {
			sent = append(sent, event)
			return nil
		},
		WaitToolResult: func(_ context.Context, id string) (ToolResult, error) {
			return ToolResult{
				ToolCallID: id,
				Status:     "ok",
				Permission: map[string]any{
					"decision": "approved",
				},
				Result: map[string]any{"ok": true},
				Log:    map[string]any{"status": "ok"},
			}, nil
		},
	})
	if err != nil {
		t.Fatalf("RunToolLoop() error = %v", err)
	}
	if result.Status != "completed" || result.Summary != "ready" || result.ToolCalls != 2 {
		t.Fatalf("result = %#v", result)
	}
	if len(sent) != 2 || sent[0].Risk != "write" || sent[1].Tool != "finish_build" {
		t.Fatalf("sent = %#v", sent)
	}
	if len(result.Messages) < 5 || result.Messages[len(result.Messages)-1].Role != "tool" {
		t.Fatalf("messages = %#v", result.Messages)
	}
	if len(result.Trace) != 2 || result.Trace[0]["tool"] != "create_node" || result.Trace[0]["permission"] == nil {
		t.Fatalf("trace = %#v", result.Trace)
	}
}

func TestRunToolLoopRejectsUnknownTool(t *testing.T) {
	client := &fakeToolStepClient{steps: []ToolStep{
		{ToolCalls: []ToolCall{{ID: "call_1", Name: "bad_tool"}}},
	}}
	_, err := RunToolLoop(context.Background(), client, nil, 4, ToolLoopCallbacks{
		SendToolCall: func(context.Context, ToolCallEvent) error { return nil },
		WaitToolResult: func(context.Context, string) (ToolResult, error) {
			return ToolResult{Status: "ok"}, nil
		},
	})
	if err == nil {
		t.Fatalf("RunToolLoop() expected error")
	}
}

func TestRunToolLoopStopsAtMaxToolCalls(t *testing.T) {
	client := &fakeToolStepClient{steps: []ToolStep{
		{ToolCalls: []ToolCall{{ID: "call_1", Name: "create_node"}}},
		{ToolCalls: []ToolCall{{ID: "call_2", Name: "create_node"}}},
	}}
	result, err := RunToolLoop(context.Background(), client, nil, 1, ToolLoopCallbacks{
		SendToolCall: func(context.Context, ToolCallEvent) error { return nil },
		WaitToolResult: func(_ context.Context, id string) (ToolResult, error) {
			return ToolResult{ToolCallID: id, Status: "ok", Result: map[string]any{"ok": true}}, nil
		},
	})
	if err == nil || result.Status != "stopped" || result.ToolCalls != 1 {
		t.Fatalf("result = %#v err=%v", result, err)
	}
}

func TestRunToolLoopRecordsRejectedTools(t *testing.T) {
	client := &fakeToolStepClient{steps: []ToolStep{
		{ToolCalls: []ToolCall{{ID: "call_1", Name: "create_node", Arguments: map[string]any{"type": "script/js"}}}},
		{Content: "done"},
	}}
	result, err := RunToolLoop(context.Background(), client, nil, 4, ToolLoopCallbacks{
		SendToolCall: func(context.Context, ToolCallEvent) error { return nil },
		WaitToolResult: func(_ context.Context, id string) (ToolResult, error) {
			return ToolResult{ToolCallID: id, Status: "rejected", Permission: map[string]any{"decision": "rejected"}, Result: map[string]any{"ok": false}}, nil
		},
	})
	if err != nil {
		t.Fatalf("RunToolLoop() error = %v", err)
	}
	if len(result.Rejections) != 1 || result.Rejections[0]["tool"] != "create_node" {
		t.Fatalf("rejections = %#v", result.Rejections)
	}
	if result.Rejections[0]["permission"] == nil || len(result.Trace) != 1 {
		t.Fatalf("rejections=%#v trace=%#v", result.Rejections, result.Trace)
	}
}
