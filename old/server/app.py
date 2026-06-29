"""FastAPI 入口：工程/图 REST + 静态前端 + (后续) WebRTC/WS 路由。"""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .models import AISessionBody, CheckReq, CompleteReq, CreateProject, FlowGraph, Meta, RenameImage, Settings
from .project import Project, list_projects, load_settings, save_settings
from .i18n import lang_from_accept_language, localize_catalog, normalize_lang, tr, translate_error

app = FastAPI(title="flow-test 测试工作流服务端")

# 开发期前端在独立端口(vite)，放开 CORS。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.on_event("startup")
async def _warm_complete():
    # 后台预热 jedi(解析 visauto/常用 stdlib)，把一次性模块分析成本挪到启动期，
    # 用户首次代码补全即秒回。失败/未装 jedi 时静默跳过，不影响启动。
    async def _run():
        try:
            from .complete import warmup
            await asyncio.to_thread(warmup)
        except Exception:
            pass
    asyncio.create_task(_run())


@app.on_event("shutdown")
async def _shutdown():
    try:
        from .webrtc import close_all_pcs
        await close_all_pcs()
    except Exception:
        pass
    try:
        from .devices import sessions
        sessions.close_all()
    except Exception:
        pass


# ======================= 工程 =======================
@app.get("/api/projects")
def api_list_projects():
    return {"projects": list_projects()}


@app.get("/api/settings")
def api_get_settings():
    return {"settings": load_settings()}


@app.put("/api/settings")
def api_put_settings(body: Settings):
    save_settings(body.settings)
    return {"ok": True}


def _lang(request: Request) -> str:
    return lang_from_accept_language(request.headers.get("accept-language"))


@app.post("/api/projects")
def api_create_project(body: CreateProject, request: Request):
    lang = _lang(request)
    try:
        p = Project(body.name)
    except ValueError as e:
        raise HTTPException(400, translate_error(lang, e))
    if p.exists:
        raise HTTPException(409, tr(lang, "api.project_exists", "工程已存在"))
    p.ensure()
    return {"name": p.name}


def _require(name: str, lang: str = "zh") -> Project:
    try:
        p = Project(name)
    except ValueError as e:
        raise HTTPException(400, translate_error(lang, e))
    if not p.exists:
        raise HTTPException(404, tr(lang, "api.project_not_found", "工程不存在"))
    return p


@app.delete("/api/projects/{name}")
def api_delete_project(name: str, request: Request):
    _require(name, _lang(request)).delete()
    return {"ok": True}


@app.get("/api/projects/{name}/flow")
def api_get_flow(name: str, request: Request):
    p = _require(name, _lang(request))
    p.register_imagepath()
    return {"graph": p.load_flow()}


@app.put("/api/projects/{name}/flow")
def api_put_flow(name: str, body: FlowGraph, request: Request):
    _require(name, _lang(request)).save_flow(body.graph)
    return {"ok": True}


@app.get("/api/projects/{name}/meta")
def api_get_meta(name: str, request: Request):
    return {"meta": _require(name, _lang(request)).load_meta()}


@app.put("/api/projects/{name}/meta")
def api_put_meta(name: str, body: Meta, request: Request):
    _require(name, _lang(request)).save_meta(body.meta)
    return {"ok": True}


# ======================= 图片 =======================
@app.get("/api/projects/{name}/images")
def api_list_images(name: str, request: Request):
    return {"images": _require(name, _lang(request)).list_images()}


@app.post("/api/projects/{name}/images")
async def api_upload_image(name: str, file: UploadFile, request: Request):
    p = _require(name, _lang(request))
    os.makedirs(p.images_dir, exist_ok=True)
    dest = p.image_path(file.filename or "image.png")
    with open(dest, "wb") as f:
        f.write(await file.read())
    return {"name": os.path.basename(dest)}


@app.post("/api/projects/{name}/images/{img}/rename")
def api_rename_image(name: str, img: str, body: RenameImage, request: Request):
    p = _require(name, _lang(request))
    try:
        return {"name": p.rename_image(img, body.name)}
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        raise HTTPException(400, translate_error(_lang(request), e))


@app.get("/api/projects/{name}/images/{img}")
def api_get_image(name: str, img: str, request: Request):
    lang = _lang(request)
    p = _require(name, lang)
    path = p.image_path(img)
    if not os.path.exists(path):
        raise HTTPException(404, tr(lang, "api.image_not_found", "图片不存在"))
    return FileResponse(path)


# ======================= 运行结果（报告/证据）=======================
@app.get("/api/projects/{name}/results")
def api_list_results(name: str, request: Request):
    return {"runs": _require(name, _lang(request)).list_runs()}


@app.delete("/api/projects/{name}/results")
def api_clear_results(name: str, request: Request):
    return {"deleted": _require(name, _lang(request)).clear_runs()}


@app.delete("/api/projects/{name}/results/{run}")
def api_delete_result(name: str, run: str, request: Request):
    p = _require(name, _lang(request))
    try:
        p.delete_run(run)
    except FileNotFoundError as e:
        raise HTTPException(404, translate_error(_lang(request), e))
    return {"ok": True}


@app.get("/api/projects/{name}/results/{run}/{fname}")
def api_get_result(name: str, run: str, fname: str, request: Request):
    lang = _lang(request)
    p = _require(name, lang)
    path = p.result_file(run, fname)
    if not os.path.exists(path):
        raise HTTPException(404, tr(lang, "api.result_file_not_found", "结果文件不存在"))
    return FileResponse(path)


# ======================= 脚本代码补全（jedi）=======================
# jedi 补全是 CPU 密集(数十~数百 ms 且持 GIL)。快速打字会瞬间堆积大量请求，同步处理会把
# 线程池/GIL 打满导致整个服务卡死。这里：① 异步路由 + 单线程串行(一次只跑一个 jedi)；
# ② 合并去抖——排队期间若有更新请求到达，过期的直接跳过，只算最后一个(最后按键胜出)。
_complete_lock = asyncio.Lock()
_complete_seq = 0


@app.post("/api/complete")
async def api_complete(body: CompleteReq, request: Request):
    global _complete_seq
    _complete_seq += 1
    mine = _complete_seq
    async with _complete_lock:
        if mine != _complete_seq:          # 已有更新的请求在排队，本次过期，丢弃
            return {"completions": []}
        try:
            from .complete import complete
            comps = await asyncio.to_thread(complete, body.code, body.line, body.column)
            return {"completions": comps}
        except ImportError:
            raise HTTPException(503, tr(_lang(request), "api.complete_needs_jedi",
                                        "代码补全需要 jedi：pip install jedi"))


# ======================= 脚本语法检查（compile）=======================
@app.post("/api/check")
def api_check(body: CheckReq, request: Request):
    # compile() 是微秒级，直接同步即可，无需补全那套串行/去抖机制
    from .check import check_syntax
    return {"errors": check_syntax(body.code, lang=_lang(request))}


# ======================= AI 辅助流程搭建 =======================
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_END = object()


def _next_or_end(iterator):
    try:
        return next(iterator)
    except StopIteration:
        return _END


@app.get("/api/projects/{name}/ai/sessions")
def api_list_ai_sessions(name: str, request: Request):
    return {"sessions": _require(name, _lang(request)).list_ai_sessions()}


@app.post("/api/projects/{name}/ai/sessions")
def api_create_ai_session(name: str, request: Request, body: AISessionBody | None = None):
    lang = _lang(request)
    session = (body.session if body else {}) or {}
    return {"session": _require(name, lang).create_ai_session(session.get("title") or "")}


@app.get("/api/projects/{name}/ai/sessions/{session_id}")
def api_get_ai_session(name: str, session_id: str, request: Request):
    p = _require(name, _lang(request))
    try:
        return {"session": p.load_ai_session(session_id)}
    except FileNotFoundError as e:
        raise HTTPException(404, translate_error(_lang(request), e))


@app.put("/api/projects/{name}/ai/sessions/{session_id}")
def api_put_ai_session(name: str, session_id: str, body: AISessionBody, request: Request):
    p = _require(name, _lang(request))
    return {"session": p.save_ai_session(session_id, body.session)}


@app.delete("/api/projects/{name}/ai/sessions/{session_id}")
def api_delete_ai_session(name: str, session_id: str, request: Request):
    p = _require(name, _lang(request))
    try:
        p.delete_ai_session(session_id)
    except FileNotFoundError as e:
        raise HTTPException(404, translate_error(_lang(request), e))
    return {"ok": True}


@app.delete("/api/projects/{name}/ai/sessions")
def api_clear_ai_sessions(name: str, request: Request):
    return {"deleted": _require(name, _lang(request)).clear_ai_sessions()}


@app.post("/api/projects/{name}/ai/draft")
async def api_ai_flow_draft(name: str, request: Request, state: str = Form("{}"),
                            files: list[UploadFile] = File(default=[])):
    lang = _lang(request)
    _require(name, lang)
    try:
        payload = json.loads(state or "{}")
        if not isinstance(payload, dict):
            raise ValueError("state must be an object")
    except Exception:
        raise HTTPException(400, tr(lang, "ai_builder.bad_state", "AI 搭建请求格式错误"))
    try:
        from .flow.ai_builder import AIBuilderError, generate_draft, read_case_documents
        docs = await read_case_documents(files or [], lang=lang)
        docs = _merge_ai_docs(payload.get("documents") or [], docs)
        return await asyncio.to_thread(generate_draft, payload, docs, lang)
    except AIBuilderError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, tr(lang, "ai_builder.failed", "AI 生成失败：{error}", error=e))


@app.post("/api/projects/{name}/ai/sessions/{session_id}/draft/stream")
async def api_ai_flow_draft_stream(name: str, session_id: str, request: Request,
                                   state: str = Form("{}"),
                                   files: list[UploadFile] = File(default=[])):
    lang = _lang(request)
    _require(name, lang)
    try:
        payload = json.loads(state or "{}")
        if not isinstance(payload, dict):
            raise ValueError("state must be an object")
    except Exception:
        raise HTTPException(400, tr(lang, "ai_builder.bad_state", "AI 搭建请求格式错误"))

    async def stream():
        try:
            from .flow.ai_builder import AIBuilderError, generate_draft_stream, read_case_documents
            yield _sse("thought", {
                "node": "docs",
                "title": tr(lang, "ai_builder.stream.reading_docs", "正在读取测试用例文档..."),
                "detail": "",
                "status": "active",
            })
            uploaded_docs = await read_case_documents(files or [], lang=lang)
            docs = _merge_ai_docs(payload.get("documents") or [], uploaded_docs)
            yield _sse("thought", {
                "node": "docs",
                "title": tr(lang, "ai_builder.stream.reading_docs", "正在读取测试用例文档..."),
                "detail": tr(lang, "ai_builder.thought.docs_done", "测试用例文档已读取并合并到会话上下文。"),
                "status": "done",
            })
            yield _sse("docs", {"docs": uploaded_docs})
            yield _sse("thought", {
                "node": "context",
                "title": tr(lang, "ai_builder.stream.analyzing", "正在分析当前画布与会话上下文..."),
                "detail": "",
                "status": "active",
            })
            await asyncio.sleep(0)
            yield _sse("thought", {
                "node": "context",
                "title": tr(lang, "ai_builder.stream.analyzing", "正在分析当前画布与会话上下文..."),
                "detail": tr(lang, "ai_builder.thought.context_done", "已整理当前画布、历史会话、草稿与表单数据。"),
                "status": "done",
            })
            draft_emitted = False
            events = iter(generate_draft_stream(payload, docs, lang))
            while True:
                event = await asyncio.to_thread(_next_or_end, events)
                if event is _END:
                    break
                etype = event.get("type")
                if etype == "message":
                    yield _sse("message", {"content": event.get("content", "")})
                elif etype == "thought":
                    yield _sse("thought", {
                        "node": event.get("node", ""),
                        "title": event.get("title", ""),
                        "detail": event.get("detail", ""),
                        "status": event.get("status", "active"),
                    })
                elif etype == "form":
                    yield _sse("form", {"form": event.get("form")})
                elif etype == "delta":
                    yield _sse("delta", {"text": event.get("delta", "")})
                elif etype == "tokens":
                    yield _sse("tokens", {
                        "completion_tokens": event.get("completion_tokens", 0),
                        "estimated": event.get("estimated", True),
                    })
                elif etype == "usage":
                    yield _sse("usage", {"usage": event.get("usage") or {}})
                elif etype == "draft":
                    draft_emitted = True
                    yield _sse("draft", {"draft": event.get("draft")})
            if draft_emitted:
                yield _sse("thought", {
                    "node": "ready",
                    "title": tr(lang, "ai_builder.stream.draft_ready", "流程草稿已生成。"),
                    "detail": "",
                    "status": "done",
                })
            yield _sse("done", {"ok": True})
        except AIBuilderError as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            yield _sse("error", {"message": tr(lang, "ai_builder.failed", "AI 生成失败：{error}", error=e)})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


def _merge_ai_docs(saved_docs: list, uploaded_docs: list) -> list[dict]:
    merged = []
    seen = set()
    for doc in [*(saved_docs or []), *(uploaded_docs or [])]:
        if not isinstance(doc, dict):
            continue
        name = str(doc.get("name") or "case.txt")
        text = str(doc.get("text") or "")
        key = (name, text[:80])
        if not text.strip() or key in seen:
            continue
        seen.add(key)
        merged.append({"name": name, "text": text})
    return merged


def _websocket_lang(websocket: WebSocket) -> str:
    qlang = websocket.query_params.get("lang")
    if qlang:
        return normalize_lang(qlang)
    return lang_from_accept_language(websocket.headers.get("accept-language"))


async def _safe_ws_send(websocket: WebSocket, data: dict) -> None:
    try:
        await websocket.send_json(data)
    except WebSocketDisconnect as e:
        raise e
    except Exception as e:
        raise WebSocketDisconnect(code=1006) from e


def _stopped_reason_message(reason: str, lang: str) -> str:
    messages = {
        "max_tool_calls": tr(lang, "ai_builder.ws.max_tool_calls_reached",
                             "AI 搭建已停止：已达最大工具调用上限，可在「设置 → AI 辅助搭建模型」中增大上限后继续。"),
        "max_repair_rounds": tr(lang, "ai_builder.ws.max_repair_rounds_reached",
                                "AI 搭建已停止：已达最大修复次数上限，可在「设置 → AI 辅助搭建模型」中增大上限后继续。"),
        "timeout": tr(lang, "ai_builder.ws.timeout_reached",
                      "AI 搭建已停止：总超时，可在「设置 → AI 辅助搭建模型」中增大超时后继续。"),
    }
    return messages.get(reason, tr(lang, "ai_builder.ws.stopped", "AI 搭建已停止：{reason}", reason=reason))


@app.websocket("/ws/ai-build/{name}/{session_id}")
async def ws_ai_build(websocket: WebSocket, name: str, session_id: str):
    await websocket.accept()
    lang = _websocket_lang(websocket)
    stopped = False
    stop_reason = ""
    try:
        p = _require(name, lang)
        session = p.load_ai_session(session_id)
        init = await websocket.receive_json()
        if init.get("type") != "init":
            await websocket.send_json({"type": "error", "message": tr(lang, "ai_builder.ws.bad_init", "AI 搭建初始化消息格式错误")})
            return
        saved_docs = session.get("documents") or []
        init_docs = init.get("documents") or []
        docs = _merge_ai_docs(saved_docs, init_docs)
        session["documents"] = docs
        build_state = session.get("build_state") if isinstance(session.get("build_state"), dict) else {}
        build_state.update({"status": "running", "last_error": "", "stop_reason": ""})
        build_state.setdefault("steps", [])
        build_state.setdefault("rejected_operations", [])
        session["build_state"] = build_state
        p.save_ai_session(session_id, session)

        pending_results: dict[str, dict] = {}
        incoming: asyncio.Queue[dict] = asyncio.Queue()

        async def reader_loop():
            nonlocal stopped, stop_reason
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "stop":
                    stopped = True
                    stop_reason = msg.get("reason") or "user_stop"
                    await incoming.put(msg)
                    break
                await incoming.put(msg)

        reader_task = asyncio.create_task(reader_loop())

        async def on_event(event: dict) -> None:
            nonlocal session
            etype = event.get("type")
            if etype == "tool_step":
                session = p.load_ai_session(session_id)
                state = session.get("build_state") or {}
                steps = state.get("steps") if isinstance(state.get("steps"), list) else []
                steps.append(event.get("step") or {})
                state["steps"] = steps
                session["build_state"] = state
                p.save_ai_session(session_id, session)
            await _safe_ws_send(websocket, event)

        async def send_tool_call(call: dict) -> None:
            await _safe_ws_send(websocket, call)

        async def wait_tool_result(call_id: str) -> dict:
            nonlocal stopped, stop_reason, session
            while True:
                if call_id in pending_results:
                    return pending_results.pop(call_id)
                msg = await incoming.get()
                mtype = msg.get("type")
                if mtype == "stop":
                    raise RuntimeError("AI_BUILD_STOPPED")
                if mtype == "tool_result":
                    tid = msg.get("tool_call_id") or msg.get("id")
                    if tid == call_id:
                        if msg.get("status") == "rejected":
                            session = p.load_ai_session(session_id)
                            state = session.get("build_state") or {}
                            rejected = state.get("rejected_operations") if isinstance(state.get("rejected_operations"), list) else []
                            rejected.append(msg.get("log") or msg.get("result") or {})
                            state["rejected_operations"] = rejected
                            session["build_state"] = state
                            messages = session.get("messages") if isinstance(session.get("messages"), list) else []
                            messages.append({
                                "role": "assistant",
                                "content": tr(lang, "ai_builder.ws.rejected_hint",
                                              "用户拒绝了 AI 操作，AI 已停止，当前半成品保留。后续应优先避免重复该操作，除非用户补充说明后确有必要。"),
                            })
                            session["messages"] = messages
                            p.save_ai_session(session_id, session)
                        return msg
                    pending_results[str(tid)] = msg

        def should_stop() -> bool:
            return stopped

        from .flow.ai_builder import AIBuilderError, AIBuilderStopped, run_ai_build_loop
        try:
            result = await run_ai_build_loop(init, docs, session, send_tool_call, wait_tool_result, on_event, should_stop, lang)
            session = p.load_ai_session(session_id)
            state = session.get("build_state") or {}
            state["status"] = result.get("status") or "completed"
            state["stop_reason"] = result.get("reason") or ""
            session["build_state"] = state
            p.save_ai_session(session_id, session)
            await _safe_ws_send(websocket, {"type": "done", **result})
        except AIBuilderStopped as e:
            session = p.load_ai_session(session_id)
            state = session.get("build_state") or {}
            state["status"] = "stopped"
            state["stop_reason"] = e.reason
            session["build_state"] = state
            p.save_ai_session(session_id, session)
            await _safe_ws_send(websocket, {"type": "done", "status": "stopped", "reason": e.reason,
                                             "message": _stopped_reason_message(e.reason, lang)})
        except RuntimeError as e:
            if str(e) != "AI_BUILD_STOPPED":
                raise
            session = p.load_ai_session(session_id)
            state = session.get("build_state") or {}
            state["status"] = "stopped"
            state["stop_reason"] = stop_reason or "user_stop"
            session["build_state"] = state
            p.save_ai_session(session_id, session)
            await _safe_ws_send(websocket, {"type": "done", "status": "stopped", "reason": state["stop_reason"]})
        except AIBuilderError as e:
            session = p.load_ai_session(session_id)
            state = session.get("build_state") or {}
            state["status"] = "failed"
            state["last_error"] = str(e)
            session["build_state"] = state
            p.save_ai_session(session_id, session)
            await _safe_ws_send(websocket, {"type": "error", "message": str(e)})
            await _safe_ws_send(websocket, {"type": "done", "status": "failed", "reason": "error"})
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        try:
            p = _require(name, lang)
            session = p.load_ai_session(session_id)
            state = session.get("build_state") or {}
            if state.get("status") == "running":
                state["status"] = "stopped"
                state["stop_reason"] = "websocket_disconnected"
                session["build_state"] = state
                p.save_ai_session(session_id, session)
        except Exception:
            pass
    except Exception as e:
        try:
            await _safe_ws_send(websocket, {"type": "error", "message": tr(lang, "ai_builder.failed", "AI 生成失败：{error}", error=e)})
            await _safe_ws_send(websocket, {"type": "done", "status": "failed", "reason": "error"})
        except Exception:
            pass


# ======================= 节点目录（前端建面板用）=======================
@app.get("/api/nodes")
def api_node_catalog(request: Request):
    from .flow.catalog import node_catalog
    return JSONResponse(localize_catalog(node_catalog(), _lang(request)))


@app.get("/api/nodes/spec")
def api_node_spec(type: str, request: Request):
    from .flow.ai_builder import _read_graph_skill_tool_doc
    from .flow.catalog import node_catalog
    lang = _lang(request)
    catalog = localize_catalog(node_catalog(), lang)
    spec = next((n for n in catalog.get("nodes", []) if n.get("type") == type), None)
    if not spec:
        raise HTTPException(404, tr(lang, "api.node_spec_not_found", "节点类型不存在：{type}", type=type))
    doc = _read_graph_skill_tool_doc(node_type=type).get("doc") or spec.get("description") or ""
    return {"ok": True, "spec": spec, "doc": doc}


# ======================= WebRTC / WS（M2/M3）=======================
def _mount_realtime():
    try:
        from .signaling import router as ws_router
        app.include_router(ws_router)
    except Exception as e:  # 实时模块未就绪时不影响 REST
        print(tr("zh", "api.realtime_mount_failed", "[warn] 实时模块未挂载：{error}", error=e))


_mount_realtime()


# ======================= 静态前端 =======================
_WEB_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "dist")
if os.path.isdir(_WEB_DIST):
    app.mount("/", StaticFiles(directory=_WEB_DIST, html=True), name="web")


def main():
    import uvicorn
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
