package project

import (
	"bytes"
	"image"
	"image/color"
	"image/png"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestProjectSaveLoadFlowAndMeta(t *testing.T) {
	store := Store{root: t.TempDir()}
	p, err := store.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := p.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	if err := p.SaveFlow(map[string]any{"nodes": []any{map[string]any{"id": 1}}, "links": []any{}}); err != nil {
		t.Fatalf("SaveFlow() error = %v", err)
	}
	graph, err := p.LoadFlow()
	if err != nil {
		t.Fatalf("LoadFlow() error = %v", err)
	}
	nodes := graph["nodes"].([]any)
	if len(nodes) != 1 {
		t.Fatalf("len(nodes) = %d, want 1", len(nodes))
	}
	if err := p.SaveMeta(map[string]any{"name": "demo"}); err != nil {
		t.Fatalf("SaveMeta() error = %v", err)
	}
	meta, err := p.LoadMeta()
	if err != nil {
		t.Fatalf("LoadMeta() error = %v", err)
	}
	if meta["name"] != "demo" {
		t.Fatalf("meta name = %v, want demo", meta["name"])
	}
}

func TestStoreListMissingRoot(t *testing.T) {
	store := Store{root: t.TempDir() + "/missing"}
	projects, err := store.List()
	if err != nil {
		t.Fatalf("List() error = %v", err)
	}
	if len(projects) != 0 {
		t.Fatalf("len(projects) = %d, want 0", len(projects))
	}
}

func TestImagesAndResultsManagement(t *testing.T) {
	store := Store{root: t.TempDir()}
	p, err := store.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := p.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	name, err := p.SaveImage("../pic.png", strings.NewReader("png"))
	if err != nil {
		t.Fatalf("SaveImage() error = %v", err)
	}
	if name != "pic.png" {
		t.Fatalf("image name = %q, want pic.png", name)
	}
	renamed, err := p.RenameImage("pic.png", "renamed.png")
	if err != nil {
		t.Fatalf("RenameImage() error = %v", err)
	}
	if renamed != "renamed.png" {
		t.Fatalf("renamed = %q, want renamed.png", renamed)
	}
	images, err := p.ListImages()
	if err != nil {
		t.Fatalf("ListImages() error = %v", err)
	}
	if len(images) != 1 || images[0] != "renamed.png" {
		t.Fatalf("images = %#v", images)
	}
	var pngBuf bytes.Buffer
	img := image.NewRGBA(image.Rect(0, 0, 2, 1))
	img.SetRGBA(0, 0, color.RGBA{R: 255, A: 255})
	img.SetRGBA(1, 0, color.RGBA{G: 255, A: 255})
	if err := png.Encode(&pngBuf, img); err != nil {
		t.Fatalf("png encode error = %v", err)
	}
	if _, err := p.SaveImage("real.png", &pngBuf); err != nil {
		t.Fatalf("SaveImage(real) error = %v", err)
	}
	loaded, err := p.LoadImage("real.png")
	if err != nil {
		t.Fatalf("LoadImage() error = %v", err)
	}
	if loaded.Bounds().Dx() != 2 || loaded.Bounds().Dy() != 1 {
		t.Fatalf("loaded bounds = %v", loaded.Bounds())
	}

	runPath := filepath.Join(p.path, resultsDir, "run-1")
	if err := os.MkdirAll(runPath, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(runPath, "report.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	path, err := p.ResultFile("run-1", "report.json")
	if err != nil {
		t.Fatalf("ResultFile() error = %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("result file stat error = %v", err)
	}
	deleted, err := p.ClearRuns()
	if err != nil {
		t.Fatalf("ClearRuns() error = %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}
}

func TestCreateRunAndSaveReport(t *testing.T) {
	store := Store{root: t.TempDir()}
	p, err := store.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := p.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	run, err := p.CreateRun()
	if err != nil {
		t.Fatalf("CreateRun() error = %v", err)
	}
	if err := p.SaveRunReport(run, map[string]any{"passed": true}); err != nil {
		t.Fatalf("SaveRunReport() error = %v", err)
	}
	if err := p.SaveRunFile(run, "report.junit.xml", []byte("<testsuite/>")); err != nil {
		t.Fatalf("SaveRunFile() error = %v", err)
	}
	path, err := p.ResultFile(run, "report.json")
	if err != nil {
		t.Fatalf("ResultFile() error = %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("report stat error = %v", err)
	}
	junitPath, err := p.ResultFile(run, "report.junit.xml")
	if err != nil {
		t.Fatalf("ResultFile(junit) error = %v", err)
	}
	if _, err := os.Stat(junitPath); err != nil {
		t.Fatalf("junit stat error = %v", err)
	}
	runs, err := p.ListRuns()
	if err != nil {
		t.Fatalf("ListRuns() error = %v", err)
	}
	if len(runs) != 1 || runs[0] != run {
		t.Fatalf("runs = %#v, want [%s]", runs, run)
	}
}

func TestSettingsRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "settings.json")
	t.Setenv("FLOW_SETTINGS_PATH", path)
	if err := SaveSettings(map[string]any{"theme": "dark"}); err != nil {
		t.Fatalf("SaveSettings() error = %v", err)
	}
	settings, err := LoadSettings()
	if err != nil {
		t.Fatalf("LoadSettings() error = %v", err)
	}
	if settings["theme"] != "dark" {
		t.Fatalf("theme = %#v, want dark", settings["theme"])
	}
}

func TestAISessionsRoundTrip(t *testing.T) {
	store := Store{root: t.TempDir()}
	p, err := store.Project("demo")
	if err != nil {
		t.Fatalf("Project() error = %v", err)
	}
	if err := p.Ensure(); err != nil {
		t.Fatalf("Ensure() error = %v", err)
	}
	session, err := p.CreateAISession("First")
	if err != nil {
		t.Fatalf("CreateAISession() error = %v", err)
	}
	id := session["id"].(string)
	saved, err := p.SaveAISession(id, map[string]any{
		"title":     "Updated",
		"messages":  []any{map[string]any{"role": "user", "content": "hi"}},
		"documents": "bad",
	})
	if err != nil {
		t.Fatalf("SaveAISession() error = %v", err)
	}
	if saved["title"] != "Updated" {
		t.Fatalf("title = %#v", saved["title"])
	}
	if len(saved["documents"].([]any)) != 0 {
		t.Fatalf("documents should be sanitized: %#v", saved["documents"])
	}
	loaded, err := p.LoadAISession(id)
	if err != nil {
		t.Fatalf("LoadAISession() error = %v", err)
	}
	if loaded["title"] != "Updated" {
		t.Fatalf("loaded title = %#v", loaded["title"])
	}
	list, err := p.ListAISessions()
	if err != nil {
		t.Fatalf("ListAISessions() error = %v", err)
	}
	if len(list) != 1 || list[0]["id"] != id {
		t.Fatalf("sessions = %#v", list)
	}
	deleted, err := p.ClearAISessions()
	if err != nil {
		t.Fatalf("ClearAISessions() error = %v", err)
	}
	if deleted != 1 {
		t.Fatalf("deleted = %d, want 1", deleted)
	}
}
