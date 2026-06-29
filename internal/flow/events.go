package flow

type Event struct {
	Type    string         `json:"type"`
	ID      int64          `json:"id,omitempty"`
	Status  string         `json:"status,omitempty"`
	Info    string         `json:"info,omitempty"`
	Level   string         `json:"level,omitempty"`
	Message string         `json:"message,omitempty"`
	Text    string         `json:"text,omitempty"`
	URL     string         `json:"url,omitempty"`
	Report  map[string]any `json:"report,omitempty"`
}

type EventSink interface {
	Emit(Event)
}

type CollectingSink struct {
	Events []Event
}

func (s *CollectingSink) Emit(event Event) {
	s.Events = append(s.Events, event)
}
