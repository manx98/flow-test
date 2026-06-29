# flow-test

This repository root now contains the Go backend. The previous Python backend has been moved under `old/`.

## Run

Install native dependencies first. The Go backend links GoCV/OpenCV and gosseract/Tesseract directly.

Ubuntu / Debian:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential pkg-config \
  libopencv-dev \
  tesseract-ocr libtesseract-dev libleptonica-dev \
  tesseract-ocr-eng tesseract-ocr-chi-sim \
  freerdp2-dev libfreerdp2-2 libfreerdp-client2-2 libwinpr2-dev \
  libvpx-dev
```

Fedora / RHEL:

```bash
sudo dnf install -y \
  gcc gcc-c++ pkgconf-pkg-config \
  opencv-devel \
  tesseract tesseract-devel leptonica-devel \
  tesseract-langpack-eng tesseract-langpack-chi_sim \
  libvpx-devel
```

macOS:

```bash
brew install opencv tesseract leptonica libvpx
```

Verify the native libraries:

```bash
pkg-config --modversion opencv4
pkg-config --modversion tesseract
pkg-config --modversion lept
pkg-config --modversion freerdp2
pkg-config --modversion winpr2
pkg-config --modversion vpx
tesseract --version
```

If `pkg-config` cannot find Tesseract or Leptonica, export the paths before building:

```bash
export CGO_CFLAGS="$(pkg-config --cflags tesseract lept)"
export CGO_LDFLAGS="$(pkg-config --libs tesseract lept)"
```

```bash
go mod tidy
go run ./cmd/flow-test
```

RDP support uses Linux cgo + FreeRDP 2. To run it:

```bash
CGO_ENABLED=1 go run ./cmd/flow-test
```

## Profiling

The Go backend exposes pprof endpoints on the same HTTP port:

```bash
go tool pprof http://127.0.0.1:8080/debug/pprof/heap
go tool pprof http://127.0.0.1:8080/debug/pprof/allocs
go tool pprof http://127.0.0.1:8080/debug/pprof/profile?seconds=30
go tool pprof http://127.0.0.1:8080/debug/pprof/goroutine
```

For quick memory checks without pprof:

```bash
curl http://127.0.0.1:8080/api/debug/memstats
curl -X POST http://127.0.0.1:8080/api/debug/gc
```

Defaults:

- Go backend: `:8080`
- Legacy Python backend lives in `old/`
- `FLOW_WORKSPACE` controls the project workspace when set
- `FLOW_REPO_ROOT` can point to the repository root; default is `.`

Current milestone:

- Gin HTTP server
- project list/create/delete
- flow load/save
- metadata load/save
- image upload/list/read/rename
- result list/read/delete/clear
- settings load/save
- AI session CRUD
- local fallback AI Draft REST/SSE that returns an applyable JS flow skeleton and persists it to AI sessions
- AI Builder WebSocket fallback that returns an applyable JS flow skeleton and completed status
- AI Builder settings parsing for provider/model/tool limits; generated drafts include safe model metadata without exposing API keys
- AI Builder HTTP model client for OpenAI-compatible/custom chat completions and Ollama `/api/chat`; 429/5xx responses are retried, while invalid responses or unavailable models fall back to the local JS draft
- AI Builder REST/SSE/WebSocket responses include safe draft metadata so callers can distinguish model-generated drafts from local fallback drafts
- AI Builder canvas tool schemas and risk metadata are defined in Go for inspect/list/read/create/set/connect/delete/validate/finish operations
- AI Builder direct-build prompt/message construction is implemented in Go, includes compact canvas nodes and recent tool trace, and saves a compact init-context summary in AI sessions
- AI Builder direct-build now auto-selects Graph Skills docs from the request, existing canvas node types, and complex/script/API/vision/device keywords
- AI Builder Eino-backed direct-build client is wired for configured OpenAI-compatible/custom and Ollama models, including realtime delta streaming and streamed tool-call argument merging
- AI Builder HTTP fallback client supports OpenAI-compatible/custom tool calls and non-streaming Ollama `/api/chat` tool calls
- AI Builder WebSocket direct-build path can run the backend tool loop, stream assistant deltas to the frontend, send tool calls to the frontend, wait for tool results, and complete on `finish_build`
- AI Builder tool loop handles user stop as `done: stopped` and records rejected tool operations back into AI session build state
- AI Builder tool loop records tool trace entries, including permission decisions and frontend tool logs, in AI session build state
- AI Builder draft compile checks for JS syntax, dynamic script ports, duplicate/invalid ports, and link port references before returning drafts
- node catalog loader reading `server/flow/graph_skills`
- sync run endpoint with JSON/JUnit report persistence
- WebSocket run with `run` / `stop`
- static frontend hosting with SPA route fallback
- Go flow runner for control/data/API/script/action placeholders
- project image loading for `const/image` during runs
- GoCV template matching for image-backed vision nodes, including masks for `vision/find_image` and `vision/find_all`
- Tesseract OCR via gosseract for `vision/find_text`, plus OCR text block matching for precomputed blocks and JS `pc.findText`
- pure Go fallback for `wait/appear` and `wait/vanish`
- `node_shot` PNG evidence for image matches during runs
- failed assertions can reference the latest `node_shot` as report evidence
- action nodes call real `device.Device` mouse/keyboard methods when available
- JS device wrapper calls real `device.Device` click/type/hotkey methods when available
- JS `pc.findImage(template, { mask })` can use real device capture with image templates and masks
- JS `pc.findAll(template, { mask })` returns all image matches from real device capture
- JS `pc.findText(text, { regex, minConfidence })` can match configured OCR text blocks
- goja JS runtime with controlled device wrapper
- device session lifecycle API with real `device/rdp` via Linux cgo + FreeRDP 2, real `device/novnc` via `github.com/kward/go-vnc` plus WebSocket transport adapter, real `device/pve` via Proxmox API + VNC WebSocket, real `device/vmware` via govmomi WebMKS ticket, and `static_image` fixture devices
- device capture API: `GET /api/devices/:session_id/capture` returns PNG for sessions with a real device
- capture-stream fallback for device UI: `/api/devices/connect` returns `stream_mode: "capture"` for real devices, `/api/webrtc/offer` keeps the same fallback response for older callers, and `/api/devices/:session_id/input` forwards mouse/keyboard events
- `io/interaction` is registered in the Go runtime and consumes connected device handles without failing unknown-node checks
- runner reuse of connected device sessions by project and node id
- JS syntax check and lightweight JS completion endpoints for code overlays
- WebRTC device bridge streams device frames as a VP8 video track through `github.com/pion/mediadevices`, keeps the DataChannel for input events, and retains HTTP capture fallback

Validation:

```bash
GOCACHE=/tmp/flow-test-go-cache GOMODCACHE=/tmp/flow-test-go-modcache go test ./...
```

Notes:

- Do not set `GOPROXY` unless your local environment requires it.
- RDP uses FreeRDP 2 through cgo on Linux. Non-Linux or `CGO_ENABLED=0` builds return a clear dependency error for RDP while the rest of the project can still build.
- xrdp/Windows RDP security negotiation is delegated to FreeRDP. The `auth` property accepts `auto`, `nla`, `tls`, and `rdp`.
- VNC uses `github.com/kward/go-vnc` for RFB protocol handling. `ws://` and `wss://` noVNC endpoints are supported by wrapping Gorilla WebSocket as a `net.Conn`.
- PVE uses the Proxmox API login -> `vncproxy` -> `vncwebsocket` flow and then reuses the VNC device. Real PVE smoke tests are gated by `PVE_TEST=1`.
- VMware uses `github.com/vmware/govmomi` to log in to ESXi/vCenter, locate the VM, acquire a WebMKS ticket, then reuse the VNC WebSocket device.
- `go mod tidy` currently records `go 1.26.3` after resolving dependencies.
