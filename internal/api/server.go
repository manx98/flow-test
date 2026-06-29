package api

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"flow-test-go/internal/catalog"
	"flow-test-go/internal/device"
	"flow-test-go/internal/project"

	"github.com/gin-gonic/gin"
)

type Config struct {
	RepoRoot string
}

type Server struct {
	router       *gin.Engine
	projects     project.Store
	catalog      *catalog.Loader
	devices      *device.SessionStore
	deviceWebRTC *deviceWebRTCManager
	repoRoot     string
}

func NewServer(cfg Config) (*Server, error) {
	if cfg.RepoRoot == "" {
		cfg.RepoRoot = "."
	}
	repoRoot, err := filepath.Abs(cfg.RepoRoot)
	if err != nil {
		return nil, err
	}
	s := &Server{
		router:       gin.New(),
		projects:     project.NewStoreFromEnv(),
		catalog:      catalog.NewLoader(filepath.Join(repoRoot, "server", "flow", "graph_skills")),
		devices:      device.NewSessionStore(),
		deviceWebRTC: newDeviceWebRTCManager(),
		repoRoot:     repoRoot,
	}
	if gin.Mode() == gin.TestMode {
		s.router.Use(gin.Recovery())
	} else {
		s.router.Use(gin.Logger(), gin.Recovery())
	}
	s.routes()
	return s, nil
}

func (s *Server) Run(addr string) error {
	return s.router.Run(addr)
}

func (s *Server) routes() {
	r := s.router
	s.registerProfileRoutes(r)
	r.GET("/api/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true, "runtime": "go"})
	})
	r.GET("/api/settings", s.getSettings)
	r.PUT("/api/settings", s.putSettings)
	r.POST("/api/check", s.checkCode)
	r.POST("/api/complete", s.completeCode)
	r.POST("/api/devices/connect", s.connectDevice)
	r.GET("/api/devices/:session_id/capture", s.captureDevice)
	r.POST("/api/devices/:session_id/input", s.deviceInput)
	r.POST("/api/devices/:session_id/disconnect", s.disconnectDevice)
	r.POST("/api/webrtc/offer", s.deviceStreamOffer)
	r.GET("/api/nodes", s.getNodes)
	r.GET("/api/nodes/spec", s.getNodeSpec)
	r.GET("/api/projects", s.listProjects)
	r.POST("/api/projects", s.createProject)
	r.DELETE("/api/projects/:name", s.deleteProject)
	r.GET("/api/projects/:name/flow", s.getFlow)
	r.PUT("/api/projects/:name/flow", s.putFlow)
	r.GET("/api/projects/:name/meta", s.getMeta)
	r.PUT("/api/projects/:name/meta", s.putMeta)
	r.GET("/api/projects/:name/images", s.listImages)
	r.POST("/api/projects/:name/images", s.uploadImage)
	r.GET("/api/projects/:name/images/:img", s.getImage)
	r.POST("/api/projects/:name/images/:img/rename", s.renameImage)
	r.GET("/api/projects/:name/results", s.listResults)
	r.DELETE("/api/projects/:name/results", s.clearResults)
	r.GET("/api/projects/:name/results/:run/:file", s.getResultFile)
	r.DELETE("/api/projects/:name/results/:run", s.deleteResult)
	r.GET("/api/projects/:name/ai/sessions", s.listAISessions)
	r.POST("/api/projects/:name/ai/sessions", s.createAISession)
	r.GET("/api/projects/:name/ai/sessions/:session_id", s.getAISession)
	r.PUT("/api/projects/:name/ai/sessions/:session_id", s.putAISession)
	r.DELETE("/api/projects/:name/ai/sessions/:session_id", s.deleteAISession)
	r.DELETE("/api/projects/:name/ai/sessions", s.clearAISessions)
	r.POST("/api/projects/:name/ai/draft", s.aiDraft)
	r.POST("/api/projects/:name/ai/sessions/:session_id/draft/stream", s.aiDraftStream)
	r.POST("/api/projects/:name/run", s.runProject)
	r.GET("/ws/run/:name", s.runWebSocket)
	r.GET("/ws/ai-build/:name/:session_id", s.aiBuildWebSocket)

	webDist := filepath.Join(s.repoRoot, "web", "dist")
	r.StaticFS("/assets", gin.Dir(filepath.Join(webDist, "assets"), false))
	r.GET("/", func(c *gin.Context) {
		serveFrontendIndex(c, webDist)
	})
	r.NoRoute(func(c *gin.Context) {
		if isAPIOrWebSocketPath(c.Request.URL.Path) || !isFrontendMethod(c.Request.Method) {
			c.JSON(http.StatusNotFound, gin.H{"detail": "not found"})
			return
		}
		serveFrontendIndex(c, webDist)
	})
}

func serveFrontendIndex(c *gin.Context, webDist string) {
	index := filepath.Join(webDist, "index.html")
	if _, err := os.Stat(index); err != nil {
		c.JSON(http.StatusNotFound, gin.H{"detail": "frontend build not found"})
		return
	}
	c.File(index)
}

func isAPIOrWebSocketPath(path string) bool {
	return strings.HasPrefix(path, "/api/") ||
		strings.HasPrefix(path, "/ws/") ||
		strings.HasPrefix(path, "/debug/pprof")
}

func isFrontendMethod(method string) bool {
	return method == http.MethodGet || method == http.MethodHead
}
