package device

import "testing"

func TestVMwareWebMKSURL(t *testing.T) {
	if got := vmwareWebMKSURL("esxi.local", 443, "abc/123"); got != "wss://esxi.local:443/ticket/abc/123" {
		t.Fatalf("url = %q", got)
	}
	if got := vmwareWebMKSURL("fd00::1", 9443, "ticket"); got != "wss://[fd00::1]:9443/ticket/ticket" {
		t.Fatalf("ipv6 url = %q", got)
	}
}
