package aibuilder

import (
	"encoding/json"
	"strings"
)

type ChatMessage struct {
	Role       string     `json:"role"`
	Content    string     `json:"content"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
	Name       string     `json:"name,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
}

func BuildDirectBuildMessages(init map[string]any, docs []map[string]any, session map[string]any) []ChatMessage {
	payload := map[string]any{
		"user_instruction":         stringValue(init["message"]),
		"recent_chat":              recentChat(init, session),
		"documents":                docsText(docs),
		"current_canvas_summary":   graphSummary(init["current_graph"]),
		"form_values":              mapValue(init["form_values"]),
		"soft_rejected_operations": rejectedOperations(session),
		"recent_tool_trace":        recentToolTrace(session),
	}
	data, _ := json.Marshal(payload)
	return []ChatMessage{
		{Role: "system", Content: DirectBuildSystemPrompt()},
		{Role: "user", Content: string(data)},
	}
}

func DirectBuildSystemPrompt() string {
	return strings.Join([]string{
		"You are an expert QA automation flow builder operating a real LiteGraph canvas through tools.",
		"Do not output a final graph JSON. Build the graph step by step by calling tools.",
		"Use list_node_types and read_node_spec before creating unfamiliar nodes. Use only node types, ports, and properties from the catalog.",
		"Write tools mutate the user's actual canvas and may require confirmation. If a tool fails, inspect/read specs and repair with different parameters.",
		"If a user previously rejected an operation, treat it as a soft hint and avoid repeating it unless the user explicitly changed requirements.",
		"Use recent_tool_trace to avoid repeating failed or rejected operations; repair the canvas from its current state instead of rebuilding blindly.",
		"For HTTP/API calls, use api/request and connect its status/body/ok outputs to logs, scripts, assertions, or result nodes as needed. Use JSON/form serialization nodes for request/response conversion. Do not put network calls inside scripts.",
		"Use script/js + script/js_exec only when it materially simplifies complex logic: loops, repeated UI operations, combined conditions, variable calculations, or tangled graph wiring. Keep simple click/wait/OCR/assert flows as visual nodes.",
		"When using scripts, create script/js and script/js_exec, call set_node_ports on script/js_exec for resource inputs and bool/text/etc result outputs, then connect resources and assertions. Pass devices, template pictures, masks, OCR engines, text, numbers, and booleans through ports instead of hard-coding them.",
		"Script business failures should usually call setResult('ok', boolean) and connect that result to assert/check and test/result. Reserve throw for unexpected errors.",
		"AI-generated scripts must not use file, network, OS, subprocess, eval, Function, dynamic import, or package-install operations.",
		"When the graph is structurally complete, call finish_build with a concise summary. The frontend will run validate_canvas; repair any validation errors.",
		"Never ask the frontend to run the test flow. Do not include hidden reasoning; short visible status messages are enough.",
	}, "\n")
}

func recentChat(init, session map[string]any) []map[string]string {
	raw := anySliceOrNil(init["history"])
	if len(raw) == 0 {
		raw = anySliceOrNil(session["messages"])
	}
	start := 0
	if len(raw) > 16 {
		start = len(raw) - 16
	}
	out := []map[string]string{}
	for _, item := range raw[start:] {
		msg, ok := item.(map[string]any)
		if !ok {
			continue
		}
		content := stringValue(msg["content"])
		if content == "" {
			continue
		}
		role := stringValue(msg["role"])
		if role == "" {
			role = "user"
		}
		out = append(out, map[string]string{"role": role, "content": content})
	}
	return out
}

func docsText(docs []map[string]any) string {
	if len(docs) == 0 {
		return "(none)"
	}
	parts := make([]string, 0, len(docs))
	for _, doc := range docs {
		name := stringValue(doc["name"])
		if name == "" {
			name = "case.txt"
		}
		text := short(stringValue(doc["text"]), 6000)
		parts = append(parts, "### "+name+"\n"+text)
	}
	return strings.Join(parts, "\n\n")
}

func graphSummary(value any) map[string]any {
	graph := mapValue(value)
	nodes := anySliceOrNil(graph["nodes"])
	links := anySliceOrNil(graph["links"])
	types := map[string]int{}
	nodeSummaries := make([]map[string]any, 0, minInt(len(nodes), 40))
	for idx, item := range nodes {
		node, ok := item.(map[string]any)
		if !ok {
			continue
		}
		typ := stringValue(node["type"])
		if typ != "" {
			types[typ]++
		}
		if idx < 40 {
			nodeSummaries = append(nodeSummaries, compactNodeSummary(node))
		}
	}
	return map[string]any{
		"node_count": len(nodes),
		"link_count": len(links),
		"types":      types,
		"nodes":      nodeSummaries,
	}
}

func compactNodeSummary(node map[string]any) map[string]any {
	out := map[string]any{
		"id":    node["id"],
		"type":  stringValue(node["type"]),
		"title": stringValue(node["title"]),
	}
	if ref := stringValue(node["ref"]); ref != "" {
		out["ref"] = ref
	}
	if pos := anySliceOrNil(node["pos"]); len(pos) >= 2 {
		out["pos"] = pos[:2]
	}
	if inputs := compactPorts(node["inputs"], true); len(inputs) > 0 {
		out["inputs"] = inputs
	}
	if outputs := compactPorts(node["outputs"], false); len(outputs) > 0 {
		out["outputs"] = outputs
	}
	return out
}

func compactPorts(value any, input bool) []map[string]any {
	items := anySliceOrNil(value)
	out := make([]map[string]any, 0, minInt(len(items), 12))
	for idx, item := range items {
		if idx >= 12 {
			break
		}
		port, ok := item.(map[string]any)
		if !ok {
			continue
		}
		entry := map[string]any{
			"name": stringValue(port["name"]),
			"type": stringValue(port["type"]),
		}
		if input {
			if port["link"] != nil {
				entry["linked"] = true
			}
		} else {
			if links := anySliceOrNil(port["links"]); len(links) > 0 {
				entry["links"] = len(links)
			}
		}
		out = append(out, entry)
	}
	return out
}

func rejectedOperations(session map[string]any) []any {
	buildState := mapValue(session["build_state"])
	rejected := anySliceOrNil(buildState["rejected_operations"])
	if len(rejected) > 8 {
		return rejected[len(rejected)-8:]
	}
	return rejected
}

func recentToolTrace(session map[string]any) []any {
	buildState := mapValue(session["build_state"])
	loop := mapValue(buildState["last_tool_loop"])
	trace := anySliceOrNil(loop["trace"])
	if len(trace) > 12 {
		return trace[len(trace)-12:]
	}
	return trace
}

func mapValue(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func anySliceOrNil(value any) []any {
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

func stringValue(value any) string {
	if s, ok := value.(string); ok {
		return s
	}
	return ""
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
