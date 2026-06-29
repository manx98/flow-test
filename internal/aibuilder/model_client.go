package aibuilder

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type ModelClient interface {
	GenerateDraft(context.Context, string) (map[string]any, error)
}

type ToolCall struct {
	ID        string         `json:"id"`
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
}

type ToolStep struct {
	Content   string     `json:"content,omitempty"`
	ToolCalls []ToolCall `json:"tool_calls,omitempty"`
	Streamed  bool       `json:"streamed,omitempty"`
}

type HTTPModelClient struct {
	config Config
	client *http.Client
}

func NewHTTPModelClient(config Config) *HTTPModelClient {
	timeout := time.Duration(config.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	return &HTTPModelClient{
		config: config,
		client: &http.Client{Timeout: timeout},
	}
}

func (c *HTTPModelClient) GenerateDraft(ctx context.Context, message string) (map[string]any, error) {
	content, err := c.generateContentWithRetry(ctx, message)
	if err != nil {
		return nil, err
	}
	draft, err := parseDraftJSON(content)
	if err != nil {
		return nil, err
	}
	return CompileDraft(draft)
}

func (c *HTTPModelClient) GenerateToolStep(ctx context.Context, messages []ChatMessage) (ToolStep, error) {
	if c.config.Provider == "ollama" {
		return c.generateOllamaToolStep(ctx, messages)
	}
	return c.generateOpenAIToolStep(ctx, messages)
}

func (c *HTTPModelClient) generateContentWithRetry(ctx context.Context, message string) (string, error) {
	attempts := c.config.RetryAttempts
	if attempts < 1 {
		attempts = 1
	}
	var content string
	var err error
	for attempt := 1; attempt <= attempts; attempt++ {
		if c.config.Provider == "ollama" {
			content, err = c.generateOllama(ctx, message)
		} else {
			content, err = c.generateOpenAICompatible(ctx, message)
		}
		if err == nil {
			return content, nil
		}
		if attempt == attempts || !retryableModelError(err) {
			break
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-time.After(modelRetryDelay(attempt)):
		}
	}
	return "", err
}

func (c *HTTPModelClient) generateOpenAICompatible(ctx context.Context, message string) (string, error) {
	endpoint, err := joinURL(c.openAIBaseURL(), "chat/completions")
	if err != nil {
		return "", err
	}
	body := map[string]any{
		"model":       c.config.Model,
		"temperature": c.config.Temperature,
		"messages": []map[string]string{
			{"role": "system", "content": draftSystemPrompt()},
			{"role": "user", "content": message},
		},
	}
	if c.config.ReasoningEffort != "" {
		body["reasoning_effort"] = c.config.ReasoningEffort
	}
	data, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.config.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.config.APIKey)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return "", modelRequestError{err: err, retry: retryableNetworkError(err)}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", modelRequestError{err: modelStatusError(resp), retry: retryableStatus(resp.StatusCode)}
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
			Text string `json:"text"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", err
	}
	if len(parsed.Choices) == 0 {
		return "", fmt.Errorf("model response has no choices")
	}
	content := parsed.Choices[0].Message.Content
	if content == "" {
		content = parsed.Choices[0].Text
	}
	if strings.TrimSpace(content) == "" {
		return "", fmt.Errorf("model response content is empty")
	}
	return content, nil
}

func (c *HTTPModelClient) generateOpenAIToolStep(ctx context.Context, messages []ChatMessage) (ToolStep, error) {
	endpoint, err := joinURL(c.openAIBaseURL(), "chat/completions")
	if err != nil {
		return ToolStep{}, err
	}
	body := map[string]any{
		"model":       c.config.Model,
		"temperature": c.config.Temperature,
		"messages":    chatMessagesForModel(messages),
		"tools":       ToolsForModel(),
		"tool_choice": "auto",
	}
	if c.config.ReasoningEffort != "" {
		body["reasoning_effort"] = c.config.ReasoningEffort
	}
	data, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return ToolStep{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.config.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.config.APIKey)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		return ToolStep{}, modelRequestError{err: err, retry: retryableNetworkError(err)}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ToolStep{}, modelRequestError{err: modelStatusError(resp), retry: retryableStatus(resp.StatusCode)}
	}
	var parsed struct {
		Choices []struct {
			Message struct {
				Content   string `json:"content"`
				ToolCalls []struct {
					ID       string `json:"id"`
					Type     string `json:"type"`
					Function struct {
						Name      string `json:"name"`
						Arguments string `json:"arguments"`
					} `json:"function"`
				} `json:"tool_calls"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return ToolStep{}, err
	}
	if len(parsed.Choices) == 0 {
		return ToolStep{}, fmt.Errorf("model response has no choices")
	}
	msg := parsed.Choices[0].Message
	step := ToolStep{Content: msg.Content}
	for _, call := range msg.ToolCalls {
		if call.Function.Name == "" {
			continue
		}
		args, err := decodeStringToolArguments(call.Function.Name, call.Function.Arguments)
		if err != nil {
			return ToolStep{}, err
		}
		step.ToolCalls = append(step.ToolCalls, ToolCall{
			ID:        call.ID,
			Name:      call.Function.Name,
			Arguments: args,
		})
	}
	if strings.TrimSpace(step.Content) == "" && len(step.ToolCalls) == 0 {
		return ToolStep{}, fmt.Errorf("model response has no content or tool calls")
	}
	return step, nil
}

func (c *HTTPModelClient) generateOllamaToolStep(ctx context.Context, messages []ChatMessage) (ToolStep, error) {
	endpoint, err := joinURL(c.config.BaseURL, "api/chat")
	if err != nil {
		return ToolStep{}, err
	}
	body := map[string]any{
		"model":    c.config.Model,
		"stream":   false,
		"messages": chatMessagesForModel(messages),
		"tools":    ToolsForModel(),
		"options":  map[string]any{"temperature": c.config.Temperature},
	}
	data, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return ToolStep{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.client.Do(req)
	if err != nil {
		return ToolStep{}, modelRequestError{err: err, retry: retryableNetworkError(err)}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return ToolStep{}, modelRequestError{err: modelStatusError(resp), retry: retryableStatus(resp.StatusCode)}
	}
	var parsed struct {
		Message struct {
			Content   string `json:"content"`
			ToolCalls []struct {
				Function struct {
					Name      string          `json:"name"`
					Arguments json.RawMessage `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"message"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return ToolStep{}, err
	}
	step := ToolStep{Content: parsed.Message.Content}
	for index, call := range parsed.Message.ToolCalls {
		if call.Function.Name == "" {
			continue
		}
		args, err := decodeRawToolArguments(call.Function.Name, call.Function.Arguments)
		if err != nil {
			return ToolStep{}, err
		}
		step.ToolCalls = append(step.ToolCalls, ToolCall{
			ID:        fmt.Sprintf("ollama_call_%d", index),
			Name:      call.Function.Name,
			Arguments: args,
		})
	}
	if strings.TrimSpace(step.Content) == "" && len(step.ToolCalls) == 0 {
		return ToolStep{}, fmt.Errorf("model response has no content or tool calls")
	}
	return step, nil
}

func (c *HTTPModelClient) generateOllama(ctx context.Context, message string) (string, error) {
	endpoint, err := joinURL(c.config.BaseURL, "api/chat")
	if err != nil {
		return "", err
	}
	body := map[string]any{
		"model":  c.config.Model,
		"stream": false,
		"messages": []map[string]string{
			{"role": "system", "content": draftSystemPrompt()},
			{"role": "user", "content": message},
		},
		"options": map[string]any{"temperature": c.config.Temperature},
	}
	data, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.client.Do(req)
	if err != nil {
		return "", modelRequestError{err: err, retry: retryableNetworkError(err)}
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return "", modelRequestError{err: modelStatusError(resp), retry: retryableStatus(resp.StatusCode)}
	}
	var parsed struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
		Response string `json:"response"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", err
	}
	content := parsed.Message.Content
	if content == "" {
		content = parsed.Response
	}
	if strings.TrimSpace(content) == "" {
		return "", fmt.Errorf("model response content is empty")
	}
	return content, nil
}

func decodeStringToolArguments(name string, arguments string) (map[string]any, error) {
	return decodeRawToolArguments(name, json.RawMessage(strings.TrimSpace(arguments)))
}

func decodeRawToolArguments(name string, raw json.RawMessage) (map[string]any, error) {
	args := map[string]any{}
	text := strings.TrimSpace(string(raw))
	if text == "" || text == "null" {
		return args, nil
	}
	if strings.HasPrefix(text, `"`) {
		var inner string
		if err := json.Unmarshal(raw, &inner); err != nil {
			return nil, fmt.Errorf("tool call %s arguments JSON error: %w", name, err)
		}
		text = strings.TrimSpace(inner)
		if text == "" {
			return args, nil
		}
		raw = json.RawMessage(text)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(&args); err != nil {
		return nil, fmt.Errorf("tool call %s arguments JSON error: %w", name, err)
	}
	return args, nil
}

func (c *HTTPModelClient) openAIBaseURL() string {
	if c.config.BaseURL != "" {
		return c.config.BaseURL
	}
	return "https://api.openai.com/v1"
}

func draftSystemPrompt() string {
	return strings.Join([]string{
		"Return only a JSON object for a flow-test AI Builder draft.",
		"The JSON object must contain nodes and links arrays.",
		"Prefer script/js plus script/js_exec for complex logic.",
		"Use setResult('ok', boolean) and connect ok to assert/check.",
		"Pass devices, images, masks, OCR, text, numbers, and booleans through graph ports instead of hard-coding resources.",
		"AI-generated scripts must not use file, network, OS, subprocess, eval, Function, dynamic import, or package-install operations.",
		"Do not include markdown, comments, or prose outside JSON.",
	}, "\n")
}

func parseDraftJSON(content string) (map[string]any, error) {
	text := strings.TrimSpace(content)
	if strings.HasPrefix(text, "```") {
		text = strings.TrimSpace(strings.TrimPrefix(text, "```json"))
		text = strings.TrimSpace(strings.TrimPrefix(text, "```"))
		text = strings.TrimSpace(strings.TrimSuffix(text, "```"))
	}
	start := strings.Index(text, "{")
	end := strings.LastIndex(text, "}")
	if start < 0 || end < start {
		return nil, fmt.Errorf("model response does not contain JSON object")
	}
	text = text[start : end+1]
	dec := json.NewDecoder(strings.NewReader(text))
	dec.UseNumber()
	var draft map[string]any
	if err := dec.Decode(&draft); err != nil {
		return nil, err
	}
	if extra, err := io.ReadAll(dec.Buffered()); err == nil && strings.TrimSpace(string(extra)) != "" {
		return nil, fmt.Errorf("model response contains trailing JSON data")
	}
	return draft, nil
}

func chatMessagesForModel(messages []ChatMessage) []map[string]any {
	out := make([]map[string]any, 0, len(messages))
	for _, msg := range messages {
		role := strings.TrimSpace(msg.Role)
		if role == "" {
			role = "user"
		}
		item := map[string]any{"role": role, "content": msg.Content}
		if msg.ToolCallID != "" {
			item["tool_call_id"] = msg.ToolCallID
		}
		if msg.Name != "" {
			item["name"] = msg.Name
		}
		if len(msg.ToolCalls) > 0 {
			calls := make([]map[string]any, 0, len(msg.ToolCalls))
			for _, call := range msg.ToolCalls {
				args, _ := json.Marshal(call.Arguments)
				calls = append(calls, map[string]any{
					"id":   call.ID,
					"type": "function",
					"function": map[string]any{
						"name":      call.Name,
						"arguments": string(args),
					},
				})
			}
			item["tool_calls"] = calls
		}
		out = append(out, item)
	}
	return out
}

type modelRequestError struct {
	err   error
	retry bool
}

func (e modelRequestError) Error() string {
	return e.err.Error()
}

func (e modelRequestError) Unwrap() error {
	return e.err
}

func retryableModelError(err error) bool {
	if e, ok := err.(modelRequestError); ok {
		return e.retry
	}
	return false
}

func retryableStatus(status int) bool {
	return status == http.StatusTooManyRequests || status >= 500
}

func retryableNetworkError(err error) bool {
	var netErr net.Error
	return errors.As(err, &netErr) && (netErr.Timeout() || netErr.Temporary())
}

func modelRetryDelay(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	delay := time.Duration(attempt) * 100 * time.Millisecond
	if delay > time.Second {
		return time.Second
	}
	return delay
}

func modelStatusError(resp *http.Response) error {
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
	detail := strings.TrimSpace(string(body))
	if detail == "" {
		return fmt.Errorf("model request failed: %s", resp.Status)
	}
	return fmt.Errorf("model request failed: %s: %s", resp.Status, short(detail, 240))
}

func joinURL(base, path string) (string, error) {
	if strings.TrimSpace(base) == "" {
		return "", fmt.Errorf("base URL is empty")
	}
	u, err := url.Parse(base)
	if err != nil {
		return "", err
	}
	if u.Scheme == "" || u.Host == "" {
		return "", fmt.Errorf("base URL must include scheme and host")
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/" + strings.TrimLeft(path, "/")
	return u.String(), nil
}
