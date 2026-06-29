package aibuilder

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestDirectBuildSystemPromptUsesJS(t *testing.T) {
	prompt := DirectBuildSystemPrompt()
	if !strings.Contains(prompt, "script/js") || !strings.Contains(prompt, "script/js_exec") {
		t.Fatalf("prompt = %s", prompt)
	}
	if strings.Contains(prompt, "script/python") || strings.Contains(prompt, "script/exec") {
		t.Fatalf("prompt still references Python script nodes: %s", prompt)
	}
	if !strings.Contains(prompt, "set_node_ports") || !strings.Contains(prompt, "finish_build") {
		t.Fatalf("prompt missing tool guidance: %s", prompt)
	}
}

func TestBuildDirectBuildMessagesPayload(t *testing.T) {
	history := []any{}
	for i := 0; i < 18; i++ {
		history = append(history, map[string]any{"role": "user", "content": "msg"})
	}
	rejected := []any{}
	for i := 0; i < 10; i++ {
		rejected = append(rejected, map[string]any{"tool": "create_node"})
	}
	trace := []any{}
	for i := 0; i < 14; i++ {
		trace = append(trace, map[string]any{"tool": "validate_canvas", "status": "error"})
	}
	messages := BuildDirectBuildMessages(
		map[string]any{
			"message": "build login test",
			"history": history,
			"current_graph": map[string]any{
				"nodes": []any{
					map[string]any{"type": "flow/start"},
					map[string]any{
						"id":    2,
						"type":  "script/js",
						"title": "Logic",
						"outputs": []any{
							map[string]any{"name": "script", "type": "script", "links": []any{1}},
						},
					},
				},
				"links": []any{[]any{1, 1, 0, 2, 0, "exec"}},
			},
			"form_values": map[string]any{"x": 1},
		},
		[]map[string]any{{"name": "case.md", "text": strings.Repeat("a", 7000)}},
		map[string]any{"build_state": map[string]any{
			"rejected_operations": rejected,
			"last_tool_loop":      map[string]any{"trace": trace},
		}},
	)
	if len(messages) != 2 || messages[0].Role != "system" || messages[1].Role != "user" {
		t.Fatalf("messages = %#v", messages)
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(messages[1].Content), &payload); err != nil {
		t.Fatalf("payload JSON error = %v", err)
	}
	if payload["user_instruction"] != "build login test" {
		t.Fatalf("payload = %#v", payload)
	}
	if len(payload["recent_chat"].([]any)) != 16 {
		t.Fatalf("recent_chat = %#v", payload["recent_chat"])
	}
	if len(payload["soft_rejected_operations"].([]any)) != 8 {
		t.Fatalf("soft_rejected_operations = %#v", payload["soft_rejected_operations"])
	}
	if len(payload["recent_tool_trace"].([]any)) != 12 {
		t.Fatalf("recent_tool_trace = %#v", payload["recent_tool_trace"])
	}
	summary := payload["current_canvas_summary"].(map[string]any)
	if summary["node_count"] != float64(2) || summary["link_count"] != float64(1) {
		t.Fatalf("summary = %#v", summary)
	}
	nodes := summary["nodes"].([]any)
	if len(nodes) != 2 || nodes[1].(map[string]any)["title"] != "Logic" {
		t.Fatalf("summary nodes = %#v", nodes)
	}
	if len(payload["documents"].(string)) > 6200 {
		t.Fatalf("documents were not trimmed")
	}
}
