package project

import (
	"encoding/json"
	"errors"
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	flowName      = "flow.json"
	metaName      = "project.json"
	imagesDir     = "images"
	resultsDir    = "results"
	aiSessionsDir = "ai_sessions"
)

type Store struct {
	root string
}

type Project struct {
	Name string
	path string
}

func NewStoreFromEnv() Store {
	root := os.Getenv("FLOW_WORKSPACE")
	if root == "" {
		home, _ := os.UserHomeDir()
		root = filepath.Join(home, ".flow-test", "projects")
	}
	return Store{root: root}
}

func LoadSettings() (map[string]any, error) {
	path := settingsPath()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	var settings map[string]any
	if err := json.Unmarshal(data, &settings); err != nil {
		return nil, err
	}
	return settings, nil
}

func SaveSettings(settings map[string]any) error {
	if settings == nil {
		settings = map[string]any{}
	}
	path := settingsPath()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(settings, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o644)
}

func settingsPath() string {
	if path := os.Getenv("FLOW_SETTINGS_PATH"); path != "" {
		return path
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".flow-test", "settings.json")
}

func (s Store) List() ([]string, error) {
	entries, err := os.ReadDir(s.root)
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			out = append(out, entry.Name())
		}
	}
	sort.Strings(out)
	return out, nil
}

func (s Store) Project(name string) (*Project, error) {
	safe, err := safeName(name)
	if err != nil {
		return nil, err
	}
	return &Project{Name: safe, path: filepath.Join(s.root, safe)}, nil
}

func (p *Project) Exists() bool {
	info, err := os.Stat(p.path)
	return err == nil && info.IsDir()
}

func (p *Project) Ensure() error {
	if err := os.MkdirAll(filepath.Join(p.path, imagesDir), 0o755); err != nil {
		return err
	}
	if _, err := os.Stat(p.flowPath()); errors.Is(err, os.ErrNotExist) {
		if err := p.SaveFlow(map[string]any{"nodes": []any{}, "links": []any{}}); err != nil {
			return err
		}
	}
	if _, err := os.Stat(p.metaPath()); errors.Is(err, os.ErrNotExist) {
		if err := p.SaveMeta(map[string]any{}); err != nil {
			return err
		}
	}
	return nil
}

func (p *Project) Delete() error {
	return os.RemoveAll(p.path)
}

func (p *Project) LoadFlow() (map[string]any, error) {
	return readJSONMap(p.flowPath(), map[string]any{"nodes": []any{}, "links": []any{}})
}

func (p *Project) SaveFlow(graph map[string]any) error {
	return writeJSONMap(p.flowPath(), graph)
}

func (p *Project) LoadMeta() (map[string]any, error) {
	return readJSONMap(p.metaPath(), map[string]any{})
}

func (p *Project) SaveMeta(meta map[string]any) error {
	return writeJSONMap(p.metaPath(), meta)
}

func (p *Project) ListImages() ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(p.path, imagesDir))
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		lower := strings.ToLower(name)
		if strings.HasSuffix(lower, ".png") || strings.HasSuffix(lower, ".jpg") ||
			strings.HasSuffix(lower, ".jpeg") || strings.HasSuffix(lower, ".bmp") {
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out, nil
}

func (p *Project) ImagePath(name string) (string, error) {
	safe, err := safeFileName(name)
	if err != nil {
		return "", err
	}
	return filepath.Join(p.path, imagesDir, safe), nil
}

func (p *Project) SaveImage(name string, r io.Reader) (string, error) {
	if name == "" {
		name = "image.png"
	}
	safe, err := safeFileName(name)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Join(p.path, imagesDir), 0o755); err != nil {
		return "", err
	}
	dest := filepath.Join(p.path, imagesDir, safe)
	out, err := os.Create(dest)
	if err != nil {
		return "", err
	}
	defer out.Close()
	if _, err := io.Copy(out, r); err != nil {
		return "", err
	}
	return safe, nil
}

func (p *Project) LoadImage(name string) (image.Image, error) {
	path, err := p.ImagePath(name)
	if err != nil {
		return nil, err
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	img, _, err := image.Decode(file)
	if err != nil {
		return nil, err
	}
	return img, nil
}

func (p *Project) RenameImage(oldName, newName string) (string, error) {
	oldSafe, err := safeFileName(oldName)
	if err != nil {
		return "", err
	}
	newSafe, err := safeFileName(newName)
	if err != nil {
		return "", err
	}
	oldPath := filepath.Join(p.path, imagesDir, oldSafe)
	newPath := filepath.Join(p.path, imagesDir, newSafe)
	if _, err := os.Stat(oldPath); err != nil {
		return "", err
	}
	if _, err := os.Stat(newPath); err == nil {
		return "", fmt.Errorf("target image already exists")
	} else if !errors.Is(err, os.ErrNotExist) {
		return "", err
	}
	if err := os.Rename(oldPath, newPath); err != nil {
		return "", err
	}
	return newSafe, nil
}

func (p *Project) ListRuns() ([]string, error) {
	entries, err := os.ReadDir(filepath.Join(p.path, resultsDir))
	if errors.Is(err, os.ErrNotExist) {
		return []string{}, nil
	}
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, entry := range entries {
		if entry.IsDir() {
			out = append(out, entry.Name())
		}
	}
	sort.Sort(sort.Reverse(sort.StringSlice(out)))
	return out, nil
}

func (p *Project) ResultFile(run, name string) (string, error) {
	safeRun, err := safeFileName(run)
	if err != nil {
		return "", err
	}
	safeName, err := safeFileName(name)
	if err != nil {
		return "", err
	}
	return filepath.Join(p.path, resultsDir, safeRun, safeName), nil
}

func (p *Project) CreateRun() (string, error) {
	name := time.Now().Format("20060102-150405.000")
	name = strings.ReplaceAll(name, ".", "-")
	path := filepath.Join(p.path, resultsDir, name)
	if err := os.MkdirAll(path, 0o755); err != nil {
		return "", err
	}
	return name, nil
}

func (p *Project) SaveRunReport(run string, report any) error {
	path, err := p.ResultFile(run, "report.json")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o644)
}

func (p *Project) SaveRunFile(run string, name string, data []byte) error {
	path, err := p.ResultFile(run, name)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func (p *Project) DeleteRun(run string) error {
	safe, err := safeFileName(run)
	if err != nil {
		return err
	}
	path := filepath.Join(p.path, resultsDir, safe)
	if _, err := os.Stat(path); err != nil {
		return err
	}
	return os.RemoveAll(path)
}

func (p *Project) ClearRuns() (int, error) {
	runs, err := p.ListRuns()
	if err != nil {
		return 0, err
	}
	for _, run := range runs {
		if err := p.DeleteRun(run); err != nil {
			return 0, err
		}
	}
	return len(runs), nil
}

func (p *Project) ListAISessions() ([]map[string]any, error) {
	entries, err := os.ReadDir(filepath.Join(p.path, aiSessionsDir))
	if errors.Is(err, os.ErrNotExist) {
		return []map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	sessions := []map[string]any{}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		data, err := readJSONMap(filepath.Join(p.path, aiSessionsDir, entry.Name()), map[string]any{})
		if err != nil {
			continue
		}
		id := strings.TrimSuffix(entry.Name(), ".json")
		sessions = append(sessions, map[string]any{
			"id":         stringOr(data["id"], id),
			"title":      stringOr(data["title"], ""),
			"created_at": numberOr(data["created_at"], 0),
			"updated_at": numberOr(data["updated_at"], 0),
		})
	}
	sort.SliceStable(sessions, func(i, j int) bool {
		return numberOr(sessions[i]["updated_at"], 0) > numberOr(sessions[j]["updated_at"], 0)
	})
	return sessions, nil
}

func (p *Project) CreateAISession(title string) (map[string]any, error) {
	id := fmt.Sprintf("%d", time.Now().UnixNano())
	if len(id) > 12 {
		id = id[len(id)-12:]
	}
	now := unixSeconds()
	session := map[string]any{
		"id":          id,
		"title":       stringOr(title, "AI 会话"),
		"created_at":  now,
		"updated_at":  now,
		"messages":    []any{},
		"documents":   []any{},
		"form_values": map[string]any{},
		"tool_permissions": map[string]any{
			"auto_approved_tools": []any{},
		},
		"build_state": defaultBuildState(),
	}
	return p.SaveAISession(id, session)
}

func (p *Project) LoadAISession(id string) (map[string]any, error) {
	path, err := p.aiSessionPath(id)
	if err != nil {
		return nil, err
	}
	if _, err := os.Stat(path); err != nil {
		return nil, err
	}
	return readJSONMap(path, map[string]any{})
}

func (p *Project) SaveAISession(id string, session map[string]any) (map[string]any, error) {
	safe, err := safeFileName(id)
	if err != nil {
		return nil, err
	}
	now := unixSeconds()
	if session == nil {
		session = map[string]any{}
	}
	session["id"] = safe
	session["updated_at"] = now
	if _, ok := session["created_at"]; !ok {
		session["created_at"] = now
	}
	clean := map[string]any{
		"id":               safe,
		"title":            stringOr(session["title"], "AI 会话"),
		"created_at":       numberOr(session["created_at"], now),
		"updated_at":       now,
		"messages":         listOrEmpty(session["messages"]),
		"documents":        listOrEmpty(session["documents"]),
		"form_values":      mapOrEmpty(session["form_values"]),
		"draft":            mapOrNil(session["draft"]),
		"tool_permissions": toolPermissionsOrDefault(session["tool_permissions"]),
		"build_state":      buildStateOrDefault(session["build_state"]),
	}
	path, err := p.aiSessionPath(safe)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	if err := writeJSONMap(path, clean); err != nil {
		return nil, err
	}
	return clean, nil
}

func (p *Project) DeleteAISession(id string) error {
	path, err := p.aiSessionPath(id)
	if err != nil {
		return err
	}
	if _, err := os.Stat(path); err != nil {
		return err
	}
	return os.Remove(path)
}

func (p *Project) ClearAISessions() (int, error) {
	sessions, err := p.ListAISessions()
	if err != nil {
		return 0, err
	}
	for _, session := range sessions {
		if err := p.DeleteAISession(fmt.Sprint(session["id"])); err != nil {
			return 0, err
		}
	}
	return len(sessions), nil
}

func (p *Project) flowPath() string {
	return filepath.Join(p.path, flowName)
}

func (p *Project) metaPath() string {
	return filepath.Join(p.path, metaName)
}

func (p *Project) aiSessionPath(id string) (string, error) {
	safe, err := safeFileName(id)
	if err != nil {
		return "", err
	}
	return filepath.Join(p.path, aiSessionsDir, safe+".json"), nil
}

func readJSONMap(path string, fallback map[string]any) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return fallback, nil
	}
	if err != nil {
		return nil, err
	}
	var out map[string]any
	if err := json.Unmarshal(data, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func writeJSONMap(path string, value map[string]any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o644)
}

func safeName(name string) (string, error) {
	name = filepath.Base(strings.TrimSpace(name))
	if name == "" || name == "." || name == ".." {
		return "", errors.New("非法工程名")
	}
	return name, nil
}

func safeFileName(name string) (string, error) {
	name = filepath.Base(strings.TrimSpace(name))
	if name == "" || name == "." || name == ".." || strings.ContainsAny(name, `/\`) {
		return "", errors.New("非法文件名")
	}
	return name, nil
}

func unixSeconds() float64 {
	return float64(time.Now().UnixNano()) / 1e9
}

func stringOr(value any, fallback string) string {
	if s, ok := value.(string); ok && s != "" {
		return s
	}
	return fallback
}

func numberOr(value any, fallback float64) float64 {
	switch v := value.(type) {
	case float64:
		return v
	case int:
		return float64(v)
	case int64:
		return float64(v)
	default:
		return fallback
	}
}

func listOrEmpty(value any) []any {
	if list, ok := value.([]any); ok {
		return list
	}
	return []any{}
}

func mapOrEmpty(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return map[string]any{}
}

func mapOrNil(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return nil
}

func toolPermissionsOrDefault(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return map[string]any{"auto_approved_tools": []any{}}
}

func buildStateOrDefault(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	return defaultBuildState()
}

func defaultBuildState() map[string]any {
	return map[string]any{
		"status":              "idle",
		"last_error":          "",
		"stop_reason":         "",
		"steps":               []any{},
		"rejected_operations": []any{},
	}
}
