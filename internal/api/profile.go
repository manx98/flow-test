package api

import (
	"net/http"
	"net/http/pprof"
	"runtime"
	"runtime/debug"

	"github.com/gin-gonic/gin"
)

func (s *Server) registerProfileRoutes(r *gin.Engine) {
	r.GET("/debug/pprof/", gin.WrapF(pprof.Index))
	r.GET("/debug/pprof/cmdline", gin.WrapF(pprof.Cmdline))
	r.GET("/debug/pprof/profile", gin.WrapF(pprof.Profile))
	r.POST("/debug/pprof/symbol", gin.WrapF(pprof.Symbol))
	r.GET("/debug/pprof/symbol", gin.WrapF(pprof.Symbol))
	r.GET("/debug/pprof/trace", gin.WrapF(pprof.Trace))
	r.GET("/debug/pprof/:name", gin.WrapF(pprof.Index))

	r.GET("/api/debug/memstats", s.getMemStats)
	r.POST("/api/debug/gc", s.forceGC)
}

func (s *Server) getMemStats(c *gin.Context) {
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	c.JSON(http.StatusOK, gin.H{
		"alloc":           ms.Alloc,
		"total_alloc":     ms.TotalAlloc,
		"sys":             ms.Sys,
		"heap_alloc":      ms.HeapAlloc,
		"heap_sys":        ms.HeapSys,
		"heap_idle":       ms.HeapIdle,
		"heap_released":   ms.HeapReleased,
		"heap_inuse":      ms.HeapInuse,
		"heap_objects":    ms.HeapObjects,
		"stack_inuse":     ms.StackInuse,
		"mspan_inuse":     ms.MSpanInuse,
		"mcache_inuse":    ms.MCacheInuse,
		"next_gc":         ms.NextGC,
		"last_gc":         ms.LastGC,
		"num_gc":          ms.NumGC,
		"num_forced_gc":   ms.NumForcedGC,
		"gc_cpu_fraction": ms.GCCPUFraction,
		"goroutines":      runtime.NumGoroutine(),
	})
}

func (s *Server) forceGC(c *gin.Context) {
	debug.FreeOSMemory()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	c.JSON(http.StatusOK, gin.H{
		"ok":            true,
		"heap_alloc":    ms.HeapAlloc,
		"heap_released": ms.HeapReleased,
		"num_gc":        ms.NumGC,
		"goroutines":    runtime.NumGoroutine(),
	})
}
