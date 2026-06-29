package api

import (
	"context"
	"image/png"
	"net/http"

	"flow-test-go/internal/device"

	"github.com/gin-gonic/gin"
)

func (s *Server) connectDevice(c *gin.Context) {
	var body struct {
		Kind    string         `json:"kind"`
		Config  map[string]any `json:"config"`
		Project string         `json:"project"`
		NodeID  int64          `json:"node_id"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	s.closeProjectNodeDeviceSessions(body.Project, body.NodeID)
	session, err := s.devices.Create(body.Kind, body.Config, body.Project, body.NodeID)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	detail := "Go device session connected"
	if session.Unsupported {
		detail = "Go device streaming is not implemented yet"
	}
	resp := gin.H{
		"session_id":  session.ID,
		"kind":        session.Kind,
		"project":     session.Project,
		"node_id":     session.NodeID,
		"width":       session.Width,
		"height":      session.Height,
		"unsupported": session.Unsupported,
		"detail":      detail,
	}
	if session.Device != nil {
		resp["stream_mode"] = "webrtc"
		resp["capture_url"] = "/api/devices/" + session.ID + "/capture"
		resp["input_url"] = "/api/devices/" + session.ID + "/input"
		resp["webrtc_url"] = "/api/webrtc/offer"
	}
	c.JSON(http.StatusOK, resp)
}

func (s *Server) disconnectDevice(c *gin.Context) {
	sessionID := c.Param("session_id")
	if s.deviceWebRTC != nil {
		s.deviceWebRTC.closeSession(sessionID)
	}
	deleted := s.devices.Delete(sessionID)
	c.JSON(http.StatusOK, gin.H{"ok": true, "deleted": deleted, "session_id": sessionID})
}

func (s *Server) closeProjectNodeDeviceSessions(project string, nodeID int64) {
	for _, sessionID := range s.devices.IDsByProjectNode(project, nodeID) {
		if s.deviceWebRTC != nil {
			s.deviceWebRTC.closeSession(sessionID)
		}
		s.devices.Delete(sessionID)
	}
}

func (s *Server) captureDevice(c *gin.Context) {
	session, ok := s.devices.Get(c.Param("session_id"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"detail": "device session not found", "session_id": c.Param("session_id")})
		return
	}
	if session.Device == nil {
		c.JSON(http.StatusNotImplemented, gin.H{"detail": "device capture is not implemented for this session", "session_id": session.ID})
		return
	}
	img, err := device.CaptureImage(c.Request.Context(), session.Device)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error(), "session_id": session.ID})
		return
	}
	if img == nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": "device returned empty capture", "session_id": session.ID})
		return
	}
	c.Header("Content-Type", "image/png")
	c.Header("Cache-Control", "no-store")
	if err := png.Encode(c.Writer, img); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error(), "session_id": session.ID})
		return
	}
}

func (s *Server) deviceInput(c *gin.Context) {
	session, ok := s.devices.Get(c.Param("session_id"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"detail": "device session not found", "session_id": c.Param("session_id")})
		return
	}
	if session.Device == nil {
		c.JSON(http.StatusNotImplemented, gin.H{"detail": "device input is not implemented for this session", "session_id": session.ID})
		return
	}
	var body deviceInputEvent
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error(), "session_id": session.ID})
		return
	}
	if err := dispatchDeviceInput(c.Request.Context(), session.Device, body); err != nil {
		status := http.StatusInternalServerError
		if err == errUnsupportedDeviceInput {
			status = http.StatusBadRequest
		}
		c.JSON(status, gin.H{"detail": err.Error(), "session_id": session.ID})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true, "session_id": session.ID})
}

type deviceInputEvent struct {
	Type   string `json:"t"`
	X      int    `json:"x"`
	Y      int    `json:"y"`
	Button string `json:"button"`
	DY     int    `json:"dy"`
	Name   string `json:"name"`
	Down   bool   `json:"down"`
	Text   string `json:"text"`
}

var errUnsupportedDeviceInput = &deviceInputError{message: "unsupported device input event"}

type deviceInputError struct {
	message string
}

func (e *deviceInputError) Error() string {
	return e.message
}

func dispatchDeviceInput(ctx context.Context, dev device.Device, evt deviceInputEvent) error {
	if dev == nil {
		return errUnsupportedDeviceInput
	}
	switch evt.Type {
	case "move":
		return dev.MouseMove(ctx, evt.X, evt.Y)
	case "down":
		return dev.MouseDown(ctx, inputButton(evt.Button), evt.X, evt.Y)
	case "up":
		return dev.MouseUp(ctx, inputButton(evt.Button), evt.X, evt.Y)
	case "scroll":
		if err := dev.MouseMove(ctx, evt.X, evt.Y); err != nil {
			return err
		}
		return dev.MouseWheel(ctx, evt.DY)
	case "key":
		if evt.Down {
			return dev.KeyDown(ctx, device.Key(evt.Name))
		}
		return dev.KeyUp(ctx, device.Key(evt.Name))
	case "text":
		return dev.TypeText(ctx, evt.Text)
	default:
		return errUnsupportedDeviceInput
	}
}

func inputButton(button string) device.Button {
	switch button {
	case string(device.ButtonMiddle):
		return device.ButtonMiddle
	case string(device.ButtonRight):
		return device.ButtonRight
	default:
		return device.ButtonLeft
	}
}
