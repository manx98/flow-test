package device

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

type rdpConfig struct {
	Host               string
	Port               int
	Username           string
	Password           string
	Domain             string
	Auth               string
	Width              int
	Height             int
	ConnectTimeout     time.Duration
	FirstUpdateTimeout time.Duration
}

func parseRDPConfig(config map[string]any) (rdpConfig, error) {
	cfg := rdpConfig{
		Host:               stringConfig(config, "host"),
		Port:               intFromConfig(config, "port", 3389),
		Username:           stringConfig(config, "username"),
		Password:           stringConfig(config, "password"),
		Domain:             stringConfig(config, "domain"),
		Width:              intFromConfig(config, "width", 1280),
		Height:             intFromConfig(config, "height", 800),
		ConnectTimeout:     time.Duration(intFromConfig(config, "connect_timeout", 60)) * time.Second,
		FirstUpdateTimeout: time.Duration(intFromConfig(config, "first_update_timeout", 30)) * time.Second,
	}
	cfg.Auth = strings.ToLower(strings.TrimSpace(stringConfig(config, "security_protocol")))
	if cfg.Auth == "" {
		cfg.Auth = strings.ToLower(strings.TrimSpace(stringConfig(config, "auth")))
	}
	if cfg.Auth == "" {
		cfg.Auth = "auto"
	}
	if cfg.Host == "" {
		return rdpConfig{}, fmt.Errorf("rdp device requires host")
	}
	return cfg, nil
}

func (c rdpConfig) Address() string {
	return c.Host + ":" + strconv.Itoa(c.Port)
}

type rdpKeyCode struct {
	Code     uint16
	Shift    bool
	Extended bool
}

func rdpScanCode(key Key) (rdpKeyCode, bool) {
	raw := string(key)
	if len(raw) == 1 {
		r := rune(raw[0])
		if r >= 'A' && r <= 'Z' {
			sc, ok := rdpUSScanCodes[r+'a'-'A']
			sc.Shift = true
			return sc, ok
		}
	}
	text := strings.ToLower(raw)
	if sc, ok := rdpNamedScanCodes[text]; ok {
		return sc, true
	}
	if len(text) == 1 {
		sc, ok := rdpUSScanCodes[rune(text[0])]
		return sc, ok
	}
	return rdpKeyCode{}, false
}

var rdpNamedScanCodes = map[string]rdpKeyCode{
	"esc":       {Code: 0x01},
	"escape":    {Code: 0x01},
	"backspace": {Code: 0x0e},
	"tab":       {Code: 0x0f},
	"enter":     {Code: 0x1c},
	"return":    {Code: 0x1c},
	"ctrl":      {Code: 0x1d},
	"control":   {Code: 0x1d},
	"shift":     {Code: 0x2a},
	"alt":       {Code: 0x38},
	"space":     {Code: 0x39},
	"delete":    {Code: 0x53, Extended: true},
	"home":      {Code: 0x47, Extended: true},
	"end":       {Code: 0x4f, Extended: true},
	"pageup":    {Code: 0x49, Extended: true},
	"pagedown":  {Code: 0x51, Extended: true},
	"left":      {Code: 0x4b, Extended: true},
	"right":     {Code: 0x4d, Extended: true},
	"up":        {Code: 0x48, Extended: true},
	"down":      {Code: 0x50, Extended: true},
}

var rdpUSScanCodes = map[rune]rdpKeyCode{
	'1': {Code: 0x02}, '2': {Code: 0x03}, '3': {Code: 0x04}, '4': {Code: 0x05}, '5': {Code: 0x06},
	'6': {Code: 0x07}, '7': {Code: 0x08}, '8': {Code: 0x09}, '9': {Code: 0x0a}, '0': {Code: 0x0b},
	'q': {Code: 0x10}, 'w': {Code: 0x11}, 'e': {Code: 0x12}, 'r': {Code: 0x13}, 't': {Code: 0x14},
	'y': {Code: 0x15}, 'u': {Code: 0x16}, 'i': {Code: 0x17}, 'o': {Code: 0x18}, 'p': {Code: 0x19},
	'a': {Code: 0x1e}, 's': {Code: 0x1f}, 'd': {Code: 0x20}, 'f': {Code: 0x21}, 'g': {Code: 0x22},
	'h': {Code: 0x23}, 'j': {Code: 0x24}, 'k': {Code: 0x25}, 'l': {Code: 0x26},
	'z': {Code: 0x2c}, 'x': {Code: 0x2d}, 'c': {Code: 0x2e}, 'v': {Code: 0x2f}, 'b': {Code: 0x30},
	'n': {Code: 0x31}, 'm': {Code: 0x32}, ' ': {Code: 0x39},
	'-': {Code: 0x0c}, '=': {Code: 0x0d}, '[': {Code: 0x1a}, ']': {Code: 0x1b}, '\\': {Code: 0x2b},
	';': {Code: 0x27}, '\'': {Code: 0x28}, '`': {Code: 0x29}, ',': {Code: 0x33}, '.': {Code: 0x34}, '/': {Code: 0x35},
	'!': {Code: 0x02, Shift: true}, '@': {Code: 0x03, Shift: true}, '#': {Code: 0x04, Shift: true},
	'$': {Code: 0x05, Shift: true}, '%': {Code: 0x06, Shift: true}, '^': {Code: 0x07, Shift: true},
	'&': {Code: 0x08, Shift: true}, '*': {Code: 0x09, Shift: true}, '(': {Code: 0x0a, Shift: true},
	')': {Code: 0x0b, Shift: true}, '_': {Code: 0x0c, Shift: true}, '+': {Code: 0x0d, Shift: true},
	'{': {Code: 0x1a, Shift: true}, '}': {Code: 0x1b, Shift: true}, '|': {Code: 0x2b, Shift: true},
	':': {Code: 0x27, Shift: true}, '"': {Code: 0x28, Shift: true}, '~': {Code: 0x29, Shift: true},
	'<': {Code: 0x33, Shift: true}, '>': {Code: 0x34, Shift: true}, '?': {Code: 0x35, Shift: true},
}
