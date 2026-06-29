package aibuilder

import "testing"

func TestConfigFromSettings(t *testing.T) {
	cfg := ConfigFromSettings(map[string]any{
		"ai_builder": map[string]any{
			"provider":          "ollama",
			"base_url":          "http://127.0.0.1:11434",
			"model":             "qwen2.5",
			"api_key":           "secret",
			"temperature":       3.5,
			"reasoning_effort":  "high",
			"confirm_mode":      "auto",
			"max_tool_calls":    500,
			"max_repair_rounds": -1,
			"timeout_seconds":   1,
			"retry_attempts":    99,
		},
	})
	if cfg.Provider != "ollama" || cfg.BaseURL == "" || cfg.Model != "qwen2.5" {
		t.Fatalf("config = %#v", cfg)
	}
	if cfg.Temperature != 2 || cfg.MaxToolCalls != 200 || cfg.MaxRepairRounds != 0 ||
		cfg.TimeoutSeconds != 5 || cfg.RetryAttempts != 10 {
		t.Fatalf("clamped config = %#v", cfg)
	}
	if !cfg.ModelReady() {
		t.Fatalf("ModelReady() = false")
	}
	meta := cfg.SafeMetadata()
	if _, ok := meta["api_key"]; ok {
		t.Fatalf("metadata leaked api_key: %#v", meta)
	}
	if meta["api_key_configured"] != true {
		t.Fatalf("metadata = %#v", meta)
	}
}

func TestConfigFromSettingsDefaultsInvalidProvider(t *testing.T) {
	cfg := ConfigFromSettings(map[string]any{
		"ai_builder": map[string]any{"provider": "bad", "confirm_mode": "bad"},
	})
	if cfg.Provider != "openai" || cfg.ConfirmMode != "manual" {
		t.Fatalf("config = %#v", cfg)
	}
	if cfg.ModelReady() {
		t.Fatalf("ModelReady() = true without api key")
	}
}
