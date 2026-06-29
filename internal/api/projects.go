package api

import (
	"errors"
	"net/http"
	"os"

	"flow-test-go/internal/project"

	"github.com/gin-gonic/gin"
)

func (s *Server) listProjects(c *gin.Context) {
	projects, err := s.projects.List()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"projects": projects})
}

func (s *Server) createProject(c *gin.Context) {
	var body struct {
		Name string `json:"name"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	p, err := s.projects.Project(body.Name)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if p.Exists() {
		c.JSON(http.StatusConflict, gin.H{"detail": "工程已存在"})
		return
	}
	if err := p.Ensure(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"name": p.Name})
}

func (s *Server) deleteProject(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	if err := p.Delete(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) getFlow(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	graph, err := p.LoadFlow()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"graph": graph})
}

func (s *Server) putFlow(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	var body struct {
		Graph map[string]any `json:"graph"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if body.Graph == nil {
		body.Graph = map[string]any{"nodes": []any{}, "links": []any{}}
	}
	if err := p.SaveFlow(body.Graph); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) getMeta(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	meta, err := p.LoadMeta()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"meta": meta})
}

func (s *Server) putMeta(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	var body struct {
		Meta map[string]any `json:"meta"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if body.Meta == nil {
		body.Meta = map[string]any{}
	}
	if err := p.SaveMeta(body.Meta); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) listImages(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	images, err := p.ListImages()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"images": images})
}

func (s *Server) getImage(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	path, err := p.ImagePath(c.Param("img"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
		c.JSON(http.StatusNotFound, gin.H{"detail": "图片不存在"})
		return
	}
	c.File(path)
}

func (s *Server) uploadImage(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	file, err := c.FormFile("file")
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	src, err := file.Open()
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	defer src.Close()
	name, err := p.SaveImage(file.Filename, src)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"name": name})
}

func (s *Server) renameImage(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	var body struct {
		Name string `json:"name"`
	}
	if err := c.ShouldBindJSON(&body); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	name, err := p.RenameImage(c.Param("img"), body.Name)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"name": name})
}

func (s *Server) listResults(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	runs, err := p.ListRuns()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"runs": runs})
}

func (s *Server) clearResults(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	deleted, err := p.ClearRuns()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"deleted": deleted})
}

func (s *Server) deleteResult(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	if err := p.DeleteRun(c.Param("run")); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			c.JSON(http.StatusNotFound, gin.H{"detail": "结果不存在"})
			return
		}
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) getResultFile(c *gin.Context) {
	p, ok := s.requireProject(c)
	if !ok {
		return
	}
	path, err := p.ResultFile(c.Param("run"), c.Param("file"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return
	}
	if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
		c.JSON(http.StatusNotFound, gin.H{"detail": "结果文件不存在"})
		return
	}
	c.File(path)
}

func (s *Server) requireProject(c *gin.Context) (*project.Project, bool) {
	p, err := s.projects.Project(c.Param("name"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"detail": err.Error()})
		return nil, false
	}
	if !p.Exists() {
		c.JSON(http.StatusNotFound, gin.H{"detail": "工程不存在"})
		return nil, false
	}
	return p, true
}
