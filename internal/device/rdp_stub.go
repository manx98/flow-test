//go:build !linux || !cgo

package device

import "fmt"

func NewRDPDevice(config map[string]any) (Device, error) {
	cfg, err := parseRDPConfig(config)
	if err != nil {
		return nil, err
	}
	return nil, fmt.Errorf(
		"RDP requires Linux cgo build with FreeRDP 2 development libraries; install with: sudo apt-get install -y freerdp2-dev libfreerdp2-2 libfreerdp-client2-2 libwinpr2-dev; then build with: CGO_ENABLED=1 go build ./cmd/flow-test (target %s)",
		cfg.Address(),
	)
}
