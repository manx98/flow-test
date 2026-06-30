# Go 重构实施计划

## 目标

使用 Go 重新实现当前后端、运行器、设备层、视觉/OCR、AI Builder 和脚本插件体系；继续复用现有 Vue/LiteGraph 前端。Go HTTP 服务使用 Gin 框架。

核心目标是长期可维护性，而不是简单语言翻译。重构后需要保持 `flow.json` 工程兼容，旧 AI session 不做兼容迁移。

## 已确认决策

- 后端使用 Go 重构。
- Go HTTP 服务使用 Gin 框架。
- 前端继续复用当前 Vue/LiteGraph。
- AI Builder 使用 CloudWeGo Eino 重新实现。
- Flow Runner 使用 Go 原生实现，不交给 Eino。
- 脚本体系改为 JS 插件，使用 `goja`。
- JS 插件允许受控设备 wrapper，不暴露底层设备对象。
- JS 插件允许循环执行 UI 操作，但必须支持 runner 超时、goja interrupt、abort 检查。
- JS 插件沿用“脚本定义节点 + 执行节点 + 动态端口”结构。
- 新节点建议为 `script/js` 与 `script/js_exec`。
- 旧 `script/python` / `script/exec` 从当前 Go/前端节点目录移除；旧版参考保留在 `old/`。
- 废弃 `visauto`。
- 视觉使用 `gocv.io/x/gocv`。
- Tesseract OCR 使用 `github.com/otiai10/gosseract/v2`。
- PaddleOCR 节点保留站位，第一阶段不实现。
- RDP 使用 FreeRDP 2 cgo 集成，依赖 `freerdp2 freerdp-client2 winpr2`。
- VMware 使用 `github.com/vmware/govmomi` 支持 ESXi。
- Local Device 第一阶段移除。
- VMware ESXi 第一阶段验收必须包含截图、鼠标、键盘输入。

## 目标架构

```text
Go Backend
  ├─ HTTP / WebSocket API (Gin)
  ├─ Project / flow.json / images / results
  ├─ Node Catalog Loader
  ├─ Flow Runner
  ├─ JS Plugin Runtime (goja)
  ├─ Device Layer
  │   ├─ RDP: FreeRDP 2 cgo
  │   ├─ noVNC/RFB: kward/go-vnc + WebSocket net.Conn adapter
  │   ├─ PVE: PVE API -> VNC websocket -> go-vnc
  │   ├─ VMware ESXi: govmomi -> WebMKS -> go-vnc
  │   └─ Local: removed
  ├─ Vision: GoCV
  ├─ OCR: gosseract
  ├─ AI Builder: Eino
  └─ Static frontend hosting
```

Eino 只负责 AI Builder 编排，不负责 Flow Runner、设备控制、视觉、OCR 或 JS 执行。

## 兼容策略

### 必须兼容

- 已有 `flow.json` 工程格式。
- 现有前端 API/WebSocket 的主要协议。
- `graph_skills/**/node.json` 组件定义格式，必要时做字段扩展。
- 项目目录结构：`flow.json`、`images/`、`results/`。
- 现有运行事件：
  - `node`
  - `node_shot`
  - `node_text`
  - `alert`
  - `run start/done/error`

### 不兼容

- 旧 AI session。
- Python 脚本运行。
- Local Device 运行。

### Legacy 行为

- `device/local`：可显示 legacy，运行时报不支持。
- PaddleOCR：节点可存在，运行时报未实现。

## 并存迁移策略

迁移期间允许 Python 后端与 Go 后端并存，直到 Go 版通过核心验收后再切换默认入口。

```text
Phase A
  Python 后端继续可用
  Go 后端在独立 Go module 中开发

Phase B
  Go 后端支持核心 API / runner
  前端可通过配置切换连接 Python 或 Go

Phase C
  Go 后端覆盖主要功能
  Python 后端只作为参考和旧版 fallback

Phase D
  Go 后端成为默认入口
  Python 后端归档或移除
```

当前目录约定：

- Go module 已上移到仓库根目录。
- Python 旧版已移动到 `old/`。
- `server/flow/graph_skills` 作为 Go 版和前端共用的组件契约目录保留在根目录。
- Python 后端迁移期继续保留在 `old/server`。
- Go 默认端口使用 `8080`。
- 前端开发时通过环境变量或 Vite proxy 切换 API base。
- 使用 golden tests 对比 Python runner 与 Go runner 行为，直到 Go runner 达到兼容目标。
- 不在 Go 版核心验收完成前删除 Python 后端或 `visauto` 参考实现。

## Go 目录建议

```text
./
  cmd/flow-test/
    main.go
  internal/api/
    gin.go
    routes.go
    websocket.go
    middleware.go
  internal/project/
    project.go
    images.go
    results.go
  internal/catalog/
    catalog.go
  internal/flow/
    graph.go
    runner.go
    report.go
    values.go
  internal/nodes/
    data.go
    flow.go
    action.go
    wait.go
    assert.go
    api.go
    vision.go
    ocr.go
    script_js.go
  internal/device/
    device.go
    rdp.go
    rfb.go
    pve.go
    vmware.go
  internal/vision/
    image.go
    template.go
    mask.go
  internal/ocr/
    tesseract.go
    paddle_stub.go
  internal/jsplugin/
    runtime.go
    wrapper_device.go
    ports.go
  internal/aibuilder/
    agent.go
    tools.go
    sessions.go
    prompts.go
    compile_patch.go
  internal/i18n/
    i18n.go
```

## Node Catalog 策略

迁移期继续使用现有 `server/flow/graph_skills/**/node.json` 作为组件契约 source of truth，Go 版不复制一份 catalog。

理由：

- 前端当前已经依赖这套 `node.json`。
- 当前 Go 版与前端共用同一份组件契约。
- 避免两份 catalog 分叉。
- Go 版可以在 loader 层过滤或标记不支持节点。
- Go 版稳定后，再考虑把 `graph_skills` 移到语言无关根目录。

Go catalog loader 规则：

- 递归读取 `server/flow/graph_skills/*/*/node.json`。
- 保留原始字段。
- 注入 Go 版支持元信息：
  - `supported: true/false`
  - `legacy: true/false`
  - `reason`
- 过滤 `device/local`。
- 仅保留 `script/js` / `script/js_exec` 脚本节点定义。
- PaddleOCR 节点保留但标记未实现。

## Flow Runner 设计

Runner 必须保持当前执行语义：

- exec 线驱动流程。
- data 输入按需拉取。
- eval 节点结果 memo。
- run 节点按执行流运行。
- 节点错误归属到源节点。
- try/catch 能捕获运行错误。
- `assert/check`、日志、提示、文本展示等自报状态节点不被后续空状态覆盖。
- abort 贯穿 runner、设备操作、JS 插件、视觉/OCR。

基础接口：

```go
type Runner struct {
    Graph Graph
    Values map[OutputRef]any
    Vars map[string]any
    Devices map[int64]Device
}

type NodeHandler interface {
    Eval(ctx context.Context, rc *RunContext, node *Node) (map[string]any, error)
    Run(ctx context.Context, rc *RunContext, node *Node) (nextExec string, err error)
}
```

## JS 插件体系

### 节点

```text
script/js
  outputs:
    script: script

script/js_exec
  inputs:
    in: exec
    script: script
    ...dynamic args
  outputs:
    out: exec
    ...dynamic results
```

### JS API

v1 暴露最小 API：

```js
const value = getArg("name")
setResult("ok", true)
log("message")
```

设备参数通过 wrapper 暴露：

```js
const pc = getArg("pc")
const found = pc.findImage("login_button", { threshold: 0.85 })
if (found.ok) {
  pc.click(found.point)
}
setResult("ok", found.ok)
```

### 禁止能力

- 文件读写。
- 网络请求。
- 子进程。
- 系统环境变量。
- 动态 import。
- `eval` / `Function`。
- 直接访问 Go 内部对象。

### 超时与中止

- 每次 JS 执行有总超时，默认 30s。
- 支持用户 stop interrupt goja。
- `while (true) {}` 必须可打断。
- wrapper 每次设备操作前后检查 `context.Context`。
- wrapper 方法级超时独立配置。

## Device 接口

统一设备接口：

```go
type Device interface {
    Capture(ctx context.Context, dst **image.RGBA) error
    MouseMove(ctx context.Context, x, y int) error
    MouseDown(ctx context.Context, button Button, x, y int) error
    MouseUp(ctx context.Context, button Button, x, y int) error
    MouseWheel(ctx context.Context, delta int) error
    KeyDown(ctx context.Context, key Key) error
    KeyUp(ctx context.Context, key Key) error
    TypeText(ctx context.Context, text string) error
    Close() error
}
```

### RDP

- 使用 FreeRDP 2 cgo。
- 维护 framebuffer。
- FreeRDP GDI paint 更新 framebuffer。
- `MouseDown/MouseMove/MouseUp/MouseWheel` 实现鼠标。
- `KeyDown/KeyUp` 实现键盘。
- 需要处理键盘布局、分辨率、重连、截图等待。
- 许可证 GPL-3.0 已接受。
- 当前实现已接入 `device/rdp`；Linux+cgo 下通过 FreeRDP 2 建立连接、拷贝 GDI framebuffer，并发送鼠标/键盘事件。
- 已支持 `security_protocol` 配置：`auto`、`ssl`、`nla`、`rdp`。旧 xrdp 可用 `ssl` 绕过 NLA。
- 已支持 FreeRDP 安全层选择、连接超时、首帧等待和断线错误上报。
- 已实现远程鼠标后端合成：缓存 FreeRDP pointer shape，并在截图/视频帧输出时合成 32bpp alpha cursor；cursor 位置跟随输入侧鼠标事件。

### noVNC / RFB

- 使用 `github.com/kward/go-vnc` 实现 RFB client。
- TCP VNC 直接通过 `net.Conn` 接入。
- noVNC WebSocket 通过 Gorilla WebSocket 包装为 `net.Conn` 后交给 `go-vnc`。
- 支持 framebuffer update。
- 支持 pointer event。
- 支持 key event。
- 支持 PVE VNC websocket。

### PVE

- 调 PVE API 获取 ticket / csrf / vncproxy 信息。
- 构造 VNC websocket URL。
- 使用 RFB device 连接。
- 当前已实现 `device/pve`：登录 `/access/ticket`，调用 `/vncproxy`，携带 `PVEAuthCookie` 和 `vncticket` 连接 `/vncwebsocket`，复用 `VNCDevice`。
- 已添加默认跳过的真实环境 smoke test：`PVE_TEST=1` 时连接真实 PVE 并截图。

### VMware ESXi

- 使用 `github.com/vmware/govmomi` 登录 ESXi。
- 定位 VM。
- 获取 console ticket / console URL。
- 接入 console adapter。
- 必须实现截图、鼠标、键盘输入。
- 第一优先级是 spike 控制台链路。
- 当前已实现 `device/vmware`：govmomi 登录，按 `vm` / `vm_name` / `moid` 定位虚拟机，调用 `AcquireTicket(webmks)`，通过 WebMKS `wss://.../ticket/...` 复用 `VNCDevice`。

建议属性：

```json
{
  "base_url": "https://esxi-host/sdk",
  "username": "root",
  "password": "",
  "insecure": true,
  "vm_name": "",
  "moid": "",
  "width": 1280,
  "height": 800
}
```

## Vision / OCR

### GoCV

实现：

- 图片加载。
- 截图转 Mat。
- 模板匹配。
- mask 匹配。
- find one。
- find all。
- match result 转 point / rect / score。
- 带命中框截图回显。

需要重点校准：

- BGR/RGBA 转换。
- 阈值默认值。
- mask 行为。
- 多尺度匹配是否进入 v1。
- 坐标系和缩放。

当前进度：

- `const/image` 在 Go run 的项目上下文中已可从 `images/` 加载真实图片；没有项目 resolver 或图片文件不存在时仍返回 `{name}` 引用供前端/预览使用。
- 已接入 GoCV 模板匹配：`vision/find_image` / `vision/find_all` 在输入为 `image.Image` 或可 Capture 的 `device.Ref` 时可返回真实 match/count。
- `mask/create` 在项目上下文中已可加载真实 mask 图片；`vision/find_image` / `vision/find_all` 使用 GoCV mask，支持白色/非透明参与、黑色/透明忽略的 mask 语义。
- `wait/appear` / `wait/vanish` 已接入同一套图片、设备截图和 GoCV mask 匹配；可观察到真实图片时按 timeout 判断 out/timeout。
- 视觉命中时 Go runner 已可生成带红框的 `node_shot` PNG 并通过运行事件返回前端可访问 URL。
- 断言失败时会把最近一次 `node_shot` URL 写入 report assert evidence，JUnit 中也会包含证据路径。
- GoCV 原生依赖已进入 Go module；部署环境需要可编译/链接 OpenCV。

### Action nodes

当前进度：

- `action/click` / `action/type` / `action/hotkey` / `action/scroll` / `action/drag` 在输入为真实 `device.Ref.Device` 时会调用统一 `device.Device` 鼠标/键盘接口。
- 输入仍为 unsupported placeholder 时保持 planned log 行为，便于设备驱动接入前继续跑流程。

### gosseract

实现：

- Tesseract OCR engine。
- 语言配置。
- 最小置信度。
- 图片预处理。
- OCR 结果结构化输出。

### Paddle

第一阶段只保留占位：

```text
PaddleOCR is not implemented in Go version yet
```

## AI Builder / Eino

Eino 负责：

- ChatModel 调用。
- Tool calling。
- Human confirm / interrupt。
- AI session。
- Graph patch 生成。
- WebSocket 直接搭建。
- Tool trace。
- Graph Skills 文档选择。

Eino 不负责：

- Flow Runner。
- Device 操作。
- Vision/OCR。
- JS 执行。

需要重写工具：

- `create_node`
- `connect_nodes`
- `set_node_property`
- `set_node_ports`
- `validate_canvas`
- 可能保留 `ask_user` / human confirmation。

AI Builder 提示词策略：

- 默认使用 JS 插件，不再生成 Python。
- 简单流程仍使用可视化节点。
- 复杂逻辑使用 `script/js` + `script/js_exec`。
- 网络请求必须使用 `api/request`。
- 外部资源必须通过图节点传入 JS 插件。
- 业务失败用 `setResult("ok", false)`，再接断言与结果节点。

旧 AI session 不迁移。

## API / WebSocket 兼容表

Go HTTP 服务使用 Gin 组织路由、中间件、静态资源和 REST API。WebSocket 可使用 Gin handler 内升级连接。

### 保留 REST API

- `GET /api/health`
- `GET /api/projects`
- `POST /api/projects`
- `DELETE /api/projects/{name}`
- `GET /api/projects/{name}/flow`
- `PUT /api/projects/{name}/flow`
- `GET /api/projects/{name}/images`
- `POST /api/projects/{name}/images`
- `GET /api/projects/{name}/results`
- `GET /api/nodes`
- `GET /api/nodes/spec`

### 保留 WebSocket

- `/ws/run/{name}`
- `/ws/ai-build/{name}/{session_id}`

### Run 事件

```json
{"type":"node","id":1,"status":"running","info":""}
{"type":"node","id":1,"status":"ok","info":""}
{"type":"node","id":1,"status":"fail","info":"..."}
{"type":"alert","id":2,"level":"info","message":"..."}
{"type":"node_shot","id":3,"url":"..."}
{"type":"node_text","id":4,"text":"..."}
{"type":"run","status":"done","report":{}}
```

## 节点迁移矩阵

### v1 必须实现

- `flow/start`
- `flow/if`
- `flow/loop`
- `flow/sequence`
- `flow/try_catch`
- `flow/raise`
- `wait/delay`
- `assert/check`
- `test/result`
- `const/text`
- `const/number`
- `const/bool`
- `const/point`
- `const/image`
- `data/text_display`
- `var/set`
- `var/get`
- `api/request`
- `api/json_serialize`
- `api/form_serialize`
- `script/js`
- `script/js_exec`
- `util/log`
- `util/alert`
- `device/attrs`
- `io/interaction`
- `device/rdp`
- `device/novnc`
- `device/pve`
- `device/vmware`
- `vision/preview`
- `vision/find_image`
- `vision/find_all`
- `vision/find_text`
- `mask/create`
- `ocr/tesseract`
- action nodes: click/type/hotkey/scroll/drag/to_point

### v1 站位

- `ocr/paddle`

### v1 移除

- `device/local`
- `script/python`
- `script/exec`

## 里程碑

### M0: 契约冻结

- 固化 flow schema。
- 固化 node catalog schema。
- 固化 WebSocket 事件。
- 产出 golden flow 测试样例。

### M1: Go 服务壳

- Gin HTTP server。
- 静态前端托管。
- project CRUD。
- flow save/load。
- node catalog loader。
- results 基础管理。

当前进度：

- Go module 已上移到仓库根目录；Python 旧版已移动到 `old/`。
- 已添加 Gin 服务入口、project CRUD、flow/meta/images/results 基础 API。
- 已补齐 settings API、JS 语法检查与轻量 JS 补全 API。
- 已补齐图片上传、图片重命名、结果文件读取、单个结果删除、结果清空 API。
- 已添加 node catalog loader，继续读取 `server/flow/graph_skills` 并过滤 `device/local`。
- 已补齐静态前端托管与 SPA route fallback，API/WS 未命中仍返回 JSON 404。
- 已添加同步 run endpoint 与可执行 WebSocket run endpoint。
- 运行结果已保存 `report.json` 与 `report.junit.xml`，REST/WS run 会返回前端可直接打开的结果链接。
- 当前 Go API 包可全量编译测试。
- 已添加 AI Build WebSocket fallback，前端连接后会收到可应用 draft 与 completed 事件，而不是直接握手失败。
- 已添加 Gin handler 回归测试，覆盖工程创建、当前 graph 运行、report.json 读取、图片上传/重命名/列表、AI Draft fallback、AI Build WS fallback。
- 已补齐 AI session CRUD REST，用于前端保存/读取 AI Builder 会话状态。

### M2: Go Flow Runner 核心

- exec/data 执行模型。
- 变量。
- 控制流。
- 断言和报告。
- WebSocket run 事件。
- 文本展示。

当前进度：

- 已添加 `internal/flow` 图模型、事件模型、最小 runner。
- 已添加 LiteGraph `links` 数组兼容解析，按节点端口 slot 映射端口名。
- 已添加 `internal/nodes` 基础 registry，覆盖 `flow/start`、`flow/if`、`flow/loop`、`flow/sequence`、`flow/try_catch`、`flow/raise`、常量、坐标常量、变量、delay、assert、test result、log、alert、text display、JSON/Form serialize、HTTP request、JS 脚本。
- `wait/delay` 已按现有节点契约使用 `seconds` 属性。
- 已添加单元测试覆盖 catalog/project/runner、LiteGraph 解析、条件分支、断言、序列化和 HTTP request 基础行为。
- 已添加异常捕获与坐标常量测试。
- 已添加 Go 版运行报告结构，`POST /api/projects/:name/run` 会生成 `results/<run>/report.json`，并在响应中返回 `run`、`report`、`events`。
- 报告语义已区分 assertion failure、捕获异常和未捕获节点错误；只有未捕获 runner error 进入 `errors`。
- 已添加设备节点输出和 `device/attrs` 拆分；`device/rdp` 已通过 FreeRDP 2 cgo 接入，`device/novnc` 已通过 `github.com/kward/go-vnc` 接入 TCP VNC 与 noVNC WebSocket，`device/pve` 已通过 Proxmox API + VNC WebSocket 接入，`device/vmware` 已通过 govmomi + WebMKS 接入。
- 已添加设备工厂入口与真实 `static_image` fixture device，可通过 `image` / `image_path` / `image_base64` 配置提供截图，供视觉/OCR/JS 脚本链路集成验证。
- 已添加设备截图 API：`GET /api/devices/:session_id/capture`，真实设备 session 返回 PNG，未接入远程驱动的 session 明确返回 501。
- 已添加 `const/image`、`vision/preview`、`mask/create` 的资源引用/透传，找图路径已接入 GoCV。
- `vision/find_image` / `vision/find_all` 已按节点契约读取 `similarity`，保留旧 `threshold` 兼容；匹配候选会按 score 降序排序，`find_image` 返回最佳命中。
- 已添加 `geom/to_point` 的纯计算实现，支持 match 锚点和偏移转换。
- 已添加 `vision/find_image`、`vision/find_all` 的 GoCV 模板匹配；`vision/find_text` 已接入 gosseract/Tesseract，可直接从图片识别 text blocks，并支持普通文本、regex 和 `min_confidence` 过滤。
- 已添加 `ocr/tesseract` gosseract 实现；`ocr/paddle` 配置引用占位，真实 Paddle 后端待 M5 接入。
- 已添加 action 节点运行实现：`action/click`、`action/type`、`action/hotkey`、`action/scroll`、`action/drag` 在有真实设备时调用统一 `device.Device` 接口；无真实设备时记录 planned action。
- 已注册 `io/interaction`，运行时会消费 device 输入并发送交互节点状态，避免未知节点错误。
- 已抽取 REST run 共用执行逻辑，便于后续 WebSocket run 复用同一 runner/report 路径。
- 已接入 `/ws/run/:name`，支持前端 `{cmd:"run", graph}`、逐条推送节点/提示/文本事件、生成 report、发送 `run done`，并支持 `{cmd:"stop"}` 取消运行。

### M3: JS 插件

- `script/js`。
- `script/js_exec`。
- 动态端口。
- goja runtime。
- 超时/interrupt/abort。
- 受控 device wrapper。

当前进度：

- 已在 Go runner registry 中接入 `script/js` 与 `script/js_exec`。
- `script/js` 已可输出脚本 code。
- `script/js_exec` 已可从动态输入端口收集参数、调用 `internal/jsplugin.Runtime`、并将 runtime results 写回动态输出端口。
- 已接入 goja runtime，支持 `getArg(name, defaultValue)`、`setResult(name, value)`、`log(value)`。
- JS runtime 支持 context timeout / interrupt，可打断 `while(true){}`。
- JS runtime 禁用 `eval` / `Function`，不暴露文件、网络、系统调用。
- JS runtime 已添加受控 device wrapper：支持 `findImage` / `findAll` / `findText` / `click` / `type` / `hotkey` / `wait` 的受限接口；`findImage` / `findAll` 在输入为真实 `device.Ref.Device` 和 `image.Image` 模板时可通过设备截图执行 GoCV 模板匹配，并支持 `{mask}`；`findText` 可匹配设备配置中的 OCR text blocks。
- JS device wrapper 在输入为真实 `device.Ref.Device` 时，`click` / `type` / `hotkey` 会调用统一 `device.Device` 接口；无真实设备时保持 planned log。
- `script/js_exec` 仅允许写入节点已声明的非 exec result 输出端口，未声明 result 会报错。
- JS `log(value)` 通过 `alert`/`log` 事件进入运行日志，不伪装为节点 ok 状态。
- 已添加 runner 集成测试：`script/js_exec` 的动态 `ok` result 可连接到 `assert/check`。
- 当前依赖整理后 Go 工具将 module directive 提升为 `go 1.26.3`。

### M4: 设备 spike

- RDP FreeRDP framebuffer + input 已接入，后续继续补键盘布局、重连和更多编码兼容。
- RFB/noVNC framebuffer + input 已通过 `github.com/kward/go-vnc` 接入。
- PVE -> VNC WebSocket -> go-vnc 已接入。
- VMware ESXi console adapter。

当前进度：

- 已定义统一 `device.Device` interface。
- 已添加 `device.Ref`，用于在 graph value / JS runtime 中携带受控设备引用；真实设备对象通过 `json:"-"` 隐藏，不暴露给前端或脚本。
- 设备 session 已支持填充真实 `Device`；`static_image`、RDP/FreeRDP、VNC/go-vnc、PVE 与 VMware 连接已接入。
- 已接入设备 session 生命周期：`/api/devices/connect` 可创建 unsupported session 并返回尺寸，`/api/devices/:session_id/disconnect` 会删除 session。
- Go runner 已支持按 `project + device node id` 复用 UI 连接创建的设备 session ref；没有 live session 时回退节点静态配置。
- 当前已接入 WebRTC video bridge：真实 `Device` 可通过 `/api/webrtc/offer` 返回 `mode: "webrtc-video"` 并推送 VP8 视频轨；前端通过 DataChannel 转发鼠标键盘事件。
- 仍保留 HTTP PNG capture fallback：当 WebRTC bridge 初始化失败时返回 `mode: "capture"`、`capture_url` 和 `input_url`。

### M5: Vision/OCR

- GoCV template matching。
- mask。
- find all。
- gosseract OCR。
- node_shot 回显。

### M6: Eino AI Builder

- session。
- prompt。
- tool calling。
- human confirm。
- graph patch compile。
- direct build websocket。
- JS 插件生成策略。

当前进度：

- 已实现 AI session 的列表、创建、读取、保存、删除、清空 REST。
- `ai/draft` 与 `ai/sessions/:id/draft/stream` 已提供本地 fallback：返回可应用的 JS 流程草稿，并把 stream 生成的 draft 保存到 AI session。
- `/ws/ai-build/:name/:session_id` 已提供本地 fallback：返回可应用的 JS 流程草稿、usage 与 completed 状态。
- 已接入 AI Builder settings 解析：provider、base_url、model、temperature、confirm/tool/retry/timeout 配置会进入 Go builder，draft metadata 只暴露安全状态，不返回 API key。
- 已接入 AI Builder HTTP 模型客户端：支持 OpenAI-compatible/custom `chat/completions` 与 Ollama `/api/chat`；OpenAI-compatible/custom 支持 tool call，Ollama 支持非流式 tool call；429/5xx 会按配置重试；模型不可用、响应无法解析或草稿编译失败时回退本地 JS draft。
- AI Builder REST/SSE/WebSocket 响应会携带安全 draft metadata，前端和会话记录可区分模型生成与本地 fallback。
- 已接入 Go 版 canvas tool schema 与风险 metadata：覆盖 inspect/list/read/create/set/connect/delete/validate/finish，并包含 `set_node_ports` 动态端口 schema。
- 已接入 Go 版 direct-build prompt/message 构造：包含用户指令、最近对话、文档摘要、压缩画布节点/端口摘要、表单值、rejected 操作和 recent tool trace；AI session 会保存压缩后的 init context summary。
- 已接入 Graph Skills 文档自动选择：根据用户需求、上传文档、当前画布节点类型和复杂/脚本/API/视觉/设备关键词补充相关 DOC；复杂、脚本、简化、循环、计算类需求会自动带上 `script/js` 与 `script/js_exec` 文档。
- 已接入 Eino-backed direct-build 客户端：OpenAI-compatible/custom 模型和 Ollama `/api/chat` 使用 Eino ChatModel 适配，支持实时 delta 返回，并能合并流式 tool-call 参数分片。
- 已接入 OpenAI-compatible tool-call 响应解析：可解析 direct-build 模式下的 `tool_calls`、函数名和 JSON 参数。
- 已接入后端 tool loop 核心与 WebSocket direct-build 基础接线：配置 OpenAI-compatible/custom/Ollama 模型时可发送 tool call 到前端、等待 tool result、追加 tool messages、限制 max tool calls，并在 `finish_build` 成功时结束。
- WebSocket direct-build 已把模型文本增量作为 `delta` 事件返回给前端，前端会实时追加显示。
- tool loop 已处理用户 stop 为 `done: stopped`，并会把 rejected tool 操作记录回 AI session build_state，供后续 prompt 避免重复操作。
- tool loop 已记录工具 trace：每次 tool call 的参数、状态、结果、权限决策和前端工具日志会写入 AI session build_state，便于审计和后续调试。
- 已接入本地 graph patch compile 校验：覆盖 JS 语法、动态端口、重复/非法端口和连线端口引用。
- human confirm / interrupt 的 Eino 原生化仍待完善；当前先复用既有 WebSocket tool_result/stop 协议。

### M7: 兼容与替换

- 旧 flow 打开/运行。
- legacy 节点提示。
- 文档更新。
- 端到端验收。

## 高风险清单

1. VMware ESXi 控制台链路是否可稳定拿到 framebuffer 和输入控制。
2. FreeRDP 2 native 依赖、运行环境和许可证对发布模式的影响。
3. GoCV / Tesseract native 依赖导致部署复杂。
4. GoCV 匹配结果与当前 visauto 行为不一致。
5. JS 插件死循环和设备操作超时。
6. Eino tool calling 与现有前端 confirm/step UI 的协议映射。
7. 旧 flow 中已移除 Python 脚本、Local Device 的迁移体验。
8. noVNC/RFB 键盘映射和中文输入。
9. RDP 键盘布局、H.264、重连和 framebuffer 更新一致性。
10. AI Builder 上下文选择和 graph skills 文档裁剪重新实现后质量回退。

## 外部依赖

- Eino: https://www.cloudwego.io/docs/eino/
- Gin: https://gin-gonic.com/
- GoCV: https://pkg.go.dev/gocv.io/x/gocv
- gosseract: https://pkg.go.dev/github.com/otiai10/gosseract/v2
- FreeRDP: https://www.freerdp.com/
- govmomi: https://pkg.go.dev/github.com/vmware/govmomi
