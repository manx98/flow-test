package aibuilder

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

type fakeModelClient struct {
	draft map[string]any
	err   error
}

func (c fakeModelClient) GenerateDraft(context.Context, string) (map[string]any, error) {
	if c.err != nil {
		return nil, c.err
	}
	return c.draft, nil
}

func TestBuilderUsesConfiguredModelClient(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	draft, err := NewBuilderWithClient(cfg, fakeModelClient{draft: baseDraft()}).BuildDraft(context.Background(), "build")
	if err != nil {
		t.Fatalf("BuildDraft() error = %v", err)
	}
	meta := draft["metadata"].(map[string]any)
	if meta["builder"] != "go-model-http" {
		t.Fatalf("metadata = %#v", meta)
	}
	model := meta["model"].(map[string]any)
	if _, ok := model["api_key"]; ok {
		t.Fatalf("metadata leaked api key: %#v", model)
	}
}

func TestBuilderFallsBackWhenModelClientFails(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	draft, err := NewBuilderWithClient(cfg, fakeModelClient{err: errModelUnavailable{}}).BuildDraft(context.Background(), "build")
	if err != nil {
		t.Fatalf("BuildDraft() error = %v", err)
	}
	meta := draft["metadata"].(map[string]any)
	if meta["builder"] != "go-local-fallback" || meta["model_error"] == "" {
		t.Fatalf("metadata = %#v", meta)
	}
}

type errModelUnavailable struct{}

func (errModelUnavailable) Error() string { return "model unavailable" }

func TestHTTPModelClientOpenAICompatible(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	cfg.BaseURL = "https://example.test/v1"
	client := NewHTTPModelClient(cfg)
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != "https://example.test/v1/chat/completions" {
			t.Fatalf("url = %s", req.URL.String())
		}
		if req.Header.Get("Authorization") != "Bearer secret" {
			t.Fatalf("authorization header = %q", req.Header.Get("Authorization"))
		}
		body := `{"choices":[{"message":{"content":"` + jsonEscapedDraft(baseDraft()) + `"}}]}`
		return &http.Response{
			StatusCode: 200,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(body)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	draft, err := client.GenerateDraft(context.Background(), "build")
	if err != nil {
		t.Fatalf("GenerateDraft() error = %v", err)
	}
	if draft["title"] == "" {
		t.Fatalf("draft = %#v", draft)
	}
}

func TestHTTPModelClientRetriesTransientStatus(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	cfg.BaseURL = "https://example.test/v1"
	cfg.RetryAttempts = 2
	client := NewHTTPModelClient(cfg)
	var calls int
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		calls++
		if calls == 1 {
			return &http.Response{
				StatusCode: 500,
				Status:     "500 Internal Server Error",
				Body:       io.NopCloser(strings.NewReader(`temporary`)),
				Header:     make(http.Header),
				Request:    req,
			}, nil
		}
		body := `{"choices":[{"message":{"content":"` + jsonEscapedDraft(baseDraft()) + `"}}]}`
		return &http.Response{
			StatusCode: 200,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(body)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	if _, err := client.GenerateDraft(context.Background(), "build"); err != nil {
		t.Fatalf("GenerateDraft() error = %v", err)
	}
	if calls != 2 {
		t.Fatalf("calls = %d", calls)
	}
}

func TestHTTPModelClientDoesNotRetryBadRequest(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	cfg.BaseURL = "https://example.test/v1"
	cfg.RetryAttempts = 3
	client := NewHTTPModelClient(cfg)
	var calls int
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		calls++
		return &http.Response{
			StatusCode: 400,
			Status:     "400 Bad Request",
			Body:       io.NopCloser(strings.NewReader(`bad request detail`)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	_, err := client.GenerateDraft(context.Background(), "build")
	if err == nil || !strings.Contains(err.Error(), "bad request detail") {
		t.Fatalf("error = %v", err)
	}
	if calls != 1 {
		t.Fatalf("calls = %d", calls)
	}
}

func TestHTTPModelClientGenerateToolStep(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	cfg.BaseURL = "https://example.test/v1"
	client := NewHTTPModelClient(cfg)
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		var body map[string]any
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			t.Fatalf("request JSON error = %v", err)
		}
		if len(body["tools"].([]any)) == 0 {
			t.Fatalf("request missing tools = %#v", body)
		}
		response := `{
			"choices": [{
				"message": {
					"content": "",
					"tool_calls": [{
						"id": "call_1",
						"type": "function",
						"function": {
							"name": "create_node",
							"arguments": "{\"type\":\"script/js\",\"pos\":[1,2]}"
						}
					}]
				}
			}]
		}`
		return &http.Response{
			StatusCode: 200,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(response)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	step, err := client.GenerateToolStep(context.Background(), []ChatMessage{
		{Role: "system", Content: "system"},
		{Role: "user", Content: "build"},
	})
	if err != nil {
		t.Fatalf("GenerateToolStep() error = %v", err)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Name != "create_node" {
		t.Fatalf("step = %#v", step)
	}
	if step.ToolCalls[0].Arguments["type"] != "script/js" {
		t.Fatalf("arguments = %#v", step.ToolCalls[0].Arguments)
	}
}

func TestHTTPModelClientGenerateToolStepRejectsBadArguments(t *testing.T) {
	cfg := DefaultConfig()
	cfg.APIKey = "secret"
	cfg.BaseURL = "https://example.test/v1"
	client := NewHTTPModelClient(cfg)
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		response := `{"choices":[{"message":{"tool_calls":[{"id":"call_1","function":{"name":"create_node","arguments":"{"}}]}}]}`
		return &http.Response{
			StatusCode: 200,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(response)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	_, err := client.GenerateToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}})
	if err == nil || !strings.Contains(err.Error(), "arguments JSON error") {
		t.Fatalf("error = %v", err)
	}
}

func TestHTTPModelClientGenerateOllamaToolStep(t *testing.T) {
	cfg := DefaultConfig()
	cfg.Provider = "ollama"
	cfg.BaseURL = "https://ollama.test"
	cfg.Model = "qwen"
	client := NewHTTPModelClient(cfg)
	client.client.Transport = roundTripFunc(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != "https://ollama.test/api/chat" {
			t.Fatalf("url = %s", req.URL.String())
		}
		var body map[string]any
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
			t.Fatalf("request JSON error = %v", err)
		}
		if body["stream"] != false || len(body["tools"].([]any)) == 0 {
			t.Fatalf("request = %#v", body)
		}
		response := `{
			"message": {
				"content": "",
				"tool_calls": [{
					"function": {
						"name": "finish_build",
						"arguments": {"summary": "ready"}
					}
				}]
			}
		}`
		return &http.Response{
			StatusCode: 200,
			Status:     "200 OK",
			Body:       io.NopCloser(strings.NewReader(response)),
			Header:     make(http.Header),
			Request:    req,
		}, nil
	})
	step, err := client.GenerateToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}})
	if err != nil {
		t.Fatalf("GenerateToolStep() error = %v", err)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Name != "finish_build" {
		t.Fatalf("step = %#v", step)
	}
	if step.ToolCalls[0].Arguments["summary"] != "ready" {
		t.Fatalf("arguments = %#v", step.ToolCalls[0].Arguments)
	}
}

func TestChatMessagesForModelIncludesToolMessages(t *testing.T) {
	messages := chatMessagesForModel([]ChatMessage{
		{Role: "assistant", Content: "", ToolCalls: []ToolCall{{ID: "call_1", Name: "create_node", Arguments: map[string]any{"type": "script/js"}}}},
		{Role: "tool", Content: `{"ok":true}`, ToolCallID: "call_1", Name: "create_node"},
	})
	assistant := messages[0]
	calls := assistant["tool_calls"].([]map[string]any)
	if calls[0]["id"] != "call_1" {
		t.Fatalf("assistant message = %#v", assistant)
	}
	tool := messages[1]
	if tool["role"] != "tool" || tool["tool_call_id"] != "call_1" || tool["name"] != "create_node" {
		t.Fatalf("tool message = %#v", tool)
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

func jsonEscapedDraft(draft map[string]any) string {
	var buf bytes.Buffer
	if err := json.NewEncoder(&buf).Encode(draft); err != nil {
		panic(err)
	}
	text := strings.TrimSpace(buf.String())
	text = strings.ReplaceAll(text, `\`, `\\`)
	text = strings.ReplaceAll(text, `"`, `\"`)
	text = strings.ReplaceAll(text, "\n", `\n`)
	return text
}
