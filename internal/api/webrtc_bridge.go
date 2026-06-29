package api

import (
	"bytes"
	"context"
	"encoding/json"
	"image"
	"image/jpeg"
	"net/http"
	"sync"
	"time"

	"flow-test-go/internal/device"

	"github.com/gin-gonic/gin"
	"github.com/pion/mediadevices"
	"github.com/pion/mediadevices/pkg/codec/vpx"
	"github.com/pion/webrtc/v4"
)

type deviceWebRTCManager struct {
	mu    sync.Mutex
	conns map[string]map[*webrtc.PeerConnection]*deviceWebRTCConn
}

type deviceWebRTCConn struct {
	pc    *webrtc.PeerConnection
	close func()
}

func newDeviceWebRTCManager() *deviceWebRTCManager {
	return &deviceWebRTCManager{conns: make(map[string]map[*webrtc.PeerConnection]*deviceWebRTCConn)}
}

func (m *deviceWebRTCManager) add(sessionID string, pc *webrtc.PeerConnection, close func()) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.conns[sessionID] == nil {
		m.conns[sessionID] = make(map[*webrtc.PeerConnection]*deviceWebRTCConn)
	}
	m.conns[sessionID][pc] = &deviceWebRTCConn{pc: pc, close: close}
}

func (m *deviceWebRTCManager) remove(sessionID string, pc *webrtc.PeerConnection) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.conns[sessionID] == nil {
		return
	}
	delete(m.conns[sessionID], pc)
	if len(m.conns[sessionID]) == 0 {
		delete(m.conns, sessionID)
	}
}

func (m *deviceWebRTCManager) closeSession(sessionID string) {
	m.mu.Lock()
	conns := m.conns[sessionID]
	delete(m.conns, sessionID)
	m.mu.Unlock()

	for pc, conn := range conns {
		if conn != nil && conn.close != nil {
			conn.close()
			continue
		}
		if pc != nil {
			_ = pc.Close()
		}
	}
}

func (s *Server) deviceStreamOffer(c *gin.Context) {
	var body struct {
		SessionID string `json:"session_id"`
		SDP       string `json:"sdp"`
		Type      string `json:"type"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	session, ok := s.devices.Get(body.SessionID)
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"detail": "device session not found", "session_id": body.SessionID})
		return
	}
	if session.Device == nil {
		c.JSON(http.StatusNotImplemented, gin.H{
			"detail":     "device streaming is not implemented for this session",
			"session_id": body.SessionID,
		})
		return
	}
	if body.SDP == "" {
		c.JSON(http.StatusBadRequest, gin.H{"detail": "missing WebRTC offer SDP", "session_id": session.ID})
		return
	}

	mediaEngine := &webrtc.MediaEngine{}
	codecSelector, err := newDeviceVideoCodecSelector()
	if err != nil {
		c.JSON(http.StatusOK, captureFallback(session.ID, err.Error()))
		return
	}
	codecSelector.Populate(mediaEngine)
	api := webrtc.NewAPI(webrtc.WithMediaEngine(mediaEngine))
	pc, err := api.NewPeerConnection(webrtc.Configuration{})
	if err != nil {
		c.JSON(http.StatusOK, captureFallback(session.ID, err.Error()))
		return
	}

	ctx, cancel := context.WithCancel(context.Background())
	videoSource := newDeviceVideoSource(ctx, session.ID, session.Device)
	videoTrack := mediadevices.NewVideoTrack(videoSource, codecSelector)
	sender, err := pc.AddTrack(videoTrack)
	if err != nil {
		cancel()
		_ = videoSource.Close()
		_ = pc.Close()
		s.deviceWebRTC.remove(session.ID, pc)
		c.JSON(http.StatusOK, captureFallback(session.ID, err.Error()))
		return
	}
	go discardSenderRTCP(sender)

	var cleanupOnce sync.Once
	cleanup := func() {
		cleanupOnce.Do(func() {
			cancel()
			_ = pc.RemoveTrack(sender)
			_ = videoTrack.Close()
			_ = pc.Close()
			s.deviceWebRTC.remove(session.ID, pc)
		})
	}
	s.deviceWebRTC.add(session.ID, pc, cleanup)
	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		if state == webrtc.PeerConnectionStateClosed ||
			state == webrtc.PeerConnectionStateFailed ||
			state == webrtc.PeerConnectionStateDisconnected {
			cleanup()
		}
	})
	pc.OnDataChannel(func(dc *webrtc.DataChannel) {
		dc.OnClose(cleanup)
		dc.OnMessage(func(msg webrtc.DataChannelMessage) {
			defer func() { _ = recover() }()
			var evt deviceInputEvent
			if err := json.Unmarshal(msg.Data, &evt); err != nil {
				return
			}
			_ = dispatchDeviceInput(ctx, session.Device, evt)
		})
	})

	if err := pc.SetRemoteDescription(webrtc.SessionDescription{
		Type: webrtc.SDPTypeOffer,
		SDP:  body.SDP,
	}); err != nil {
		cleanup()
		_ = pc.Close()
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error(), "session_id": session.ID})
		return
	}
	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		cleanup()
		_ = pc.Close()
		c.JSON(http.StatusOK, captureFallback(session.ID, err.Error()))
		return
	}
	gatherDone := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(answer); err != nil {
		cleanup()
		_ = pc.Close()
		c.JSON(http.StatusOK, captureFallback(session.ID, err.Error()))
		return
	}
	<-gatherDone
	local := pc.LocalDescription()
	if local == nil {
		cleanup()
		_ = pc.Close()
		c.JSON(http.StatusOK, captureFallback(session.ID, "empty WebRTC answer"))
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"type":       local.Type.String(),
		"sdp":        local.SDP,
		"mode":       "webrtc-video",
		"session_id": session.ID,
	})
}

type deviceVideoSource struct {
	ctx   context.Context
	id    string
	dev   device.Device
	frame *image.RGBA
	once  sync.Once
}

func newDeviceVideoSource(ctx context.Context, sessionID string, dev device.Device) *deviceVideoSource {
	return &deviceVideoSource{
		ctx: ctx,
		id:  "device-" + sessionID,
		dev: dev,
	}
}

func (s *deviceVideoSource) ID() string {
	return s.id
}

func (s *deviceVideoSource) Close() error {
	return nil
}

func (s *deviceVideoSource) Read() (image.Image, func(), error) {
	if err := s.dev.Capture(s.ctx, &s.frame); err != nil {
		return nil, nil, err
	}
	return s.frame, func() {}, nil
}

func newDeviceVideoCodecSelector() (*mediadevices.CodecSelector, error) {
	vp8Params, err := vpx.NewVP8Params()
	if err != nil {
		return nil, err
	}
	vp8Params.BitRate = 1600_000
	vp8Params.KeyFrameInterval = 45
	vp8Params.RateControlEndUsage = vpx.RateControlCBR
	vp8Params.LagInFrames = 0
	return mediadevices.NewCodecSelector(
		mediadevices.WithVideoEncoders(&vp8Params),
	), nil
}

func discardSenderRTCP(sender *webrtc.RTPSender) {
	buf := make([]byte, 1500)
	for {
		if _, _, err := sender.Read(buf); err != nil {
			return
		}
	}
}

func streamDeviceFrames(ctx context.Context, dev device.Device, dc *webrtc.DataChannel) {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if dc.ReadyState() != webrtc.DataChannelStateOpen {
				return
			}
			if dc.BufferedAmount() > 4*1024*1024 {
				continue
			}
			img, err := device.CaptureImage(ctx, dev)
			if err != nil || img == nil {
				continue
			}
			var buf bytes.Buffer
			if err := jpeg.Encode(&buf, img, &jpeg.Options{Quality: 80}); err != nil {
				continue
			}
			if err := dc.Send(buf.Bytes()); err != nil {
				return
			}
		}
	}
}

func captureFallback(sessionID string, detail string) gin.H {
	return gin.H{
		"type":        "capture",
		"mode":        "capture",
		"session_id":  sessionID,
		"capture_url": "/api/devices/" + sessionID + "/capture",
		"input_url":   "/api/devices/" + sessionID + "/input",
		"detail":      detail,
	}
}
