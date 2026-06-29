package aibuilder

import (
	"context"
	"encoding/json"
	"fmt"
)

type ToolStepClient interface {
	GenerateToolStep(context.Context, []ChatMessage) (ToolStep, error)
}

type StreamingToolStepClient interface {
	ToolStepClient
	StreamToolStep(context.Context, []ChatMessage, func(string) error) (ToolStep, error)
}

type ToolCallEvent struct {
	ID   string         `json:"id"`
	Tool string         `json:"tool"`
	Risk string         `json:"risk"`
	Args map[string]any `json:"args"`
}

type ToolResult struct {
	ToolCallID string         `json:"tool_call_id"`
	Tool       string         `json:"tool"`
	Status     string         `json:"status"`
	Permission map[string]any `json:"permission,omitempty"`
	Result     map[string]any `json:"result"`
	Log        map[string]any `json:"log,omitempty"`
}

type ToolLoopCallbacks struct {
	SendToolCall   func(context.Context, ToolCallEvent) error
	WaitToolResult func(context.Context, string) (ToolResult, error)
	OnMessage      func(context.Context, string) error
	OnDelta        func(context.Context, string) error
}

type ToolLoopResult struct {
	Status     string
	Summary    string
	Messages   []ChatMessage
	ToolCalls  int
	Rejections []map[string]any
	Trace      []map[string]any
}

func RunToolLoop(ctx context.Context, client ToolStepClient, messages []ChatMessage, maxToolCalls int, callbacks ToolLoopCallbacks) (ToolLoopResult, error) {
	if client == nil {
		return ToolLoopResult{}, fmt.Errorf("tool loop requires a model client")
	}
	if callbacks.SendToolCall == nil || callbacks.WaitToolResult == nil {
		return ToolLoopResult{}, fmt.Errorf("tool loop requires send and wait callbacks")
	}
	if maxToolCalls < 1 {
		maxToolCalls = 1
	}
	result := ToolLoopResult{Status: "running", Messages: append([]ChatMessage{}, messages...)}
	for result.ToolCalls < maxToolCalls {
		step, err := generateToolStep(ctx, client, result.Messages, callbacks.OnDelta)
		if err != nil {
			return result, err
		}
		if step.Content != "" && callbacks.OnMessage != nil && !step.Streamed {
			if err := callbacks.OnMessage(ctx, step.Content); err != nil {
				return result, err
			}
		}
		if len(step.ToolCalls) == 0 {
			result.Status = "completed"
			result.Summary = step.Content
			return result, nil
		}
		result.Messages = append(result.Messages, ChatMessage{Role: "assistant", Content: step.Content, ToolCalls: step.ToolCalls})
		for _, call := range step.ToolCalls {
			risk, ok := ToolRisks[call.Name]
			if !ok {
				return result, fmt.Errorf("unknown tool: %s", call.Name)
			}
			if result.ToolCalls >= maxToolCalls {
				result.Status = "stopped"
				return result, fmt.Errorf("max tool calls reached")
			}
			result.ToolCalls++
			if err := callbacks.SendToolCall(ctx, ToolCallEvent{ID: call.ID, Tool: call.Name, Risk: risk, Args: call.Arguments}); err != nil {
				return result, err
			}
			toolResult, err := callbacks.WaitToolResult(ctx, call.ID)
			if err != nil {
				return result, err
			}
			result.Trace = append(result.Trace, toolTraceEntry(call, toolResult))
			if toolResult.Status == "rejected" {
				result.Rejections = append(result.Rejections, map[string]any{
					"tool":       call.Name,
					"args":       call.Arguments,
					"permission": toolResult.Permission,
				})
			}
			result.Messages = append(result.Messages, toolResultMessage(call, toolResult))
			if call.Name == "finish_build" && toolResult.Status == "ok" {
				result.Status = "completed"
				if summary, ok := call.Arguments["summary"].(string); ok {
					result.Summary = summary
				}
				return result, nil
			}
		}
	}
	result.Status = "stopped"
	return result, fmt.Errorf("max tool calls reached")
}

func generateToolStep(ctx context.Context, client ToolStepClient, messages []ChatMessage, onDelta func(context.Context, string) error) (ToolStep, error) {
	streaming, ok := client.(StreamingToolStepClient)
	if !ok || onDelta == nil {
		return client.GenerateToolStep(ctx, messages)
	}
	return streaming.StreamToolStep(ctx, messages, func(delta string) error {
		if delta == "" {
			return nil
		}
		return onDelta(ctx, delta)
	})
}

func toolTraceEntry(call ToolCall, result ToolResult) map[string]any {
	entry := map[string]any{
		"tool_call_id": call.ID,
		"tool":         call.Name,
		"args":         call.Arguments,
		"status":       result.Status,
		"result":       result.Result,
	}
	if result.Permission != nil {
		entry["permission"] = result.Permission
	}
	if result.Log != nil {
		entry["log"] = result.Log
	}
	return entry
}

func toolResultMessage(call ToolCall, result ToolResult) ChatMessage {
	payload := map[string]any{
		"status": result.Status,
		"result": result.Result,
	}
	data, _ := json.Marshal(payload)
	return ChatMessage{
		Role:       "tool",
		Content:    string(data),
		ToolCallID: call.ID,
		Name:       call.Name,
	}
}
