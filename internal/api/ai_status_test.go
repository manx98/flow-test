package api

import (
	"strings"
	"testing"
)

func TestAIDraftStatusPayloadModel(t *testing.T) {
	payload := aiDraftStatusPayload(map[string]any{
		"metadata": map[string]any{"builder": "go-model-http"},
	})
	if payload["done_message"] != "Go AI Builder completed" {
		t.Fatalf("payload = %#v", payload)
	}
	if payload["metadata"] == nil {
		t.Fatalf("payload metadata missing = %#v", payload)
	}
}

func TestAIDraftStatusPayloadFallbackWithModelError(t *testing.T) {
	payload := aiDraftStatusPayload(map[string]any{
		"metadata": map[string]any{"builder": "go-local-fallback", "model_error": "connection refused"},
	})
	if payload["done_message"] != "Go fallback AI Builder completed" {
		t.Fatalf("payload = %#v", payload)
	}
	if payload["content"] == "未配置可用模型时，Go 运行时已生成一个可应用的 JS 流程骨架。" {
		t.Fatalf("payload did not mention model fallback = %#v", payload)
	}
}

func TestDocsFromStateSelectsScriptDocsForComplexRequests(t *testing.T) {
	docs := docsFromState(map[string]any{
		"message": "使用脚本简化复杂循环逻辑",
		"documents": []any{
			map[string]any{"name": "case.md", "text": "user doc"},
		},
	})
	names := docNames(docs)
	if !strings.Contains(names, "case.md") {
		t.Fatalf("user docs missing: %s", names)
	}
	if !strings.Contains(names, "graph_skills/script/script_js/DOC.md") || !strings.Contains(names, "graph_skills/script/script_js_exec/DOC.md") {
		t.Fatalf("script docs missing: %s", names)
	}
}

func TestDocsFromStateSelectsDocsForExistingGraphTypes(t *testing.T) {
	docs := docsFromState(map[string]any{
		"message": "继续优化",
		"current_graph": map[string]any{
			"nodes": []any{
				map[string]any{"type": "api/request"},
			},
		},
	})
	names := docNames(docs)
	if !strings.Contains(names, "graph_skills/api/api_request/DOC.md") {
		t.Fatalf("api request doc missing: %s", names)
	}
}

func docNames(docs []map[string]any) string {
	names := make([]string, 0, len(docs))
	for _, doc := range docs {
		if name, ok := doc["name"].(string); ok {
			names = append(names, name)
		}
	}
	return strings.Join(names, "\n")
}
