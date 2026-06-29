package aibuilder

import (
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

func TestNewEinoModelClientDefaultTimeout(t *testing.T) {
	client, err := NewEinoModelClient(Config{Provider: "custom", BaseURL: "https://example.test/v1", Model: "test-model"})
	if err != nil {
		t.Fatalf("NewEinoModelClient() error = %v", err)
	}
	underlying, ok := client.model.(*httpEinoChatModel)
	if !ok {
		t.Fatalf("model type = %T", client.model)
	}
	if underlying.http.Timeout != 120*time.Second {
		t.Fatalf("timeout = %s", underlying.http.Timeout)
	}
}

func TestEinoModelClientStreamsContentAndToolCalls(t *testing.T) {
	var sawStream bool
	base := &httpEinoChatModel{
		config: Config{Provider: "custom", BaseURL: "https://example.test/v1", Model: "test-model", ReasoningEffort: "low", TimeoutSeconds: 30},
		http: &http.Client{Timeout: 30 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.URL.String() != "https://example.test/v1/chat/completions" {
				t.Fatalf("url = %s", r.URL.String())
			}
			requestBody := readRequestBody(t, r)
			if !strings.Contains(requestBody, `"stream":true`) {
				t.Fatalf("request did not enable stream")
			}
			if !strings.Contains(requestBody, `"reasoning_effort":"low"`) {
				t.Fatalf("request did not include reasoning_effort: %s", requestBody)
			}
			sawStream = true
			return &http.Response{
				StatusCode: 200,
				Status:     "200 OK",
				Header:     make(http.Header),
				Request:    r,
				Body: io.NopCloser(strings.NewReader(`data: {"choices":[{"delta":{"content":"hello "}}]}

data: {"choices":[{"delta":{"content":"world"}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"finish_build","arguments":"{\"summary\""}}]}}]}

data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":":\"ok\"}"}}]}}]}

data: [DONE]

`)),
			}, nil
		})},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		t.Fatalf("WithTools() error = %v", err)
	}
	client := &EinoModelClient{model: withTools}
	var deltas []string
	step, err := client.StreamToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}}, func(delta string) error {
		deltas = append(deltas, delta)
		return nil
	})
	if err != nil {
		t.Fatalf("StreamToolStep() error = %v", err)
	}
	if !sawStream || strings.Join(deltas, "") != "hello world" {
		t.Fatalf("sawStream=%v deltas=%#v", sawStream, deltas)
	}
	if step.Content != "hello world" || !step.Streamed {
		t.Fatalf("step = %#v", step)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Name != "finish_build" {
		t.Fatalf("tool calls = %#v", step.ToolCalls)
	}
	if step.ToolCalls[0].Arguments["summary"] != "ok" {
		t.Fatalf("tool call arguments = %#v", step.ToolCalls[0].Arguments)
	}
}

func TestEinoModelClientStreamsLargeToolArguments(t *testing.T) {
	longSummary := strings.Repeat("x", 80*1024)
	arguments := `{\"summary\":\"` + longSummary + `\"}`
	base := &httpEinoChatModel{
		config: Config{Provider: "custom", BaseURL: "https://example.test/v1", Model: "test-model", TimeoutSeconds: 30},
		http: &http.Client{Timeout: 30 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			return &http.Response{
				StatusCode: 200,
				Status:     "200 OK",
				Header:     make(http.Header),
				Request:    r,
				Body: io.NopCloser(strings.NewReader(`data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"finish_build","arguments":"` + arguments + `"}}]}}]}

data: [DONE]

`)),
			}, nil
		})},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		t.Fatalf("WithTools() error = %v", err)
	}
	client := &EinoModelClient{model: withTools}
	step, err := client.StreamToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}}, nil)
	if err != nil {
		t.Fatalf("StreamToolStep() error = %v", err)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Arguments["summary"] != longSummary {
		t.Fatalf("tool calls = %#v", step.ToolCalls)
	}
}

func TestEinoModelClientReturnsStreamDecodeError(t *testing.T) {
	base := &httpEinoChatModel{
		config: Config{Provider: "custom", BaseURL: "https://example.test/v1", Model: "test-model", TimeoutSeconds: 30},
		http: &http.Client{Timeout: 30 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			return &http.Response{
				StatusCode: 200,
				Status:     "200 OK",
				Header:     make(http.Header),
				Request:    r,
				Body:       io.NopCloser(strings.NewReader("data: {bad-json}\n\n")),
			}, nil
		})},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		t.Fatalf("WithTools() error = %v", err)
	}
	client := &EinoModelClient{model: withTools}
	_, err = client.StreamToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}}, nil)
	if err == nil {
		t.Fatalf("StreamToolStep() error = nil")
	}
}

func TestEinoModelClientGenerateOllamaToolCall(t *testing.T) {
	base := &httpEinoChatModel{
		config: Config{Provider: "ollama", BaseURL: "https://ollama.test", Model: "qwen", TimeoutSeconds: 30},
		http: &http.Client{Timeout: 30 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if r.URL.String() != "https://ollama.test/api/chat" {
				t.Fatalf("url = %s", r.URL.String())
			}
			requestBody := readRequestBody(t, r)
			if !strings.Contains(requestBody, `"stream":false`) || !strings.Contains(requestBody, `"tools"`) {
				t.Fatalf("request = %s", requestBody)
			}
			return &http.Response{
				StatusCode: 200,
				Status:     "200 OK",
				Header:     make(http.Header),
				Request:    r,
				Body: io.NopCloser(strings.NewReader(`{
					"message": {
						"role": "assistant",
						"content": "",
						"tool_calls": [{
							"function": {
								"name": "finish_build",
								"arguments": {"summary": "ollama ready"}
							}
						}]
					}
				}`)),
			}, nil
		})},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		t.Fatalf("WithTools() error = %v", err)
	}
	client := &EinoModelClient{model: withTools}
	step, err := client.GenerateToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}})
	if err != nil {
		t.Fatalf("GenerateToolStep() error = %v", err)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Name != "finish_build" || step.ToolCalls[0].Arguments["summary"] != "ollama ready" {
		t.Fatalf("step = %#v", step)
	}
}

func TestEinoModelClientStreamsOllamaToolCall(t *testing.T) {
	base := &httpEinoChatModel{
		config: Config{Provider: "ollama", BaseURL: "https://ollama.test", Model: "qwen", TimeoutSeconds: 30},
		http: &http.Client{Timeout: 30 * time.Second, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
			if !strings.Contains(readRequestBody(t, r), `"stream":true`) {
				t.Fatalf("request did not enable stream")
			}
			return &http.Response{
				StatusCode: 200,
				Status:     "200 OK",
				Header:     make(http.Header),
				Request:    r,
				Body: io.NopCloser(strings.NewReader(`{"message":{"role":"assistant","content":"building "},"done":false}
{"message":{"role":"assistant","content":"flow"},"done":false}
{"message":{"role":"assistant","tool_calls":[{"function":{"name":"finish_build","arguments":{"summary":"done"}}}]},"done":false}
{"done":true}
`)),
			}, nil
		})},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		t.Fatalf("WithTools() error = %v", err)
	}
	client := &EinoModelClient{model: withTools}
	var deltas []string
	step, err := client.StreamToolStep(context.Background(), []ChatMessage{{Role: "user", Content: "build"}}, func(delta string) error {
		deltas = append(deltas, delta)
		return nil
	})
	if err != nil {
		t.Fatalf("StreamToolStep() error = %v", err)
	}
	if strings.Join(deltas, "") != "building flow" || step.Content != "building flow" {
		t.Fatalf("step=%#v deltas=%#v", step, deltas)
	}
	if len(step.ToolCalls) != 1 || step.ToolCalls[0].Arguments["summary"] != "done" {
		t.Fatalf("tool calls = %#v", step.ToolCalls)
	}
}

func TestEinoToolsExposeRiskMetadata(t *testing.T) {
	tools := EinoTools()
	if len(tools) == 0 {
		t.Fatalf("tools empty")
	}
	for _, tool := range tools {
		if tool.Name == "set_node_ports" {
			if tool.Extra["risk"] != "write" || tool.Extra["parameters"] == nil {
				t.Fatalf("tool = %#v", tool)
			}
			if tool.ParamsOneOf == nil {
				t.Fatalf("tool missing standard params schema")
			}
			jsonSchema, err := tool.ParamsOneOf.ToJSONSchema()
			if err != nil {
				t.Fatalf("ToJSONSchema() error = %v", err)
			}
			if jsonSchema == nil {
				t.Fatalf("tool params schema is nil")
			}
			return
		}
	}
	t.Fatalf("set_node_ports not found")
}

func readRequestBody(t *testing.T, r *http.Request) string {
	t.Helper()
	data, err := io.ReadAll(r.Body)
	if err != nil {
		t.Fatalf("read body error = %v", err)
	}
	return string(data)
}
