package main

import (
	"log"
	"os"

	"flow-test-go/internal/api"
)

func main() {
	addr := os.Getenv("FLOW_GO_ADDR")
	if addr == "" {
		addr = ":8000"
	}
	server, err := api.NewServer(api.Config{
		RepoRoot: envOr("FLOW_REPO_ROOT", "."),
	})
	if err != nil {
		log.Fatal(err)
	}
	if err := server.Run(addr); err != nil {
		log.Fatal(err)
	}
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
