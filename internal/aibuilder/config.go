package aibuilder

import (
	"fmt"
	"strings"
)

type Config struct {
	Provider        string
	BaseURL         string
	Model           string
	APIKey          string
	Temperature     float64
	ReasoningEffort string
	ConfirmMode     string
	MaxToolCalls    int
	MaxRepairRounds int
	TimeoutSeconds  int
	RetryAttempts   int
}

func DefaultConfig() Config {
	return Config{
		Provider:        "openai",
		Model:           "gpt-4o",
		Temperature:     0,
		ConfirmMode:     "manual",
		MaxToolCalls:    40,
		MaxRepairRounds: 5,
		TimeoutSeconds:  120,
		RetryAttempts:   10,
	}
}

func ConfigFromSettings(settings map[string]any) Config {
	cfg := DefaultConfig()
	raw, _ := settings["ai_builder"].(map[string]any)
	if raw == nil {
		return cfg
	}
	cfg.Provider = enumString(raw["provider"], cfg.Provider, "openai", "ollama", "custom")
	cfg.BaseURL = strings.TrimSpace(stringSetting(raw["base_url"], cfg.BaseURL))
	cfg.Model = strings.TrimSpace(stringSetting(raw["model"], cfg.Model))
	cfg.APIKey = stringSetting(raw["api_key"], cfg.APIKey)
	cfg.Temperature = clampFloat(floatSetting(raw["temperature"], cfg.Temperature), 0, 2)
	cfg.ReasoningEffort = enumString(raw["reasoning_effort"], cfg.ReasoningEffort, "", "low", "medium", "high")
	cfg.ConfirmMode = enumString(raw["confirm_mode"], cfg.ConfirmMode, "manual", "auto")
	cfg.MaxToolCalls = clampInt(intSetting(raw["max_tool_calls"], cfg.MaxToolCalls), 1, 200)
	cfg.MaxRepairRounds = clampInt(intSetting(raw["max_repair_rounds"], cfg.MaxRepairRounds), 0, 50)
	cfg.TimeoutSeconds = clampInt(intSetting(raw["timeout_seconds"], cfg.TimeoutSeconds), 5, 600)
	cfg.RetryAttempts = clampInt(intSetting(raw["retry_attempts"], cfg.RetryAttempts), 1, 10)
	return cfg
}

func (c Config) ModelReady() bool {
	switch c.Provider {
	case "ollama":
		return c.BaseURL != "" && c.Model != ""
	case "custom":
		return c.BaseURL != "" && c.Model != ""
	default:
		return c.Model != "" && c.APIKey != ""
	}
}

func (c Config) SafeMetadata() map[string]any {
	return map[string]any{
		"provider":            c.Provider,
		"base_url_configured": c.BaseURL != "",
		"model":               c.Model,
		"api_key_configured":  c.APIKey != "",
		"temperature":         c.Temperature,
		"reasoning_effort":    c.ReasoningEffort,
		"confirm_mode":        c.ConfirmMode,
		"max_tool_calls":      c.MaxToolCalls,
		"max_repair_rounds":   c.MaxRepairRounds,
		"timeout_seconds":     c.TimeoutSeconds,
		"retry_attempts":      c.RetryAttempts,
		"model_ready":         c.ModelReady(),
	}
}

func stringSetting(value any, fallback string) string {
	if s, ok := value.(string); ok {
		return s
	}
	return fallback
}

func floatSetting(value any, fallback float64) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case jsonNumber:
		f, err := v.Float64()
		if err == nil {
			return f
		}
	}
	return fallback
}

func intSetting(value any, fallback int) int {
	switch v := value.(type) {
	case float64:
		return int(v)
	case int:
		return v
	case int64:
		return int(v)
	case jsonNumber:
		i, err := v.Int64()
		if err == nil {
			return int(i)
		}
	}
	return fallback
}

type jsonNumber interface {
	Float64() (float64, error)
	Int64() (int64, error)
}

func enumString(value any, fallback string, allowed ...string) string {
	text := stringSetting(value, fallback)
	for _, candidate := range allowed {
		if text == candidate {
			return text
		}
	}
	return fallback
}

func clampFloat(value, minValue, maxValue float64) float64 {
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func clampInt(value, minValue, maxValue int) int {
	if value < minValue {
		return minValue
	}
	if value > maxValue {
		return maxValue
	}
	return value
}

func (c Config) fallbackReason() string {
	if c.ModelReady() {
		return fmt.Sprintf("Model provider %s is configured, but model generation failed; local fallback was used.", c.Provider)
	}
	return "Model provider is not fully configured; local fallback builder was used."
}
