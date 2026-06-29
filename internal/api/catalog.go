package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

func (s *Server) getNodes(c *gin.Context) {
	data, err := s.catalog.Load()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	c.JSON(http.StatusOK, data)
}

func (s *Server) getNodeSpec(c *gin.Context) {
	nodeType := c.Query("type")
	data, err := s.catalog.Load()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"detail": err.Error()})
		return
	}
	nodes, _ := data["nodes"].([]map[string]any)
	for _, node := range nodes {
		if node["type"] == nodeType {
			c.JSON(http.StatusOK, node)
			return
		}
	}
	c.JSON(http.StatusNotFound, gin.H{"detail": "node type not found"})
}
