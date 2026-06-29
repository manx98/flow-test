package aibuilder

import (
	"context"
	"strings"
)

type Builder struct {
	config Config
	client ModelClient
}

func NewBuilder() *Builder {
	return NewBuilderWithConfig(DefaultConfig())
}

func NewBuilderWithConfig(config Config) *Builder {
	return NewBuilderWithClient(config, NewHTTPModelClient(config))
}

func NewBuilderWithClient(config Config, client ModelClient) *Builder {
	return &Builder{config: config, client: client}
}

func (b *Builder) BuildDraft(ctx context.Context, message string) (map[string]any, error) {
	if b.config.ModelReady() && b.client != nil {
		if draft, err := b.client.GenerateDraft(ctx, message); err == nil {
			annotateDraftMetadata(draft, "go-model-http", b.config, "")
			return CompileDraft(draft)
		} else {
			return CompileDraft(b.buildFallbackDraft(ctx, message, err.Error()))
		}
	}
	return CompileDraft(b.buildFallbackDraft(ctx, message, ""))
}

func BuildFallbackDraft(message string) map[string]any {
	return NewBuilder().BuildFallbackDraft(context.Background(), message)
}

func (b *Builder) BuildFallbackDraft(_ context.Context, message string) map[string]any {
	return b.buildFallbackDraft(context.Background(), message, "")
}

func (b *Builder) buildFallbackDraft(_ context.Context, message string, modelError string) map[string]any {
	title := "JS fallback test flow"
	summary := "Local fallback draft: execute JavaScript logic, assert the ok result, and finish the test."
	if strings.TrimSpace(message) != "" {
		title = "JS test flow draft"
		summary = "Local fallback draft for: " + short(message, 120)
	}
	cfg := b.config
	draft := map[string]any{
		"title":   title,
		"summary": summary,
		"stats": map[string]any{
			"steps": 4,
			"nodes": 4,
			"links": 4,
		},
		"notes": []any{
			cfg.fallbackReason(),
			"Edit the JS script or add dynamic inputs to wire real devices, images, OCR, or API data.",
		},
		"nodes": []any{
			map[string]any{
				"id":   "script",
				"type": "script/js",
				"pos":  []any{0, 0},
				"properties": map[string]any{
					"code": fallbackCode(message),
				},
			},
			map[string]any{
				"id":   "exec",
				"type": "script/js_exec",
				"pos":  []any{260, 0},
				"inputs": []any{
					map[string]any{"name": "in", "type": "exec"},
					map[string]any{"name": "script", "type": "script"},
				},
				"outputs": []any{
					map[string]any{"name": "out", "type": "exec"},
					map[string]any{"name": "ok", "type": "bool"},
				},
			},
			map[string]any{
				"id":   "assert",
				"type": "assert/check",
				"pos":  []any{520, 0},
				"properties": map[string]any{
					"message": "JS flow result should be ok",
				},
			},
			map[string]any{
				"id":   "result",
				"type": "test/result",
				"pos":  []any{780, 0},
			},
		},
		"links": []any{
			map[string]any{"from": "script", "out": "script", "to": "exec", "in": "script"},
			map[string]any{"from": "exec", "out": "ok", "to": "assert", "in": "cond"},
			map[string]any{"from": "exec", "out": "out", "to": "assert", "in": "in"},
			map[string]any{"from": "assert", "out": "pass", "to": "result", "in": "in"},
		},
		"entry": "exec",
	}
	annotateDraftMetadata(draft, "go-local-fallback", cfg, modelError)
	return draft
}

func annotateDraftMetadata(draft map[string]any, builder string, cfg Config, modelError string) {
	meta, _ := draft["metadata"].(map[string]any)
	if meta == nil {
		meta = map[string]any{}
		draft["metadata"] = meta
	}
	meta["builder"] = builder
	meta["model"] = cfg.SafeMetadata()
	if modelError != "" {
		meta["model_error"] = short(modelError, 240)
	}
}

func fallbackCode(message string) string {
	lines := []string{
		"// Local Go fallback draft. Replace this with the real test logic.",
		"// Read graph resources with getArg('name') and publish business results with setResult('ok', bool).",
	}
	if strings.TrimSpace(message) != "" {
		lines = append(lines, "// Request: "+escapeLine(short(message, 180)))
	}
	lines = append(lines,
		"const ok = true;",
		"log('JS fallback flow executed');",
		"setResult('ok', ok);",
		"",
	)
	return strings.Join(lines, "\n")
}

func short(value string, limit int) string {
	value = strings.TrimSpace(strings.Join(strings.Fields(value), " "))
	if len(value) <= limit {
		return value
	}
	if limit <= 3 {
		return value[:limit]
	}
	return value[:limit-3] + "..."
}

func escapeLine(value string) string {
	return strings.ReplaceAll(value, "\n", " ")
}
