package api

import (
	"context"
	"encoding/json"
	"errors"
	"image"
	"net/http"
	"os"
	"sync"

	"flow-test-go/internal/aibuilder"
	"flow-test-go/internal/flow"
	"flow-test-go/internal/nodes"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

var runUpgrader = websocket.Upgrader{
	CheckOrigin: func(*http.Request) bool { return true },
}

func (s *Server) runProject(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	raw, err := graphFromRunRequest(c, p)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	graph, err := decodeGraph(raw)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	runName, saveErr := p.CreateRun()
	result := s.runGraphForProject(context.Background(), c.Param("name"), p, runName, graph)
	if saveErr == nil {
		saveErr = saveRunArtifacts(p, c.Param("name"), runName, result.Report)
	}
	body := gin.H{"ok": result.Err == nil, "events": result.Events, "report": result.Report}
	if result.Err != nil {
		body["detail"] = result.Err.Error()
	}
	if saveErr == nil {
		body["run"] = runName
		addRunURLs(body, c.Param("name"), runName)
	} else {
		body["save_error"] = saveErr.Error()
	}
	c.JSON(http.StatusOK, body)
}

type runResult struct {
	Events []flow.Event
	Report *flow.Report
	Err    error
}

type liveRunSink struct {
	events    []flow.Event
	writeJSON func(any) bool
}

func (s *liveRunSink) Emit(event flow.Event) {
	s.events = append(s.events, event)
	if event.Type != "run" {
		s.writeJSON(event)
	}
}

func runGraph(ctx context.Context, graph flow.Graph) runResult {
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, nodes.NewRegistry(), sink)
	err := runner.Run(ctx)
	report := flow.ReportFromEvents(sink.Events, err)
	return runResult{Events: sink.Events, Report: report, Err: err}
}

type projectRuntime interface {
	LoadImage(string) (image.Image, error)
	SaveRunFile(string, string, []byte) error
}

func (s *Server) runGraphForProject(ctx context.Context, projectName string, p projectRuntime, runName string, graph flow.Graph) runResult {
	sink := &flow.CollectingSink{}
	runner := flow.NewRunner(graph, nodes.NewRegistry(), sink)
	runner.DeviceResolver = func(node *flow.Node) (any, bool) {
		return s.devices.RefByProjectNode(projectName, node.ID)
	}
	runner.ImageResolver = func(name string) (any, bool, error) {
		img, err := p.LoadImage(name)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return nil, false, nil
			}
			return nil, false, err
		}
		return img, true, nil
	}
	if runName != "" {
		runner.ShotSink = func(nodeID int64, img image.Image, rects []image.Rectangle) (string, error) {
			name, err := saveNodeShot(p, runName, nodeID, img, rects)
			if err != nil {
				return "", err
			}
			return "/api/projects/" + projectName + "/results/" + runName + "/" + name, nil
		}
	}
	err := runner.Run(ctx)
	report := flow.ReportFromEvents(sink.Events, err)
	return runResult{Events: sink.Events, Report: report, Err: err}
}

func (s *Server) runWebSocket(c *gin.Context) {
	projectName := c.Param("name")
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	conn, err := runUpgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	var cancel context.CancelFunc
	var writeMu sync.Mutex
	writeJSON := func(value any) bool {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteJSON(value) == nil
	}
	for {
		var msg struct {
			Cmd   string         `json:"cmd"`
			Graph map[string]any `json:"graph"`
		}
		if err := conn.ReadJSON(&msg); err != nil {
			if cancel != nil {
				cancel()
			}
			return
		}
		switch msg.Cmd {
		case "stop":
			if cancel != nil {
				cancel()
			}
		case "run":
			if cancel != nil {
				cancel()
			}
			raw := msg.Graph
			if raw == nil {
				raw, err = p.LoadFlow()
				if err != nil {
					writeJSON(gin.H{"type": "run", "status": "error", "error": err.Error()})
					continue
				}
			}
			graph, err := decodeGraph(raw)
			if err != nil {
				writeJSON(gin.H{"type": "run", "status": "error", "error": err.Error()})
				continue
			}
			runName, err := p.CreateRun()
			if err != nil {
				writeJSON(gin.H{"type": "run", "status": "error", "error": err.Error()})
				continue
			}
			ctx, stop := context.WithCancel(context.Background())
			cancel = stop
			go func() {
				defer stop()
				s.runGraphWebSocket(ctx, projectName, p, runName, graph, writeJSON)
			}()
		}
	}
}

func (s *Server) runGraphWebSocket(ctx context.Context, projectName string, p interface {
	CreateRun() (string, error)
	LoadImage(string) (image.Image, error)
	SaveRunReport(string, any) error
	SaveRunFile(string, string, []byte) error
}, runName string, graph flow.Graph, writeJSON func(any) bool) {
	if !writeJSON(gin.H{"type": "run", "status": "start"}) {
		return
	}
	result := s.runGraphForProjectLive(ctx, projectName, p, runName, graph, writeJSON)
	saveErr := saveRunArtifacts(p, projectName, runName, result.Report)
	if result.Err != nil {
		writeJSON(gin.H{"type": "run", "status": "error", "error": result.Err.Error()})
		return
	}
	done := gin.H{"type": "run", "status": "done", "report": result.Report}
	if saveErr == nil {
		done["run"] = runName
		addRunURLs(done, projectName, runName)
	} else {
		done["save_error"] = saveErr.Error()
	}
	writeJSON(done)
}

func (s *Server) runGraphForProjectLive(ctx context.Context, projectName string, p projectRuntime, runName string, graph flow.Graph, writeJSON func(any) bool) runResult {
	sink := &liveRunSink{writeJSON: writeJSON}
	runner := flow.NewRunner(graph, nodes.NewRegistry(), sink)
	runner.DeviceResolver = func(node *flow.Node) (any, bool) {
		return s.devices.RefByProjectNode(projectName, node.ID)
	}
	runner.ImageResolver = func(name string) (any, bool, error) {
		img, err := p.LoadImage(name)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				return nil, false, nil
			}
			return nil, false, err
		}
		return img, true, nil
	}
	if runName != "" {
		runner.ShotSink = func(nodeID int64, img image.Image, rects []image.Rectangle) (string, error) {
			name, err := saveNodeShot(p, runName, nodeID, img, rects)
			if err != nil {
				return "", err
			}
			return "/api/projects/" + projectName + "/results/" + runName + "/" + name, nil
		}
	}
	err := runner.Run(ctx)
	report := flow.ReportFromEvents(sink.events, err)
	return runResult{Events: sink.events, Report: report, Err: err}
}

type runArtifactWriter interface {
	SaveRunReport(string, any) error
	SaveRunFile(string, string, []byte) error
}

func saveRunArtifacts(p runArtifactWriter, projectName string, runName string, report *flow.Report) error {
	if err := p.SaveRunReport(runName, report); err != nil {
		return err
	}
	return p.SaveRunFile(runName, "report.junit.xml", []byte(report.ToJUnit("flow:"+projectName)))
}

func addRunURLs(out gin.H, projectName string, runName string) {
	base := "/api/projects/" + projectName + "/results/" + runName
	out["report_url"] = base + "/report.json"
	out["junit_url"] = base + "/report.junit.xml"
}

func (s *Server) aiBuildWebSocket(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	conn, err := runUpgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	for {
		var msg struct {
			Type         string           `json:"type"`
			Message      string           `json:"message"`
			History      []map[string]any `json:"history"`
			Documents    []map[string]any `json:"documents"`
			CurrentGraph map[string]any   `json:"current_graph"`
			FormValues   map[string]any   `json:"form_values"`
		}
		if err := conn.ReadJSON(&msg); err != nil {
			return
		}
		switch msg.Type {
		case "stop":
			_ = conn.WriteJSON(gin.H{"type": "done", "status": "stopped", "message": "AI Builder stopped"})
			return
		case "init":
			_ = conn.WriteJSON(gin.H{
				"type":                   "status",
				"status":                 "running",
				"message":                "Go AI Builder websocket connected",
				"tools":                  aibuilder.ToolMetadata(),
				"tool_calling_supported": true,
			})
			state := map[string]any{
				"message":       msg.Message,
				"history":       mapsToAnySlice(msg.History),
				"documents":     mapsToAnySlice(msg.Documents),
				"current_graph": msg.CurrentGraph,
				"form_values":   msg.FormValues,
			}
			cfg := s.aiBuilderConfig()
			if cfg.ModelReady() {
				if s.runAIBuilderToolLoop(c.Request.Context(), conn, p, c.Param("session_id"), cfg, state) {
					return
				}
			}
			s.runAIBuilderFallback(c.Request.Context(), conn, p, c.Param("session_id"), msg.Message, state)
			return
		default:
			_ = conn.WriteJSON(gin.H{
				"type":    "error",
				"message": "AI Builder websocket expected init or stop",
			})
		}
	}
}

func (s *Server) runAIBuilderToolLoop(ctx context.Context, conn *websocket.Conn, p interface {
	LoadAISession(string) (map[string]any, error)
	SaveAISession(string, map[string]any) (map[string]any, error)
}, sessionID string, cfg aibuilder.Config, state map[string]any) bool {
	session, _ := p.LoadAISession(sessionID)
	messages := aibuilder.BuildDirectBuildMessages(state, docsFromState(state), session)
	client, err := aibuilder.NewEinoModelClient(cfg)
	if err != nil {
		_ = conn.WriteJSON(gin.H{"type": "error", "message": err.Error()})
		_ = conn.WriteJSON(gin.H{"type": "done", "status": "failed", "message": err.Error()})
		return true
	}
	result, err := aibuilder.RunToolLoop(ctx, client, messages, cfg.MaxToolCalls, aibuilder.ToolLoopCallbacks{
		OnMessage: func(_ context.Context, text string) error {
			return conn.WriteJSON(gin.H{"type": "message", "content": text})
		},
		OnDelta: func(_ context.Context, text string) error {
			return conn.WriteJSON(gin.H{"type": "delta", "text": text})
		},
		SendToolCall: func(_ context.Context, event aibuilder.ToolCallEvent) error {
			return conn.WriteJSON(gin.H{
				"type": "tool_call",
				"id":   event.ID,
				"tool": event.Tool,
				"risk": event.Risk,
				"args": event.Args,
			})
		},
		WaitToolResult: func(_ context.Context, id string) (aibuilder.ToolResult, error) {
			for {
				var msg struct {
					Type       string         `json:"type"`
					ToolCallID string         `json:"tool_call_id"`
					Tool       string         `json:"tool"`
					Status     string         `json:"status"`
					Result     map[string]any `json:"result"`
					Permission map[string]any `json:"permission"`
					Log        map[string]any `json:"log"`
					Reason     string         `json:"reason"`
				}
				if err := conn.ReadJSON(&msg); err != nil {
					return aibuilder.ToolResult{}, err
				}
				if msg.Type == "stop" {
					return aibuilder.ToolResult{}, aiBuilderStoppedError{reason: msg.Reason}
				}
				if msg.Type != "tool_result" || msg.ToolCallID != id {
					continue
				}
				return aibuilder.ToolResult{
					ToolCallID: msg.ToolCallID,
					Tool:       msg.Tool,
					Status:     msg.Status,
					Permission: msg.Permission,
					Result:     msg.Result,
					Log:        msg.Log,
				}, nil
			}
		},
	})
	if err != nil {
		var stopped aiBuilderStoppedError
		if errors.As(err, &stopped) {
			_ = conn.WriteJSON(gin.H{"type": "done", "status": "stopped", "message": "AI Builder stopped", "reason": stopped.reason})
			return true
		}
		if result.ToolCalls == 0 {
			return false
		}
		_ = conn.WriteJSON(gin.H{"type": "error", "message": err.Error()})
		_ = conn.WriteJSON(gin.H{"type": "done", "status": "failed", "message": err.Error()})
		return true
	}
	_ = saveToolLoopStateToAISession(p, sessionID, state, result)
	_ = conn.WriteJSON(gin.H{
		"type":       "done",
		"status":     "completed",
		"message":    "Go AI Builder completed",
		"summary":    result.Summary,
		"tool_calls": result.ToolCalls,
	})
	return true
}

type aiBuilderStoppedError struct {
	reason string
}

func (e aiBuilderStoppedError) Error() string {
	if e.reason == "" {
		return "AI Builder stopped"
	}
	return "AI Builder stopped: " + e.reason
}

func (s *Server) runAIBuilderFallback(ctx context.Context, conn *websocket.Conn, p interface {
	LoadAISession(string) (map[string]any, error)
	SaveAISession(string, map[string]any) (map[string]any, error)
}, sessionID string, message string, state map[string]any) {
	builder := s.newAIBuilder()
	draft, err := builder.BuildDraft(ctx, message)
	if err != nil {
		_ = conn.WriteJSON(gin.H{"type": "error", "message": err.Error()})
		_ = conn.WriteJSON(gin.H{"type": "done", "status": "failed", "message": err.Error()})
		return
	}
	_ = saveDraftToAISession(p, sessionID, draft, state)
	status := aiDraftStatusPayload(draft)
	_ = conn.WriteJSON(gin.H{"type": "message", "content": status["content"], "metadata": status["metadata"]})
	_ = conn.WriteJSON(gin.H{"type": "draft", "draft": draft})
	_ = conn.WriteJSON(gin.H{"type": "usage", "usage": gin.H{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated": true}})
	_ = conn.WriteJSON(gin.H{
		"type":     "done",
		"status":   "completed",
		"message":  status["done_message"],
		"summary":  status["summary"],
		"metadata": status["metadata"],
	})
}

func decodeGraph(raw map[string]any) (flow.Graph, error) {
	data, err := json.Marshal(raw)
	if err != nil {
		return flow.Graph{}, err
	}
	var graph flow.Graph
	if err := json.Unmarshal(data, &graph); err != nil {
		return flow.Graph{}, err
	}
	return graph, nil
}

func graphFromRunRequest(c *gin.Context, p interface {
	LoadFlow() (map[string]any, error)
}) (map[string]any, error) {
	if c.Request.Body == nil || c.Request.ContentLength == 0 {
		return p.LoadFlow()
	}
	var body struct {
		Graph map[string]any `json:"graph"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		return nil, err
	}
	if body.Graph == nil {
		return p.LoadFlow()
	}
	return body.Graph, nil
}
