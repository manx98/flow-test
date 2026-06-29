package aibuilder

import "testing"

func TestCompileDraftAcceptsScriptDynamicPorts(t *testing.T) {
	draft := baseDraft()
	exec := draft["nodes"].([]any)[1].(map[string]any)
	exec["inputs"] = []any{
		map[string]any{"name": "in", "type": "exec"},
		map[string]any{"name": "script", "type": "script"},
		map[string]any{"name": "device", "type": "device"},
		map[string]any{"name": "name", "type": "text"},
	}
	exec["outputs"] = []any{
		map[string]any{"name": "out", "type": "exec"},
		map[string]any{"name": "ok", "type": "bool"},
		map[string]any{"name": "message", "type": "text"},
	}
	draft["links"] = append(draft["links"].([]any),
		map[string]any{"from": "exec", "out": "message", "to": "display", "in": "text"},
	)
	if _, err := CompileDraft(draft); err != nil {
		t.Fatalf("CompileDraft() error = %v", err)
	}
}

func TestCompileDraftRejectsNonScriptDynamicPort(t *testing.T) {
	draft := baseDraft()
	assertNode := draft["nodes"].([]any)[2].(map[string]any)
	assertNode["inputs"] = []any{
		map[string]any{"name": "in", "type": "exec"},
		map[string]any{"name": "cond", "type": "bool"},
		map[string]any{"name": "extra", "type": "text"},
	}
	if _, err := CompileDraft(draft); err == nil {
		t.Fatalf("CompileDraft() expected error")
	}
}

func TestCompileDraftRejectsBadDynamicPortType(t *testing.T) {
	draft := baseDraft()
	exec := draft["nodes"].([]any)[1].(map[string]any)
	exec["outputs"] = []any{
		map[string]any{"name": "out", "type": "exec"},
		map[string]any{"name": "ok", "type": "bool"},
		map[string]any{"name": "next", "type": "exec"},
	}
	if _, err := CompileDraft(draft); err == nil {
		t.Fatalf("CompileDraft() expected error")
	}
}

func TestCompileDraftRejectsDuplicatePort(t *testing.T) {
	draft := baseDraft()
	exec := draft["nodes"].([]any)[1].(map[string]any)
	exec["inputs"] = []any{
		map[string]any{"name": "script", "type": "script"},
		map[string]any{"name": "script", "type": "script"},
	}
	if _, err := CompileDraft(draft); err == nil {
		t.Fatalf("CompileDraft() expected error")
	}
}

func TestCompileDraftRejectsBadJSSyntax(t *testing.T) {
	draft := baseDraft()
	script := draft["nodes"].([]any)[0].(map[string]any)
	script["properties"] = map[string]any{"code": "const value = ;"}
	if _, err := CompileDraft(draft); err == nil {
		t.Fatalf("CompileDraft() expected error")
	}
}

func TestBuildDraftCompilesFallback(t *testing.T) {
	if _, err := NewBuilder().BuildDraft(nil, "check login"); err != nil {
		t.Fatalf("BuildDraft() error = %v", err)
	}
}

func baseDraft() map[string]any {
	return map[string]any{
		"nodes": []any{
			map[string]any{
				"id":         "script",
				"type":       "script/js",
				"properties": map[string]any{"code": "setResult('ok', true);"},
			},
			map[string]any{
				"id":   "exec",
				"type": "script/js_exec",
				"inputs": []any{
					map[string]any{"name": "in", "type": "exec"},
					map[string]any{"name": "script", "type": "script"},
				},
				"outputs": []any{
					map[string]any{"name": "out", "type": "exec"},
					map[string]any{"name": "ok", "type": "bool"},
				},
			},
			map[string]any{"id": "assert", "type": "assert/check"},
			map[string]any{"id": "result", "type": "test/result"},
			map[string]any{
				"id":     "display",
				"type":   "data/text_display",
				"inputs": []any{map[string]any{"name": "text", "type": "text"}},
			},
		},
		"links": []any{
			map[string]any{"from": "script", "out": "script", "to": "exec", "in": "script"},
			map[string]any{"from": "exec", "out": "ok", "to": "assert", "in": "cond"},
			map[string]any{"from": "exec", "out": "out", "to": "assert", "in": "in"},
			map[string]any{"from": "assert", "out": "pass", "to": "result", "in": "in"},
		},
	}
}
