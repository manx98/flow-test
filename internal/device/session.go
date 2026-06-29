package device

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"sync"
	"time"
)

type Session struct {
	ID          string         `json:"session_id"`
	Kind        string         `json:"kind"`
	Config      map[string]any `json:"-"`
	Project     string         `json:"project,omitempty"`
	NodeID      int64          `json:"node_id,omitempty"`
	Width       int            `json:"width"`
	Height      int            `json:"height"`
	Unsupported bool           `json:"unsupported,omitempty"`
	CreatedAt   time.Time      `json:"created_at"`
	Device      Device         `json:"-"`
}

type SessionStore struct {
	mu       sync.RWMutex
	sessions map[string]*Session
}

func NewSessionStore() *SessionStore {
	return &SessionStore{sessions: map[string]*Session{}}
}

func (s *SessionStore) Create(kind string, config map[string]any, project string, nodeID int64) (*Session, error) {
	if kind == "" {
		return nil, fmt.Errorf("device kind is required")
	}
	if config == nil {
		config = map[string]any{}
	}
	width := intFromConfig(config, "width", 1280)
	height := intFromConfig(config, "height", 720)
	dev, err := NewConfiguredDevice(kind, config)
	if err != nil {
		return nil, err
	}
	if sized, ok := dev.(SizedDevice); ok {
		if w, h := sized.Size(); w > 0 && h > 0 {
			width, height = w, h
		}
	}
	unsupported := dev == nil
	session := &Session{
		ID:          newSessionID(),
		Kind:        kind,
		Config:      copyConfig(config),
		Project:     project,
		NodeID:      nodeID,
		Width:       width,
		Height:      height,
		Unsupported: unsupported,
		CreatedAt:   time.Now().UTC(),
		Device:      dev,
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sessions[session.ID] = session
	return session, nil
}

func (s *SessionStore) Get(id string) (*Session, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	session, ok := s.sessions[id]
	return session, ok
}

func (s *SessionStore) Delete(id string) bool {
	s.mu.Lock()
	session, ok := s.sessions[id]
	if !ok {
		s.mu.Unlock()
		return false
	}
	delete(s.sessions, id)
	s.mu.Unlock()
	closeSessionDevice(session)
	return true
}

func (s *SessionStore) IDsByProjectNode(project string, nodeID int64) []string {
	if project == "" || nodeID == 0 {
		return nil
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	var ids []string
	for _, session := range s.sessions {
		if session.Project == project && session.NodeID == nodeID {
			ids = append(ids, session.ID)
		}
	}
	return ids
}

func closeSessionDevice(session *Session) {
	if session != nil && session.Device != nil {
		_ = session.Device.Close()
		session.Device = nil
	}
}

func (s *SessionStore) Ref(id string) (Ref, bool) {
	session, ok := s.Get(id)
	if !ok {
		return Ref{}, false
	}
	ref := NewUnsupportedRef(session.Kind, publicConfig(session.Config), session.Width, session.Height)
	ref.Device = session.Device
	ref.Unsupported = session.Unsupported
	return ref, true
}

func (s *SessionStore) RefByProjectNode(project string, nodeID int64) (Ref, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, session := range s.sessions {
		if session.Project == project && session.NodeID == nodeID {
			ref := NewUnsupportedRef(session.Kind, publicConfig(session.Config), session.Width, session.Height)
			ref.Device = session.Device
			ref.Unsupported = session.Unsupported
			return ref, true
		}
	}
	return Ref{}, false
}

func copyConfig(config map[string]any) map[string]any {
	out := make(map[string]any, len(config))
	for key, value := range config {
		out[key] = value
	}
	return out
}

func publicConfig(config map[string]any) map[string]any {
	out := make(map[string]any, len(config))
	for key, value := range config {
		if key == "password" {
			continue
		}
		out[key] = value
	}
	return out
}

func intFromConfig(config map[string]any, key string, fallback int) int {
	switch value := config[key].(type) {
	case int:
		if value > 0 {
			return value
		}
	case int64:
		if value > 0 {
			return int(value)
		}
	case float64:
		if value > 0 {
			return int(value)
		}
	case jsonNumber:
		if n, err := value.Int64(); err == nil && n > 0 {
			return int(n)
		}
	}
	return fallback
}

type jsonNumber interface {
	Int64() (int64, error)
}

func newSessionID() string {
	var buf [8]byte
	if _, err := rand.Read(buf[:]); err == nil {
		return "dev-" + hex.EncodeToString(buf[:])
	}
	return fmt.Sprintf("dev-%d", time.Now().UnixNano())
}
