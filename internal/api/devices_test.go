package api

import (
	"context"
	"testing"
)

func TestDispatchDeviceInputNilDevice(t *testing.T) {
	if err := dispatchDeviceInput(context.Background(), nil, deviceInputEvent{Type: "move"}); err != errUnsupportedDeviceInput {
		t.Fatalf("err = %v", err)
	}
}
