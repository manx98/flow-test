package device

import "testing"

func TestParseRDPConfigUsesAuthAndSecurityProtocol(t *testing.T) {
	cfg, err := parseRDPConfig(map[string]any{
		"host": "127.0.0.1",
		"auth": "rdp",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Auth != "rdp" {
		t.Fatalf("auth = %q", cfg.Auth)
	}

	cfg, err = parseRDPConfig(map[string]any{
		"host":              "127.0.0.1",
		"auth":              "rdp",
		"security_protocol": "tls",
	})
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Auth != "tls" {
		t.Fatalf("security_protocol should override auth, got %q", cfg.Auth)
	}
}

func TestRDPScanCodeTracksShift(t *testing.T) {
	sc, ok := rdpScanCode(Key("A"))
	if !ok || sc.Code != 0x1e || !sc.Shift {
		t.Fatalf("A scan code = %#v ok=%v", sc, ok)
	}

	sc, ok = rdpScanCode(Key("!"))
	if !ok || sc.Code != 0x02 || !sc.Shift {
		t.Fatalf("! scan code = %#v ok=%v", sc, ok)
	}
}
