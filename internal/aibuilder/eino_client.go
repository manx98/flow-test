package aibuilder

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/cloudwego/eino/components/model"
	"github.com/cloudwego/eino/schema"
	"github.com/eino-contrib/jsonschema"
)

type EinoModelClient struct {
	model model.ToolCallingChatModel
}

func NewEinoModelClient(config Config) (*EinoModelClient, error) {
	timeout := time.Duration(config.TimeoutSeconds) * time.Second
	if timeout <= 0 {
		timeout = 120 * time.Second
	}
	base := &httpEinoChatModel{
		config: config,
		http:   &http.Client{Timeout: timeout},
	}
	withTools, err := base.WithTools(EinoTools())
	if err != nil {
		return nil, err
	}
	return &EinoModelClient{model: withTools}, nil
}

func (c *EinoModelClient) GenerateToolStep(ctx context.Context, messages []ChatMessage) (ToolStep, error) {
	msg, err := c.model.Generate(ctx, toEinoMessages(messages))
	if err != nil {
		return ToolStep{}, err
	}
	return fromEinoMessage(msg)
}

func (c *EinoModelClient) StreamToolStep(ctx context.Context, messages []ChatMessage, onDelta func(string) error) (ToolStep, error) {
	stream, err := c.model.Stream(ctx, toEinoMessages(messages))
	if err != nil {
		return ToolStep{}, err
	}
	defer stream.Close()
	var full strings.Builder
	toolBuilders := map[string]*streamToolCallBuilder{}
	var toolOrder []string
	for {
		msg, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return ToolStep{}, err
		}
		if msg == nil {
			continue
		}
		if msg.Content != "" {
			full.WriteString(msg.Content)
			if onDelta != nil {
				if err := onDelta(msg.Content); err != nil {
					return ToolStep{}, err
				}
			}
		}
		for _, call := range msg.ToolCalls {
			mergeStreamToolCall(toolBuilders, &toolOrder, call)
		}
	}
	toolCalls, err := streamToolCalls(toolBuilders, toolOrder)
	if err != nil {
		return ToolStep{}, err
	}
	if full.Len() == 0 && len(toolCalls) == 0 {
		return ToolStep{}, fmt.Errorf("model stream has no content or tool calls")
	}
	return ToolStep{Content: full.String(), ToolCalls: toolCalls, Streamed: full.Len() > 0}, nil
}

func EinoTools() []*schema.ToolInfo {
	specs := BuildToolSpecs()
	out := make([]*schema.ToolInfo, 0, len(specs))
	for _, spec := range specs {
		out = append(out, &schema.ToolInfo{
			Name:        spec.Name,
			Desc:        spec.Description,
			ParamsOneOf: schema.NewParamsOneOfByJSONSchema(toolJSONSchema(spec)),
			Extra: map[string]any{
				"risk":       spec.Risk,
				"parameters": spec.Parameters,
				"required":   spec.Required,
			},
		})
	}
	return out
}

func toolJSONSchema(spec ToolSpec) *jsonschema.Schema {
	raw := map[string]any{
		"type":                 "object",
		"properties":           spec.Parameters,
		"required":             spec.Required,
		"additionalProperties": false,
	}
	data, _ := json.Marshal(raw)
	var out jsonschema.Schema
	if err := json.Unmarshal(data, &out); err != nil {
		return &jsonschema.Schema{}
	}
	return &out
}

func toEinoMessages(messages []ChatMessage) []*schema.Message {
	out := make([]*schema.Message, 0, len(messages))
	for _, msg := range messages {
		switch msg.Role {
		case "system":
			out = append(out, schema.SystemMessage(msg.Content))
		case "assistant":
			out = append(out, schema.AssistantMessage(msg.Content, toEinoToolCalls(msg.ToolCalls)))
		case "tool":
			out = append(out, schema.ToolMessage(msg.Content, msg.ToolCallID, schema.WithToolName(msg.Name)))
		default:
			out = append(out, schema.UserMessage(msg.Content))
		}
	}
	return out
}

func toEinoToolCalls(calls []ToolCall) []schema.ToolCall {
	out := make([]schema.ToolCall, 0, len(calls))
	for _, call := range calls {
		args, _ := json.Marshal(call.Arguments)
		out = append(out, schema.ToolCall{
			ID:   call.ID,
			Type: "function",
			Function: schema.FunctionCall{
				Name:      call.Name,
				Arguments: string(args),
			},
		})
	}
	return out
}

func fromEinoMessage(msg *schema.Message) (ToolStep, error) {
	if msg == nil {
		return ToolStep{}, fmt.Errorf("model response is nil")
	}
	step := ToolStep{Content: msg.Content}
	for _, call := range msg.ToolCalls {
		toolCall, err := fromEinoToolCall(call)
		if err != nil {
			return ToolStep{}, err
		}
		step.ToolCalls = append(step.ToolCalls, toolCall)
	}
	if strings.TrimSpace(step.Content) == "" && len(step.ToolCalls) == 0 {
		return ToolStep{}, fmt.Errorf("model response has no content or tool calls")
	}
	return step, nil
}

func fromEinoToolCall(call schema.ToolCall) (ToolCall, error) {
	args := map[string]any{}
	if strings.TrimSpace(call.Function.Arguments) != "" {
		dec := json.NewDecoder(strings.NewReader(call.Function.Arguments))
		dec.UseNumber()
		if err := dec.Decode(&args); err != nil {
			return ToolCall{}, fmt.Errorf("tool call %s arguments JSON error: %w", call.Function.Name, err)
		}
	}
	return ToolCall{ID: call.ID, Name: call.Function.Name, Arguments: args}, nil
}

type streamToolCallBuilder struct {
	index     int
	id        string
	name      string
	arguments strings.Builder
}

func mergeStreamToolCall(builders map[string]*streamToolCallBuilder, order *[]string, call schema.ToolCall) {
	key := call.ID
	index := len(*order)
	if call.Index != nil {
		index = *call.Index
		key = fmt.Sprintf("index:%d", index)
	}
	if key == "" {
		key = fmt.Sprintf("anonymous:%d", len(*order))
	}
	builder := builders[key]
	if builder == nil {
		builder = &streamToolCallBuilder{index: index}
		builders[key] = builder
		*order = append(*order, key)
	}
	if call.ID != "" {
		builder.id = call.ID
	}
	if call.Function.Name != "" {
		builder.name = call.Function.Name
	}
	if call.Function.Arguments != "" {
		builder.arguments.WriteString(call.Function.Arguments)
	}
}

func streamToolCalls(builders map[string]*streamToolCallBuilder, order []string) ([]ToolCall, error) {
	out := make([]ToolCall, 0, len(order))
	for _, key := range order {
		builder := builders[key]
		if builder == nil {
			continue
		}
		args := map[string]any{}
		rawArgs := strings.TrimSpace(builder.arguments.String())
		if rawArgs != "" {
			dec := json.NewDecoder(strings.NewReader(rawArgs))
			dec.UseNumber()
			if err := dec.Decode(&args); err != nil {
				return nil, fmt.Errorf("tool call %s arguments JSON error: %w", builder.name, err)
			}
		}
		id := builder.id
		if id == "" {
			id = fmt.Sprintf("tool_call_%d", builder.index)
		}
		out = append(out, ToolCall{ID: id, Name: builder.name, Arguments: args})
	}
	return out, nil
}

type httpEinoChatModel struct {
	config Config
	http   *http.Client
	tools  []*schema.ToolInfo
}

func (m *httpEinoChatModel) WithTools(tools []*schema.ToolInfo) (model.ToolCallingChatModel, error) {
	next := *m
	next.tools = tools
	return &next, nil
}

func (m *httpEinoChatModel) Generate(ctx context.Context, input []*schema.Message, _ ...model.Option) (*schema.Message, error) {
	body := m.requestBody(input, false)
	resp, err := m.do(ctx, body)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if m.config.Provider == "ollama" {
		return decodeOllamaMessage(resp.Body)
	}
	return decodeOpenAIMessage(resp.Body)
}

func (m *httpEinoChatModel) Stream(ctx context.Context, input []*schema.Message, _ ...model.Option) (*schema.StreamReader[*schema.Message], error) {
	body := m.requestBody(input, true)
	resp, err := m.do(ctx, body)
	if err != nil {
		return nil, err
	}
	reader, writer := schema.Pipe[*schema.Message](8)
	go func() {
		defer writer.Close()
		defer resp.Body.Close()
		if m.config.Provider == "ollama" {
			m.streamOllama(resp.Body, writer)
			return
		}
		scanner := bufio.NewScanner(resp.Body)
		scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if !strings.HasPrefix(line, "data:") {
				continue
			}
			data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if data == "[DONE]" {
				return
			}
			msg, err := decodeOpenAIStreamMessage(strings.NewReader(data))
			if err != nil {
				writer.Send(nil, err)
				return
			}
			if msg == nil {
				continue
			}
			if writer.Send(msg, nil) {
				return
			}
		}
		if err := scanner.Err(); err != nil {
			writer.Send(nil, err)
		}
	}()
	return reader, nil
}

func (m *httpEinoChatModel) streamOllama(body io.Reader, writer *schema.StreamWriter[*schema.Message]) {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		msg, done, err := decodeOllamaStreamMessage(strings.NewReader(line))
		if err != nil {
			writer.Send(nil, err)
			return
		}
		if msg != nil && writer.Send(msg, nil) {
			return
		}
		if done {
			return
		}
	}
	if err := scanner.Err(); err != nil {
		writer.Send(nil, err)
	}
}

func (m *httpEinoChatModel) requestBody(input []*schema.Message, stream bool) map[string]any {
	if m.config.Provider == "ollama" {
		return map[string]any{
			"model":    m.config.Model,
			"messages": openAIRequestMessages(input),
			"tools":    openAIRequestTools(m.tools),
			"stream":   stream,
			"options":  map[string]any{"temperature": m.config.Temperature},
		}
	}
	body := map[string]any{
		"model":       m.config.Model,
		"temperature": m.config.Temperature,
		"messages":    openAIRequestMessages(input),
		"tools":       openAIRequestTools(m.tools),
		"tool_choice": "auto",
		"stream":      stream,
	}
	if m.config.ReasoningEffort != "" {
		body["reasoning_effort"] = m.config.ReasoningEffort
	}
	return body
}

func (m *httpEinoChatModel) do(ctx context.Context, body map[string]any) (*http.Response, error) {
	endpointPath := "chat/completions"
	baseURL := m.openAIBaseURL()
	if m.config.Provider == "ollama" {
		endpointPath = "api/chat"
		baseURL = m.config.BaseURL
	}
	endpoint, err := joinURL(baseURL, endpointPath)
	if err != nil {
		return nil, err
	}
	data, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if m.config.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+m.config.APIKey)
	}
	resp, err := m.http.Do(req)
	if err != nil {
		return nil, modelRequestError{err: err, retry: retryableNetworkError(err)}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		return nil, modelRequestError{err: modelStatusError(resp), retry: retryableStatus(resp.StatusCode)}
	}
	return resp, nil
}

func (m *httpEinoChatModel) openAIBaseURL() string {
	if m.config.BaseURL != "" {
		return m.config.BaseURL
	}
	return "https://api.openai.com/v1"
}

func openAIRequestMessages(input []*schema.Message) []map[string]any {
	out := make([]map[string]any, 0, len(input))
	for _, msg := range input {
		if msg == nil {
			continue
		}
		item := map[string]any{
			"role":    string(msg.Role),
			"content": msg.Content,
		}
		if msg.Name != "" {
			item["name"] = msg.Name
		}
		if msg.ToolCallID != "" {
			item["tool_call_id"] = msg.ToolCallID
		}
		if len(msg.ToolCalls) > 0 {
			item["tool_calls"] = openAIToolCalls(msg.ToolCalls)
		}
		out = append(out, item)
	}
	return out
}

func openAIRequestTools(tools []*schema.ToolInfo) []map[string]any {
	out := make([]map[string]any, 0, len(tools))
	for _, tool := range tools {
		if tool == nil {
			continue
		}
		out = append(out, map[string]any{
			"type": "function",
			"function": map[string]any{
				"name":        tool.Name,
				"description": tool.Desc,
				"parameters":  openAIToolParameters(tool),
			},
		})
	}
	return out
}

func openAIToolParameters(tool *schema.ToolInfo) map[string]any {
	if tool != nil && tool.ParamsOneOf != nil {
		if jsonSchema, err := tool.ParamsOneOf.ToJSONSchema(); err == nil && jsonSchema != nil {
			data, _ := json.Marshal(jsonSchema)
			params := map[string]any{}
			if err := json.Unmarshal(data, &params); err == nil {
				return params
			}
		}
	}
	if tool == nil {
		return map[string]any{"type": "object", "properties": map[string]any{}}
	}
	params, _ := tool.Extra["parameters"].(map[string]any)
	required, _ := tool.Extra["required"].([]string)
	return map[string]any{
		"type":                 "object",
		"properties":           params,
		"required":             required,
		"additionalProperties": false,
	}
}

func openAIToolCalls(calls []schema.ToolCall) []map[string]any {
	out := make([]map[string]any, 0, len(calls))
	for _, call := range calls {
		out = append(out, map[string]any{
			"id":   call.ID,
			"type": "function",
			"function": map[string]any{
				"name":      call.Function.Name,
				"arguments": call.Function.Arguments,
			},
		})
	}
	return out
}

func decodeOpenAIMessage(r io.Reader) (*schema.Message, error) {
	var parsed struct {
		Choices []struct {
			Message openAIMessagePayload `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(r).Decode(&parsed); err != nil {
		return nil, err
	}
	if len(parsed.Choices) == 0 {
		return nil, fmt.Errorf("model response has no choices")
	}
	return parsed.Choices[0].Message.toEinoMessage()
}

func decodeOpenAIStreamMessage(r io.Reader) (*schema.Message, error) {
	var parsed struct {
		Choices []struct {
			Delta openAIMessagePayload `json:"delta"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(r).Decode(&parsed); err != nil {
		return nil, err
	}
	if len(parsed.Choices) == 0 {
		return nil, nil
	}
	return parsed.Choices[0].Delta.toEinoMessage()
}

func decodeOllamaMessage(r io.Reader) (*schema.Message, error) {
	var parsed struct {
		Message ollamaMessagePayload `json:"message"`
	}
	if err := json.NewDecoder(r).Decode(&parsed); err != nil {
		return nil, err
	}
	return parsed.Message.toEinoMessage()
}

func decodeOllamaStreamMessage(r io.Reader) (*schema.Message, bool, error) {
	var parsed struct {
		Message ollamaMessagePayload `json:"message"`
		Done    bool                 `json:"done"`
		Error   string               `json:"error"`
	}
	if err := json.NewDecoder(r).Decode(&parsed); err != nil {
		return nil, false, err
	}
	if parsed.Error != "" {
		return nil, parsed.Done, fmt.Errorf("ollama stream error: %s", parsed.Error)
	}
	msg, err := parsed.Message.toEinoMessage()
	if err != nil {
		return nil, parsed.Done, err
	}
	if msg.Content == "" && len(msg.ToolCalls) == 0 {
		return nil, parsed.Done, nil
	}
	return msg, parsed.Done, nil
}

type openAIMessagePayload struct {
	Role      string `json:"role"`
	Content   string `json:"content"`
	ToolCalls []struct {
		ID       string `json:"id"`
		Index    *int   `json:"index"`
		Type     string `json:"type"`
		Function struct {
			Name      string `json:"name"`
			Arguments string `json:"arguments"`
		} `json:"function"`
	} `json:"tool_calls"`
}

func (p openAIMessagePayload) toEinoMessage() (*schema.Message, error) {
	msg := &schema.Message{
		Role:    schema.Assistant,
		Content: p.Content,
	}
	if p.Role != "" {
		msg.Role = schema.RoleType(p.Role)
	}
	for _, call := range p.ToolCalls {
		msg.ToolCalls = append(msg.ToolCalls, schema.ToolCall{
			Index: call.Index,
			ID:    call.ID,
			Type:  "function",
			Function: schema.FunctionCall{
				Name:      call.Function.Name,
				Arguments: call.Function.Arguments,
			},
		})
	}
	return msg, nil
}

type ollamaMessagePayload struct {
	Role      string `json:"role"`
	Content   string `json:"content"`
	ToolCalls []struct {
		Function struct {
			Name      string          `json:"name"`
			Arguments json.RawMessage `json:"arguments"`
		} `json:"function"`
	} `json:"tool_calls"`
}

func (p ollamaMessagePayload) toEinoMessage() (*schema.Message, error) {
	msg := &schema.Message{
		Role:    schema.Assistant,
		Content: p.Content,
	}
	if p.Role != "" {
		msg.Role = schema.RoleType(p.Role)
	}
	for index, call := range p.ToolCalls {
		if call.Function.Name == "" {
			continue
		}
		args, err := decodeRawToolArguments(call.Function.Name, call.Function.Arguments)
		if err != nil {
			return nil, err
		}
		rawArgs, _ := json.Marshal(args)
		idx := index
		msg.ToolCalls = append(msg.ToolCalls, schema.ToolCall{
			Index: &idx,
			ID:    fmt.Sprintf("ollama_call_%d", index),
			Type:  "function",
			Function: schema.FunctionCall{
				Name:      call.Function.Name,
				Arguments: string(rawArgs),
			},
		})
	}
	return msg, nil
}
