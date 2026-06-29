"""AI-assisted test flow planning.

The builder exposes Graph Skills to the model and asks it to return a graph
patch: concrete LiteGraph node types, properties, and named links. The backend
does not maintain a separate task DSL; it only validates the patch against the
Graph Skills node catalog before the frontend previews and inserts it.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..i18n import tr
from ..check import check_syntax
from . import types as T
from .catalog import GRAPH_SKILLS_ROOT, node_catalog


_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
_DEVICE_TYPES = {"device/local", "device/novnc", "device/rdp", "device/pve", "device/vmware"}
_SENSITIVE_PROPS = {"api_key", "password", "token", "secret"}
_MAX_DOC_CHARS = 28000
_MAX_SKILL_CONTEXT_CHARS = 52000
_MAX_SELECTED_CATEGORIES = 5
_MAX_SELECTED_NODES = 14
_MAX_TOOL_ROUNDS = 6
_SCRIPT_EXEC_DYNAMIC_TYPES = {"match", "point", "text", "number", "bool", "picture", "mask", "ocr", "device", "script"}


class AIBuilderError(RuntimeError):
    """Raised for user-facing AI builder failures."""


class AIBuilderStopped(RuntimeError):
    """Raised when the user stops or disconnects an AI build."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def missing_forms(state: dict, lang: str = "zh") -> list[dict]:
    """Return dynamic forms required before the planner can run."""
    values = state.get("form_values") or {}
    graph = state.get("current_graph") or {}
    if not _has_device_source(graph) and not (values.get("device_config") or {}).get("type"):
        return [_device_form(values.get("device_config") or {}, lang)]
    return []


async def read_case_documents(files: list[Any], lang: str = "zh") -> list[dict]:
    docs = []
    for f in files or []:
        name = getattr(f, "filename", "") or "case.txt"
        data = await f.read()
        text = _read_document(name, data, lang)
        if text.strip():
            docs.append({"name": name, "text": text[:_MAX_DOC_CHARS]})
    return docs


def generate_draft(state: dict, docs: list[dict], lang: str = "zh") -> dict:
    forms = missing_forms(state, lang)
    if forms:
        return {
            "message": tr(lang, "ai_builder.need_info", "需要先补充这些信息，我拿到后继续生成流程。"),
            "forms": forms,
            "draft": None,
        }

    ai_cfg = state.get("ai_settings") or ((state.get("form_values") or {}).get("ai_settings") or {})
    _require_ai_config(ai_cfg, lang)
    graph = state.get("current_graph") or {}
    device_cfg = ((state.get("form_values") or {}).get("device_config") or {})
    graph_nodes = ((state.get("form_values") or {}).get("graph_nodes") or {})
    previous_patch = _previous_patch(state)
    if not graph_nodes.get("image_node_id") and _judge_needs_graph_nodes(ai_cfg, state, docs, previous_patch, lang):
        return {
            "message": tr(lang, "ai_builder.need_graph_nodes", "需要先选择画布中的模板图片节点，我拿到后继续生成流程。"),
            "forms": [_graph_nodes_form(graph_nodes, lang)],
            "draft": None,
        }
    patch = _ask_model(ai_cfg, state, docs, previous_patch, lang)
    draft = compile_graph_patch(patch, graph, device_cfg, ai_cfg, graph_nodes, lang=lang)
    return {
        "message": tr(lang, "ai_builder.draft_ready", "已生成流程草稿，你可以预览后应用到画布，或继续描述修改。"),
        "forms": [],
        "draft": draft,
    }


def generate_draft_stream(state: dict, docs: list[dict], lang: str = "zh"):
    yield _thought("precheck", tr(lang, "ai_builder.thought.precheck", "检查生成前置条件"), status="active")
    forms = missing_forms(state, lang)
    if forms:
        yield _thought("precheck", tr(lang, "ai_builder.thought.precheck", "检查生成前置条件"),
                       tr(lang, "ai_builder.thought.need_info", "缺少必要配置，暂停生成并等待用户补充。"),
                       status="done")
        yield {
            "type": "message",
            "content": tr(lang, "ai_builder.need_info", "需要先补充这些信息，我拿到后继续生成流程。"),
        }
        for form in forms:
            yield {"type": "form", "form": form}
        return
    yield _thought("precheck", tr(lang, "ai_builder.thought.precheck", "检查生成前置条件"),
                   tr(lang, "ai_builder.thought.precheck_ok", "设备与会话上下文已准备好。"),
                   status="done")

    ai_cfg = state.get("ai_settings") or ((state.get("form_values") or {}).get("ai_settings") or {})
    _require_ai_config(ai_cfg, lang)
    graph = state.get("current_graph") or {}
    device_cfg = ((state.get("form_values") or {}).get("device_config") or {})
    graph_nodes = ((state.get("form_values") or {}).get("graph_nodes") or {})
    previous_patch = _previous_patch(state)
    yield _thought("graph_nodes", tr(lang, "ai_builder.thought.graph_nodes", "判断是否需要图像节点"), status="active")
    if not graph_nodes.get("image_node_id") and _judge_needs_graph_nodes(ai_cfg, state, docs, previous_patch, lang):
        yield _thought("graph_nodes", tr(lang, "ai_builder.thought.graph_nodes", "判断是否需要图像节点"),
                       tr(lang, "ai_builder.thought.graph_nodes_needed", "模型判断需要使用画布中的模板图片节点。"),
                       status="done")
        yield {
            "type": "message",
            "content": tr(lang, "ai_builder.need_graph_nodes", "需要先选择画布中的模板图片节点，我拿到后继续生成流程。"),
        }
        yield {"type": "form", "form": _graph_nodes_form(graph_nodes, lang)}
        return
    yield _thought("graph_nodes", tr(lang, "ai_builder.thought.graph_nodes", "判断是否需要图像节点"),
                   tr(lang, "ai_builder.thought.graph_nodes_ready", "无需额外选择，或已取得图片/遮罩节点。"),
                   status="done")
    yield _thought("skills", tr(lang, "ai_builder.thought.skills", "读取 Graph Skills 索引"), status="active")
    skill_context = _select_graph_skill_context(ai_cfg, state, docs, previous_patch, graph_nodes, lang)
    yield _thought("skills", tr(lang, "ai_builder.thought.skills", "读取 Graph Skills 索引"),
                   tr(lang, "ai_builder.thought.skills_done", "模型已选择需要展开的分类和节点文档。"),
                   status="done")
    yield _thought("model", tr(lang, "ai_builder.thought.model", "生成测试流程草稿"), status="active")
    content = ""
    usage = None
    for event in _ask_model_stream(ai_cfg, state, docs, previous_patch, lang, skill_context):
        if event["type"] == "delta":
            content += event["delta"]
            yield {"type": "delta", "delta": event["delta"]}
            yield {"type": "tokens", **event["tokens"]}
        elif event["type"] == "usage":
            usage = event["usage"]
            yield {"type": "usage", "usage": usage}
    yield _thought("model", tr(lang, "ai_builder.thought.model", "生成测试流程草稿"),
                   tr(lang, "ai_builder.thought.model_done", "模型输出完成，开始解析与校验。"),
                   status="done")
    yield _thought("compile", tr(lang, "ai_builder.thought.compile", "编译为画布草稿"), status="active")
    obj = _extract_json(content)
    if not isinstance(obj, dict):
        yield _thought("compile", tr(lang, "ai_builder.thought.compile", "编译为画布草稿"),
                       tr(lang, "ai_builder.thought.compile_failed", "模型输出无法解析为流程 JSON。"),
                       status="error")
        raise AIBuilderError(tr(lang, "ai_builder.bad_model_json",
                                "模型没有返回可解析的流程 JSON：{snippet}", snippet=content[:200]))
    patch = _normalize_graph_patch(obj)
    draft = compile_graph_patch(patch, graph, device_cfg, ai_cfg, graph_nodes, lang=lang)
    yield _thought("compile", tr(lang, "ai_builder.thought.compile", "编译为画布草稿"),
                   tr(lang, "ai_builder.thought.compile_done", "已生成可应用到画布的节点与连线。"),
                   status="done")
    yield {
        "type": "message",
        "content": tr(lang, "ai_builder.draft_ready", "已生成流程草稿，你可以预览后应用到画布，或继续描述修改。"),
    }
    yield {"type": "draft", "draft": draft}
    if usage:
        yield {"type": "usage", "usage": usage}


def _thought(node: str, title: str, detail: str = "", status: str = "active") -> dict:
    return {
        "type": "thought",
        "node": node,
        "title": title,
        "detail": detail,
        "status": status,
    }


def compile_graph_patch(patch: dict, current_graph: dict | None = None, device_config: dict | None = None,
                        ai_config: dict | None = None, graph_nodes: dict | None = None,
                        lang: str = "zh") -> dict:
    compiler = _GraphPatchCompiler(current_graph or {}, device_config or {}, ai_config or {}, graph_nodes or {}, lang)
    return compiler.compile(patch or {})


def _previous_patch(state: dict) -> dict | None:
    return state.get("draft_patch") or state.get("graph_patch") or state.get("draft_dsl") or None


def _ai_config_ready(cfg: dict) -> bool:
    provider = (cfg.get("provider") or "openai").strip().lower()
    model = (cfg.get("model") or "").strip()
    if not model:
        return False
    if provider == "openai":
        return bool((cfg.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip())
    if provider == "custom":
        return bool((cfg.get("base_url") or "").strip())
    return True


def _require_ai_config(cfg: dict, lang: str) -> None:
    provider = (cfg.get("provider") or "openai").strip().lower()
    model = (cfg.get("model") or "").strip()
    if not model:
        raise AIBuilderError(tr(
            lang, "ai_builder.settings_missing",
            "请先在「设置」中配置 AI 辅助搭建使用的模型。"))
    if provider == "openai" and not (cfg.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip():
        raise AIBuilderError(tr(
            lang, "ai_builder.settings_missing",
            "请先在「设置」中配置 AI 辅助搭建使用的模型。"))
    if provider == "custom" and not (cfg.get("base_url") or "").strip():
        raise AIBuilderError(tr(
            lang, "ai_builder.settings_missing",
            "请先在「设置」中配置 AI 辅助搭建使用的模型。"))


def _ai_form(current: dict, lang: str) -> dict:
    return {
        "id": "ai_settings",
        "kind": "fields",
        "title": tr(lang, "ai_builder.forms.ai.title", "AI 模型配置"),
        "description": tr(lang, "ai_builder.forms.ai.desc", "用于本次流程生成；敏感字段不会写入流程。"),
        "submit_label": tr(lang, "ai_builder.forms.continue", "继续生成"),
        "fields": [
            _field("provider", tr(lang, "ai_builder.forms.ai.provider", "服务商"), "enum",
                   current.get("provider", "openai"), options=["openai", "ollama", "custom"]),
            _field("base_url", tr(lang, "ai_builder.forms.ai.base_url", "接口地址"), "string",
                   current.get("base_url", "")),
            _field("model", tr(lang, "ai_builder.forms.ai.model", "模型"), "string",
                   current.get("model", "gpt-4o")),
            _field("api_key", tr(lang, "ai_builder.forms.ai.api_key", "API Key"), "password",
                   current.get("api_key", ""), sensitive=True),
            _field("temperature", tr(lang, "ai_builder.forms.ai.temperature", "采样温度"), "number",
                   current.get("temperature", 0)),
            _field("reasoning_effort", tr(lang, "ai_builder.forms.ai.reasoning_effort", "思考强度"), "enum",
                   current.get("reasoning_effort", ""), options=["", "low", "medium", "high"]),
        ],
    }


def _device_form(current: dict, lang: str) -> dict:
    devices = []
    for spec in node_catalog().get("nodes", []):
        if spec.get("type") in _DEVICE_TYPES:
            devices.append({
                "type": spec["type"],
                "title": spec.get("title", spec["type"]),
                "properties": spec.get("properties") or [],
            })
    return {
        "id": "device_config",
        "kind": "device",
        "title": tr(lang, "ai_builder.forms.device.title", "被测设备配置"),
        "description": tr(lang, "ai_builder.forms.device.desc", "当前画布没有设备节点，请选择设备类型并填写配置。敏感字段不会写入流程。"),
        "submit_label": tr(lang, "ai_builder.forms.continue", "继续生成"),
        "type": current.get("type", "device/rdp"),
        "devices": devices,
    }


def _graph_nodes_form(current: dict, lang: str) -> dict:
    return {
        "id": "graph_nodes",
        "kind": "graph_nodes",
        "title": tr(lang, "ai_builder.forms.graph_nodes.title", "选择图像节点"),
        "description": tr(
            lang,
            "ai_builder.forms.graph_nodes.desc",
            "请在画布中选择模板图片节点；如果流程需要忽略区域，也可以选择遮罩节点。"),
        "submit_label": tr(lang, "ai_builder.forms.continue", "继续生成"),
        "values": current or {},
    }


def _field(name: str, label: str, ftype: str, default=None, **extra) -> dict:
    return {"name": name, "label": label, "type": ftype, "default": default, **extra}


def _read_document(name: str, data: bytes, lang: str) -> str:
    ext = os.path.splitext(name.lower())[1]
    if ext in {".txt", ".md", ".json", ".csv"}:
        return _decode_text(data)
    if ext == ".docx":
        try:
            from docx import Document
        except ImportError as e:
            raise AIBuilderError(tr(lang, "ai_builder.docx_needs_package",
                                    "读取 docx 需要 python-docx：pip install python-docx")) from e
        doc = Document(BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    raise AIBuilderError(tr(
        lang, "ai_builder.unsupported_doc",
        "不支持的文档格式：{name}。请上传 txt/md/json/csv/docx。", name=name))


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _ask_model(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
               lang: str, skill_context: str | None = None) -> dict:
    req = _model_request(ai_cfg, state, docs, previous_patch, lang, skill_context)
    params = _run_graph_skill_tool_loop(req["client"], req["params"])
    resp = _chat_create(req["client"], {**params, "tool_choice": "none"})
    content = (resp.choices[0].message.content or "").strip()
    obj = _extract_json(content)
    if not isinstance(obj, dict):
        raise AIBuilderError(tr(lang, "ai_builder.bad_model_json",
                                "模型没有返回可解析的流程 JSON：{snippet}", snippet=content[:200]))
    return _normalize_graph_patch(obj)


def _ask_model_stream(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
                      lang: str, skill_context: str | None = None):
    req = _model_request(ai_cfg, state, docs, previous_patch, lang, skill_context)
    params_with_tools = _run_graph_skill_tool_loop(req["client"], req["params"])
    params_with_tools["tool_choice"] = "none"
    params = {**req["params"], "stream": True, "stream_options": {"include_usage": True}}
    params.update({
        "messages": params_with_tools["messages"],
        "tools": params_with_tools.get("tools"),
        "tool_choice": "none",
    })
    try:
        stream = _chat_create(req["client"], params)
    except TypeError:
        params.pop("stream_options", None)
        stream = _chat_create(req["client"], params)
    completion_estimate = 0
    for chunk in stream:
        usage = _usage_dict(getattr(chunk, "usage", None))
        if usage:
            yield {"type": "usage", "usage": usage}
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        text = getattr(delta, "content", None) or ""
        if not text:
            continue
        completion_estimate += _estimate_tokens(text)
        yield {
            "type": "delta",
            "delta": text,
            "tokens": {
                "completion_tokens": completion_estimate,
                "estimated": True,
            },
        }


def _model_request(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
                   lang: str, skill_context: str | None = None) -> dict:
    client, params = _model_client_params(ai_cfg, lang)
    messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(state, docs, previous_patch, skill_context)},
        ]
    return {"client": client, "params": {**params, "messages": messages, "tools": _graph_skill_tools()}}


def _model_client_params(ai_cfg: dict, lang: str) -> tuple[Any, dict]:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise AIBuilderError(tr(lang, "ai_builder.needs_openai",
                                "AI 流程生成需要 openai：pip install openai")) from e

    provider = (ai_cfg.get("provider") or "openai").strip().lower()
    base_url = (ai_cfg.get("base_url") or "").strip() or _DEFAULT_BASE.get(provider, "")
    if not base_url:
        raise AIBuilderError(tr(lang, "ai_builder.missing_base_url", "custom 服务商需要填写接口地址"))
    api_key = (ai_cfg.get("api_key") or os.environ.get("OPENAI_API_KEY") or "").strip()
    if provider == "ollama":
        api_key = api_key or "ollama"
    elif provider == "custom":
        api_key = api_key or "none"
    model = (ai_cfg.get("model") or "gpt-4o").strip()
    temperature = float(ai_cfg.get("temperature", 0) or 0)
    reasoning_effort = str(ai_cfg.get("reasoning_effort") or "").strip()

    client = OpenAI(base_url=base_url, api_key=api_key or "none")
    params = {
        "model": model,
        "temperature": temperature,
    }
    if reasoning_effort:
        params["reasoning_effort"] = reasoning_effort
    return client, params


def _chat_create(client, params: dict):
    try:
        return client.chat.completions.create(**params)
    except TypeError:
        if "reasoning_effort" in params:
            retry = dict(params)
            retry.pop("reasoning_effort", None)
            return client.chat.completions.create(**retry)
        raise
    except Exception as e:
        if "reasoning_effort" in params and "reasoning_effort" in str(e):
            retry = dict(params)
            retry.pop("reasoning_effort", None)
            return client.chat.completions.create(**retry)
        raise


def _is_retryable_model_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    retryable = ("timeout", "timed out", "connection", "connect", "network", "temporarily unavailable")
    return any(part in name or part in text for part in retryable)


async def _interruptible_sleep(seconds: float, should_stop: Callable[[], bool] | None = None) -> None:
    end = time.monotonic() + seconds
    while True:
        if should_stop and should_stop():
            raise AIBuilderStopped("user_stop")
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.1, remaining))


async def _chat_create_with_retry_async(client, params: dict, lang: str,
                                        on_event: Callable[[dict], Awaitable[None]] | None = None,
                                        should_stop: Callable[[], bool] | None = None,
                                        attempts: int = 3):
    last_error = None
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        if should_stop and should_stop():
            raise AIBuilderStopped("user_stop")
        try:
            return await asyncio.to_thread(_chat_create, client, params)
        except Exception as e:
            last_error = e
            if attempt >= total or not _is_retryable_model_error(e):
                break
            if on_event:
                await on_event({
                    "type": "status",
                    "status": "retrying",
                    "message": tr(lang, "ai_builder.ws.model_retry",
                                  "模型接口超时或连接失败，正在重试 {attempt}/{total}...",
                                  attempt=attempt + 1, total=total),
                })
            await _interruptible_sleep(min(3.2, 0.8 * (2 ** (attempt - 1))), should_stop)
    if last_error and _is_retryable_model_error(last_error):
        raise AIBuilderError(tr(lang, "ai_builder.ws.model_retry_failed",
                                "模型接口超时或连接失败，已重试 {total} 次仍失败：{error}",
                                total=total, error=last_error)) from last_error
    raise last_error


def _run_graph_skill_tool_loop(client, params: dict) -> dict:
    messages = [dict(m) for m in (params.get("messages") or [])]
    tools = params.get("tools") or []
    if not tools:
        return {**params, "messages": messages}
    base = {k: v for k, v in params.items() if k not in {"messages", "stream", "stream_options"}}
    for _ in range(_MAX_TOOL_ROUNDS):
        resp = _chat_create(client, {**base, "messages": messages, "tool_choice": "auto"})
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        messages.append(_message_to_dict(msg))
        if not tool_calls:
            break
        for call in tool_calls:
            fn = getattr(call, "function", None)
            name = getattr(fn, "name", "")
            raw_args = getattr(fn, "arguments", "") or "{}"
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}
            result = _dispatch_graph_skill_tool(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": getattr(call, "id", ""),
                "content": json.dumps(result, ensure_ascii=False),
            })
    return {**params, "messages": messages}


def _message_to_dict(message) -> dict:
    if hasattr(message, "model_dump"):
        data = message.model_dump(exclude_none=True)
    else:
        data = {
            "role": getattr(message, "role", "assistant"),
            "content": getattr(message, "content", None),
            "tool_calls": getattr(message, "tool_calls", None),
        }
    if data.get("content") is None and data.get("tool_calls"):
        data["content"] = ""
    return data


def _graph_skill_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_graph_skill_categories",
                "description": "List Graph Skills categories with brief guidance. Use this before reading category details.",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_graph_skill_nodes",
                "description": "List graph node types in one category, or all node summaries when category is omitted.",
                "parameters": {
                    "type": "object",
                    "properties": {"category": {"type": "string", "description": "Directory category name, e.g. action"}},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_graph_skill_doc",
                "description": "Read one category DOC.md or one merged node document with node.json ports/properties plus DOC.md usage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "Directory category name to read."},
                        "node_type": {"type": "string", "description": "Graph node type to read, e.g. action/click."},
                    },
                    "additionalProperties": False,
                },
            },
        },
    ]


def _dispatch_graph_skill_tool(name: str, args: dict) -> dict:
    if name == "list_graph_skill_categories":
        return {"categories": _list_graph_skill_categories()}
    if name == "list_graph_skill_nodes":
        return {"nodes": _list_graph_skill_nodes(str(args.get("category") or "").strip() or None)}
    if name == "read_graph_skill_doc":
        return _read_graph_skill_tool_doc(
            category=str(args.get("category") or "").strip() or None,
            node_type=str(args.get("node_type") or "").strip() or None,
        )
    return {"error": f"unknown tool: {name}"}


def _list_graph_skill_categories() -> list[dict]:
    out = []
    for path in sorted(GRAPH_SKILLS_ROOT.glob("*/DOC.md")):
        text = _read_skill_doc(path, 1200)
        out.append({"name": path.parent.name, "doc": text})
    return out


def _list_graph_skill_nodes(category: str | None = None) -> list[dict]:
    nodes = []
    for spec in node_catalog().get("nodes", []):
        dirname = _category_dir_for_spec(spec)
        if category and dirname != category:
            continue
        nodes.append({
            "category": dirname,
            "type": spec.get("type"),
            "title": spec.get("title"),
            "description": spec.get("description"),
        })
    return nodes


def _read_graph_skill_tool_doc(category: str | None = None, node_type: str | None = None) -> dict:
    if node_type:
        catalog_nodes = node_catalog().get("nodes", [])
        spec = next((n for n in catalog_nodes if n.get("type") == node_type), None)
        if not spec:
            return {"error": f"unknown node_type: {node_type}"}
        dirname = node_type.replace("/", "_")
        paths = list(GRAPH_SKILLS_ROOT.glob(f"*/{dirname}/DOC.md"))
        if not paths:
            return {"error": f"doc not found for node_type: {node_type}"}
        return {"node_type": node_type, "doc": _render_node_skill_doc(spec, paths[0])}
    if category:
        path = GRAPH_SKILLS_ROOT / category / "DOC.md"
        if not path.exists():
            return {"error": f"unknown category: {category}"}
        return {"category": category, "doc": _read_skill_doc(path, 4000)}
    return {"error": "category or node_type is required"}


def _judge_needs_graph_nodes(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
                             lang: str) -> bool:
    client, params_base = _model_client_params(ai_cfg, lang)
    graph = state.get("current_graph") or {}
    payload = {
        "instruction": state.get("message") or "",
        "recent_chat": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in (state.get("history") or [])[-8:] if m.get("content")
        ],
        "documents": [{"name": d.get("name", ""), "text": (d.get("text") or "")[:6000]} for d in docs],
        "previous_graph_patch": previous_patch,
        "available_graph_nodes": _available_graph_nodes(graph),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You decide whether an AI-assisted UI test flow MUST ask the user to select an existing "
                "template image node from the LiteGraph canvas before planning. Return ONLY JSON with this "
                "shape: {\"needs_graph_nodes\": true|false, \"reason\": \"short\"}.\n"
                "Return true when the case needs template-image matching from an existing graph image node, "
                "for example finding/clicking/asserting a specific icon, picture, screenshot crop, or masked "
                "template that cannot be represented reliably by OCR text or an AI visual description alone. "
                "Return false for pure text/OCR checks, keyboard/input flows, device setup, or semantic AI "
                "vision descriptions that do not require a user-provided template image. Mask selection is "
                "optional and should not by itself force true unless a template image is needed."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    params = {**params_base, "messages": messages, "stream": False}
    try:
        resp = client.chat.completions.create(**params)
        content = (resp.choices[0].message.content or "").strip()
    except Exception:
        return False
    obj = _extract_json(content)
    return bool(isinstance(obj, dict) and obj.get("needs_graph_nodes") is True)


def _available_graph_nodes(graph: dict) -> dict:
    images = []
    masks = []
    for node in graph.get("nodes") or []:
        props = node.get("properties") or {}
        item = {
            "id": node.get("id"),
            "type": node.get("type"),
            "title": node.get("title") or "",
        }
        if node.get("type") == "const/image":
            item["name"] = props.get("name") or ""
            images.append(item)
        elif node.get("type") == "mask/create":
            item["mask"] = props.get("mask") or ""
            masks.append(item)
    return {"image_nodes": images, "mask_nodes": masks}


def _usage_dict(usage) -> dict | None:
    if not usage:
        return None
    if isinstance(usage, dict):
        data = usage
    elif hasattr(usage, "model_dump"):
        data = usage.model_dump()
    else:
        data = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
    out = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = data.get(key)
        if isinstance(value, int):
            out[key] = value
    return out or None


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


_SYSTEM_PROMPT = """You are an expert QA automation flow builder for a LiteGraph-based UI testing tool.
Return ONLY one compact JSON object. No prose, no markdown fences.

You no longer use a fixed action DSL. Learn the available graph modules from Graph Skills in the user message, then create a graph patch using those node types and named ports.
You have Graph Skills tools. Use them to inspect only the categories and node docs needed for the current task before producing the final graph patch.

Required JSON shape:
{
  "title": "short test name",
  "summary": "what the graph does",
  "nodes": [
    {"id":"n1", "type":"flow/start", "title":"optional", "pos":[120,330], "properties":{}}
  ],
  "links": [
    {"from":"n1", "out":"out", "to":"n2", "in":"in"}
  ],
  "entry": "n1"
}

Rules:
- Use ONLY node types, input names, output names, and property names from Graph Skills node.json.
- For script/exec only, you may add dynamic data ports by declaring "inputs" and/or "outputs" on the node. Dynamic port types must be one of: match, point, text, number, bool, picture, mask, ocr, device, script.
- Use current canvas nodes as external references with id format external:<canvas_node_id>.
- Link exec ports to exec ports, and data ports to compatible data ports only.
- If the current canvas has an unused flow/start, do not create another start; set entry to the first generated exec node and the backend will connect it.
- If there is no device node on the current canvas, create the configured device node plus device/attrs. Connect device outputs to actions and vision nodes as needed.
- For HTTP/API calls, use api/request. Use api/json_serialize or api/form_serialize for JSON/form request body conversion. Do not put network calls inside Python scripts.
- For visible text, prefer OCR/vision text nodes. For exact pictures/icons, use the selected external const/image node and optional mask/create node when supplied.
- Use script/python + script/exec only when it materially simplifies complex logic: loops, repeated UI operations, combined conditions, variable calculations, or tangled graph wiring. Keep simple click/wait/OCR/assert flows as visual nodes.
- When using Python scripts, pass external resources through script/exec inputs: devices, template pictures, masks, OCR engines, text, numbers, and booleans. Do not hard-code secrets, device settings, image names, or screen coordinates unless the user explicitly asks.
- Script business failures should usually call set_result('ok', boolean) and connect that bool to assert/check and test/result. Reserve raise for unexpected errors.
- AI-generated scripts must not use file, network, OS, subprocess, eval, exec, or package-install operations.
- Include a test/result node when the flow has a natural completion.
- Return a complete revised graph patch, not a diff.
- Use concise Chinese text when the user's case is Chinese; otherwise use the user's language.
"""


def _user_prompt(state: dict, docs: list[dict], previous_patch: dict | None,
                 skill_context: str | None = None) -> str:
    message = state.get("message") or ""
    history = state.get("history") or []
    hist = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}"
        for m in history[-12:] if m.get("content")
    )
    doc_text = "\n\n".join(
        f"### Document: {d['name']}\n{d['text']}" for d in docs
    ) or "(none)"
    prev = json.dumps(previous_patch, ensure_ascii=False, indent=2) if previous_patch else "(none)"
    values = state.get("form_values") or {}
    selected_graph_nodes = values.get("graph_nodes") or {}
    selected = json.dumps(selected_graph_nodes, ensure_ascii=False, indent=2) if selected_graph_nodes else "(none)"
    graph = state.get("current_graph") or {}
    graph_summary = json.dumps(_current_graph_summary(graph), ensure_ascii=False, indent=2)
    device_cfg = json.dumps(values.get("device_config") or {}, ensure_ascii=False, indent=2)
    skills = skill_context or _graph_skills_index_prompt()
    return (
        f"Graph Skills reference:\n{skills}\n\n"
        f"Current user instruction:\n{message or '(continue with supplied context)'}\n\n"
        f"Recent chat:\n{hist or '(none)'}\n\n"
        f"Uploaded test case documents:\n{doc_text}\n\n"
        f"Current canvas summary:\n{graph_summary}\n\n"
        f"Configured device, if current canvas has no device:\n{device_cfg}\n\n"
        f"Selected graph image/mask nodes:\n{selected}\n\n"
        f"Previous graph patch to modify, if any:\n{prev}\n\n"
        "Return the revised complete graph patch JSON now."
    )


def _extract_json(content: str):
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _graph_skills_index_prompt() -> str:
    root_doc = _read_skill_doc(GRAPH_SKILLS_ROOT / "DOC.md", 5000)
    catalog = node_catalog()
    category_index = _graph_skill_category_index(catalog)
    return (
        f"# Root\n{root_doc}\n\n"
        f"# Auto-generated category and node index\n{category_index}\n\n"
        "Detailed category DOC.md and node DOC.md are not loaded yet. "
        "Select the category names and node types you need to read before generating the patch."
    )[:_MAX_SKILL_CONTEXT_CHARS]


def _select_graph_skill_context(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
                                selected_graph_nodes: dict | None, lang: str) -> str:
    refs = _choose_graph_skill_refs(ai_cfg, state, docs, previous_patch, selected_graph_nodes or {}, lang)
    return _graph_skills_selected_prompt(refs)


def _choose_graph_skill_refs(ai_cfg: dict, state: dict, docs: list[dict], previous_patch: dict | None,
                             selected_graph_nodes: dict, lang: str) -> dict:
    client, params = _model_client_params(ai_cfg, lang)
    graph = state.get("current_graph") or {}
    payload = {
        "instruction": state.get("message") or "",
        "recent_chat": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in (state.get("history") or [])[-8:] if m.get("content")
        ],
        "documents": [{"name": d.get("name", ""), "text": (d.get("text") or "")[:5000]} for d in docs],
        "previous_graph_patch": previous_patch,
        "current_canvas": _current_graph_summary(graph),
        "selected_graph_nodes": selected_graph_nodes,
        "graph_skills_index": _graph_skills_index_prompt(),
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You select which Graph Skills documentation must be read before building a LiteGraph test "
                "flow. Return ONLY JSON: {\"categories\":[\"action\"], \"node_types\":[\"action/click\"]}. "
                "Choose the smallest useful set. Include nodes needed for data, device attributes, execution "
                "flow, waits, assertions, and result reporting when relevant. Include script/python and "
                "script/exec when the request mentions scripts/simplification/complex logic or needs loops, "
                "repeated UI actions, combined conditions, variable calculations, or otherwise tangled wiring."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        resp = client.chat.completions.create(**{**params, "messages": messages, "stream": False})
        content = (resp.choices[0].message.content or "").strip()
        obj = _extract_json(content)
    except Exception:
        obj = None
    refs = _normalize_skill_refs(obj if isinstance(obj, dict) else {})
    fallback = _heuristic_skill_refs(state, docs, previous_patch, selected_graph_nodes)
    refs["categories"] = _ordered_limited([*refs["categories"], *fallback["categories"]], _MAX_SELECTED_CATEGORIES)
    refs["node_types"] = _ordered_limited([*refs["node_types"], *fallback["node_types"]], _MAX_SELECTED_NODES)
    return refs


def _normalize_skill_refs(obj: dict) -> dict:
    category_names = _category_names()
    node_types = {spec["type"] for spec in node_catalog().get("nodes", [])}
    categories = [
        str(x).strip()
        for x in (obj.get("categories") or obj.get("read_categories") or [])
        if str(x).strip() in category_names
    ]
    selected_nodes = [
        str(x).strip()
        for x in (obj.get("node_types") or obj.get("nodes") or obj.get("read_nodes") or [])
        if str(x).strip() in node_types
    ]
    return {
        "categories": _ordered_limited(categories, _MAX_SELECTED_CATEGORIES),
        "node_types": _ordered_limited(selected_nodes, _MAX_SELECTED_NODES),
    }


def _ordered_limited(values: list[str], limit: int) -> list[str]:
    out = []
    seen = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
        if len(out) >= limit:
            break
    return out


def _category_names() -> set[str]:
    return {path.parent.name for path in GRAPH_SKILLS_ROOT.glob("*/DOC.md")}


def _graph_skills_selected_prompt(refs: dict) -> str:
    root_doc = _read_skill_doc(GRAPH_SKILLS_ROOT / "DOC.md", 5000)
    category_docs = []
    for name in refs.get("categories") or []:
        path = GRAPH_SKILLS_ROOT / name / "DOC.md"
        if path.exists():
            category_docs.append(f"## {name}\n{_read_skill_doc(path, 2200)}")
    node_docs = _node_docs_for_types(refs.get("node_types") or [])
    text = (
        f"# Root\n{root_doc}\n\n"
        f"# Selected category DOC.md\n{chr(10).join(category_docs) or '(none)'}\n\n"
        f"# Selected merged node documents\n{node_docs or '(none)'}"
    )
    return text[:_MAX_SKILL_CONTEXT_CHARS]


def _read_skill_doc(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except OSError:
        return ""


def _graph_skill_category_index(catalog: dict) -> str:
    grouped: dict[str, list[str]] = {}
    for spec in catalog.get("nodes", []):
        category = str(spec.get("category") or "未分类")
        grouped.setdefault(category, []).append(
            f"- `{spec.get('type')}`: {spec.get('title', '')} - {spec.get('description', '')}"
        )
    chunks = []
    for category in sorted(grouped):
        chunks.append(f"## {category}")
        chunks.extend(sorted(grouped[category]))
    return "\n".join(chunks)


def _port_summaries(ports: list[dict]) -> list[dict]:
    out = []
    for p in ports:
        out.append({
            "name": p.get("name"),
            "type": p.get("type"),
            "kind": p.get("kind"),
            "required": bool(p.get("required")),
            "desc": p.get("desc", ""),
        })
    return out


def _property_summaries(props: list[dict]) -> list[dict]:
    out = []
    for p in props:
        item = {
            "name": p.get("name"),
            "type": p.get("type"),
            "default": p.get("default"),
            "desc": p.get("desc", ""),
        }
        if p.get("options"):
            item["options"] = p.get("options")
        out.append(item)
    return out


def _render_node_skill_doc(spec: dict, doc_path: Path) -> str:
    """Merge structured node.json details with the handwritten usage DOC."""
    title = spec.get("title") or spec.get("type")
    lines = [
        f"# {title} ({spec.get('type')})",
        "",
        f"- 分类: {spec.get('category', '')}",
        f"- 说明: {spec.get('description', '')}",
    ]
    script = spec.get("script")
    if script:
        lines.append(f"- 脚本等价调用: `{script}`")
    functions = spec.get("functions") or []
    if functions:
        lines.extend(["", "## 可用函数"])
        for item in functions:
            lines.append(f"- `{item.get('sig', '')}`: {item.get('desc', '')}")
    injects = spec.get("injects") or []
    if injects:
        lines.extend(["", "## 注入对象"])
        for item in injects:
            lines.append(f"- `{item.get('name', '')}`: {item.get('desc', '')}")
    lines.extend(["", "## 输入端口"])
    lines.extend(_render_port_table(spec.get("inputs") or []))
    lines.extend(["", "## 输出端口"])
    lines.extend(_render_port_table(spec.get("outputs") or []))
    lines.extend(["", "## 参数"])
    lines.extend(_render_property_table(spec.get("properties") or []))
    usage = _usage_doc_text(doc_path, 5000)
    if usage:
        lines.extend(["", usage])
    return "\n".join(lines).strip()


def _usage_doc_text(path: Path, limit: int) -> str:
    text = _read_skill_doc(path, limit).strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines).strip()


def _render_port_table(ports: list[dict]) -> list[str]:
    if not ports:
        return ["无"]
    rows = ["| 名称 | 类型 | 种类 | 必选 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for p in ports:
        rows.append(
            f"| {p.get('name', '')} | {p.get('type', '')} | {p.get('kind', '')} | "
            f"{'是' if p.get('required') else '否'} | {p.get('desc', '')} |"
        )
    return rows


def _render_property_table(props: list[dict]) -> list[str]:
    if not props:
        return ["无"]
    rows = ["| 名称 | 类型 | 默认值 | 选项 | 说明 |", "| --- | --- | --- | --- | --- |"]
    for p in props:
        default = json.dumps(p.get("default", ""), ensure_ascii=False)
        options = ", ".join(str(x) for x in (p.get("options") or []))
        rows.append(
            f"| {p.get('name', '')} | {p.get('type', '')} | {default} | "
            f"{options} | {p.get('desc', '')} |"
        )
    return rows


def _heuristic_skill_refs(state: dict, docs: list[dict], previous_patch: dict | None,
                          selected_graph_nodes: dict) -> dict:
    message = state.get("message") or ""
    history = state.get("history") or []
    haystack = " ".join([
        message or "",
        " ".join(str(m.get("content", "")) for m in history[-12:]),
        " ".join(str(d.get("text", ""))[:3000] for d in docs),
        json.dumps(previous_patch or {}, ensure_ascii=False),
    ]).lower()
    selected: set[str] = set()
    keyword_types = {
        "text": ["vision/find_text", "const/text", "action/type", "assert/check", "test/result"],
        "文字": ["vision/find_text", "const/text", "action/type", "assert/check", "test/result"],
        "ocr": ["vision/find_text", "ocr/tesseract", "ocr/paddle"],
        "图片": ["vision/find_image", "const/image", "geom/to_point", "assert/check"],
        "image": ["vision/find_image", "const/image", "geom/to_point", "assert/check"],
        "点击": ["action/click", "geom/to_point", "test/result"],
        "click": ["action/click", "geom/to_point", "test/result"],
        "输入": ["action/type", "const/text"],
        "快捷键": ["action/hotkey"],
        "hotkey": ["action/hotkey"],
        "等待": ["wait/delay", "wait/appear", "wait/vanish"],
        "断言": ["assert/check", "test/result"],
        "assert": ["assert/check", "test/result"],
        "循环": ["flow/loop"],
        "条件": ["flow/if"],
        "变量": ["var/set", "var/get", "data/text_display"],
        "展示": ["data/text_display", "var/get"],
        "显示": ["data/text_display", "var/get"],
        "查看": ["data/text_display", "var/get", "util/log"],
        "display": ["data/text_display", "var/get"],
        "脚本": ["script/python", "script/exec"],
        "script": ["script/python", "script/exec"],
        "python": ["script/python", "script/exec"],
        "复杂": ["script/python", "script/exec", "assert/check", "test/result"],
        "简化": ["script/python", "script/exec", "assert/check", "test/result"],
        "重复": ["script/python", "script/exec"],
        "计算": ["script/python", "script/exec", "assert/check"],
        "complex": ["script/python", "script/exec", "assert/check", "test/result"],
        "simplify": ["script/python", "script/exec", "assert/check", "test/result"],
        "repeat": ["script/python", "script/exec"],
        "api": ["api/request", "api/json_serialize", "const/text", "assert/check", "test/result"],
        "http": ["api/request", "api/json_serialize", "const/text", "assert/check", "test/result"],
        "请求": ["api/request", "api/json_serialize", "const/text", "assert/check", "test/result"],
        "接口": ["api/request", "api/json_serialize", "const/text", "assert/check", "test/result"],
        "网络": ["api/request", "api/json_serialize", "const/text", "assert/check", "test/result"],
        "json": ["api/json_serialize", "api/request", "script/python", "script/exec"],
        "表单": ["api/form_serialize", "api/request"],
        "form": ["api/form_serialize", "api/request"],
        "urlencoded": ["api/form_serialize", "api/request"],
    }
    for key, types in keyword_types.items():
        if key in haystack:
            selected.update(types)
    for base in ("flow/start", "test/result", "device/attrs", "util/log"):
        selected.add(base)
    if selected_graph_nodes.get("image_node_id"):
        selected.update(["const/image", "vision/find_image", "geom/to_point", "action/click"])
    if selected_graph_nodes.get("mask_node_id"):
        selected.update(["mask/create", "vision/find_image"])
    if previous_patch:
        for node in previous_patch.get("nodes") or []:
            if isinstance(node, dict) and node.get("type"):
                selected.add(str(node["type"]))
    type_to_category = {
        spec["type"]: _category_dir_for_spec(spec)
        for spec in node_catalog().get("nodes", [])
    }
    categories = [c for ntype in selected if (c := type_to_category.get(ntype))]
    return {
        "categories": _ordered_limited(categories, _MAX_SELECTED_CATEGORIES),
        "node_types": _ordered_limited(list(selected), _MAX_SELECTED_NODES),
    }


def _node_docs_for_types(node_types: list[str]) -> str:
    doc_chunks = []
    catalog_nodes = node_catalog().get("nodes", [])
    type_to_dir = {spec["type"]: spec["type"].replace("/", "_") for spec in catalog_nodes}
    type_to_spec = {spec["type"]: spec for spec in catalog_nodes}
    for ntype in node_types:
        dirname = type_to_dir.get(ntype)
        if not dirname:
            continue
        paths = list(GRAPH_SKILLS_ROOT.glob(f"*/{dirname}/DOC.md"))
        if paths:
            doc_chunks.append(_render_node_skill_doc(type_to_spec[ntype], paths[0]))
    return "\n\n".join(doc_chunks)[:24000]


def _category_dir_for_spec(spec: dict) -> str | None:
    dirname = str(spec.get("type", "")).replace("/", "_")
    for path in GRAPH_SKILLS_ROOT.glob(f"*/{dirname}/node.json"):
        return path.parent.parent.name
    return None


def _current_graph_summary(graph: dict) -> dict:
    nodes = []
    for node in graph.get("nodes") or []:
        props = _sanitize_props(node.get("properties") or {})
        nodes.append({
            "id": node.get("id"),
            "external_ref": f"external:{node.get('id')}",
            "type": node.get("type"),
            "title": node.get("title") or "",
            "properties": props,
        })
    return {
        "nodes": nodes,
        "has_device": _has_device_source(graph),
        "unused_start_node_id": _start_available(graph),
        "available_graph_nodes": _available_graph_nodes(graph),
    }


def _normalize_graph_patch(obj: dict) -> dict:
    if isinstance(obj.get("graph_patch"), dict):
        obj = obj["graph_patch"]
    nodes = obj.get("nodes") or []
    links = obj.get("links") or []
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(links, list):
        links = []
    out = {
        "title": str(obj.get("title") or "AI 生成测试流程")[:80],
        "summary": str(obj.get("summary") or "")[:1200],
        "nodes": [],
        "links": [],
        "entry": str(obj.get("entry") or "")[:120],
    }
    for raw in nodes[:90]:
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or "").strip()
        ntype = str(raw.get("type") or "").strip()
        if not nid or not ntype:
            continue
        pos = raw.get("pos")
        if not (isinstance(pos, list) and len(pos) >= 2):
            pos = None
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        item = {"id": nid[:120], "type": ntype, "properties": props}
        if raw.get("title"):
            item["title"] = str(raw.get("title"))[:120]
        if pos:
            item["pos"] = [_num(pos[0], 120), _num(pos[1], 330)]
        inputs = _normalize_patch_ports(raw.get("inputs"))
        outputs = _normalize_patch_ports(raw.get("outputs"))
        if inputs:
            item["inputs"] = inputs
        if outputs:
            item["outputs"] = outputs
        out["nodes"].append(item)
    for raw in links[:180]:
        if not isinstance(raw, dict):
            continue
        item = {
            "from": str(raw.get("from") or "").strip()[:120],
            "out": str(raw.get("out") or "").strip()[:80],
            "to": str(raw.get("to") or "").strip()[:120],
            "in": str(raw.get("in") or "").strip()[:80],
            "optional": bool(raw.get("optional", False)),
        }
        if item["from"] and item["out"] and item["to"] and item["in"]:
            out["links"].append(item)
    if not out["entry"] and out["nodes"]:
        out["entry"] = out["nodes"][0]["id"]
    return out


def _normalize_patch_ports(raw_ports: Any) -> list[dict]:
    if not isinstance(raw_ports, list):
        return []
    ports = []
    for raw in raw_ports[:40]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:80]
        ptype = str(raw.get("type") or "").strip()[:40]
        if name and ptype:
            ports.append({"name": name, "type": ptype})
    return ports


def _has_device_source(graph: dict) -> bool:
    return any((n.get("type") in _DEVICE_TYPES) for n in (graph.get("nodes") or []))


def _first_node(graph: dict, ntype: str) -> dict | None:
    for node in graph.get("nodes") or []:
        if node.get("type") == ntype:
            return node
    return None


def _first_device_source(graph: dict) -> dict | None:
    for node in graph.get("nodes") or []:
        if node.get("type") in _DEVICE_TYPES:
            return node
    return None


def _start_available(graph: dict) -> int | None:
    for node in graph.get("nodes") or []:
        if node.get("type") != "flow/start":
            continue
        out = next((o for o in (node.get("outputs") or []) if o.get("name") == "out"), None)
        if not (out or {}).get("links"):
            return int(node.get("id"))
    return None


class _GraphPatchCompiler:
    def __init__(self, current_graph: dict, device_config: dict, ai_config: dict,
                 graph_nodes: dict, lang: str = "zh") -> None:
        self.current_graph = current_graph
        self.device_config = device_config
        self.ai_config = ai_config
        self.graph_nodes = graph_nodes
        self.lang = lang
        self.catalog = {n["type"]: n for n in node_catalog().get("nodes", [])}
        self.current_specs = {
            f"external:{n.get('id')}": self._effective_spec_for_existing_node(n)
            for n in current_graph.get("nodes") or []
            if n.get("id") is not None
        }

    def compile(self, patch: dict) -> dict:
        nodes = [self._normalize_node(n) for n in patch.get("nodes") or []]
        nodes = [n for n in nodes if n]
        if not nodes:
            raise AIBuilderError(tr(self.lang, "ai_builder.empty_graph_patch",
                                    "模型没有生成任何可用的 Graph Skills 节点。"))
        local_specs = {n["id"]: self._effective_spec_for_node(n) for n in nodes}
        links = self._normalize_links(patch.get("links") or [], local_specs)
        entry = self._valid_entry(patch.get("entry"), local_specs)
        start_external = _start_available(self.current_graph) if entry else None
        if self._has_generated_start(nodes):
            start_external = None
        notes = []
        if start_external is not None:
            notes.append(tr(self.lang, "ai_builder.note_connect_start",
                            "应用时会尝试连接到当前空闲的「开始」节点。"))
        elif _first_node(self.current_graph, "flow/start") and entry:
            notes.append(tr(self.lang, "ai_builder.note_manual_connect",
                            "当前画布已有正在使用的「开始」节点，草稿会保持未接入，应用后可手动连接入口。"))
        return {
            "title": patch.get("title") or tr(self.lang, "ai_builder.default_title", "AI 生成测试流程"),
            "summary": patch.get("summary") or "",
            "graph_patch": patch,
            "dsl": patch,
            "nodes": nodes,
            "links": links,
            "entry": entry,
            "auto_connect_start": start_external,
            "notes": notes,
            "stats": {"nodes": len(nodes), "links": len(links), "steps": len(nodes)},
        }

    def _normalize_node(self, raw: dict) -> dict | None:
        if not isinstance(raw, dict):
            return None
        nid = str(raw.get("id") or "").strip()
        ntype = str(raw.get("type") or "").strip()
        if not nid or nid.startswith("external:"):
            raise AIBuilderError(tr(self.lang, "ai_builder.bad_graph_patch",
                                    "模型生成了非法节点 id：{value}", value=nid or "(empty)"))
        if ntype not in self.catalog:
            raise AIBuilderError(tr(self.lang, "ai_builder.bad_graph_patch",
                                    "模型使用了不存在的节点类型：{value}", value=ntype))
        pos = raw.get("pos")
        if not (isinstance(pos, list) and len(pos) >= 2):
            pos = [120, 330]
        props = self._normalize_properties(ntype, raw.get("properties") or {})
        inputs = self._normalize_dynamic_ports(ntype, "inputs", raw.get("inputs"))
        outputs = self._normalize_dynamic_ports(ntype, "outputs", raw.get("outputs"))
        node = {
            "id": nid,
            "type": ntype,
            "title": str(raw.get("title") or "")[:120],
            "pos": [_num(pos[0], 120), _num(pos[1], 330)],
            "properties": props,
        }
        if inputs:
            node["inputs"] = inputs
        if outputs:
            node["outputs"] = outputs
        return node

    def _normalize_properties(self, ntype: str, raw_props: dict) -> dict:
        spec = self.catalog[ntype]
        allowed = {p.get("name"): p for p in spec.get("properties") or [] if p.get("name")}
        out = {}
        for name, value in (raw_props or {}).items():
            if name not in allowed:
                continue
            prop = allowed[name]
            out[name] = self._coerce_property(value, prop)
        if ntype == (self.device_config.get("type") or ""):
            for name, value in _sanitize_props(self.device_config.get("properties") or {}).items():
                if name in allowed and name not in out:
                    out[name] = self._coerce_property(value, allowed[name])
        if ntype == "script/python":
            errors = check_syntax(str(out.get("code") or ""), lang=self.lang)
            if errors:
                message = errors[0].get("message") or "syntax error"
                line = errors[0].get("line") or 1
                raise AIBuilderError(tr(
                    self.lang, "ai_builder.bad_graph_patch",
                    "模型生成了无效流程：{value}", value=f"script/python code line {line}: {message}"))
        return _sanitize_props(out)

    def _normalize_dynamic_ports(self, ntype: str, group: str, raw_ports: Any) -> list[dict]:
        ports = _normalize_patch_ports(raw_ports)
        if not ports:
            return []
        if ntype not in {"script/exec", "script/js_exec"}:
            raise AIBuilderError(tr(
                self.lang, "ai_builder.bad_graph_patch",
                "模型生成了无效流程：{value}", value=f"{ntype} cannot declare dynamic ports"))
        static = self.catalog[ntype].get(group) or []
        static_by_name = {p.get("name"): p for p in static}
        reserved = set(static_by_name)
        seen = set()
        out = []
        for port in ports:
            name = port["name"]
            ptype = port["type"]
            if name in seen:
                raise AIBuilderError(tr(
                    self.lang, "ai_builder.bad_graph_patch",
                    "模型生成了无效流程：{value}", value=f"duplicate dynamic port {name}"))
            seen.add(name)
            if name in static_by_name:
                if static_by_name[name].get("type") == ptype:
                    continue
                raise AIBuilderError(tr(
                    self.lang, "ai_builder.bad_graph_patch",
                    "模型生成了无效流程：{value}", value=f"cannot override fixed port {name}"))
            if name in reserved or ptype == "exec" or ptype not in _SCRIPT_EXEC_DYNAMIC_TYPES:
                raise AIBuilderError(tr(
                    self.lang, "ai_builder.bad_graph_patch",
                    "模型生成了无效流程：{value}", value=f"invalid dynamic port {name}:{ptype}"))
            out.append({"name": name, "type": ptype})
        return out

    def _effective_spec_for_node(self, node: dict) -> dict:
        spec = self.catalog[node["type"]]
        if node["type"] not in {"script/exec", "script/js_exec"}:
            return spec
        merged = dict(spec)
        merged["inputs"] = [*(spec.get("inputs") or []), *(node.get("inputs") or [])]
        merged["outputs"] = [*(spec.get("outputs") or []), *(node.get("outputs") or [])]
        return merged

    def _effective_spec_for_existing_node(self, node: dict) -> dict | None:
        spec = self.catalog.get(node.get("type"))
        if not spec:
            return None
        if node.get("type") not in {"script/exec", "script/js_exec"}:
            return spec
        merged = dict(spec)
        static_inputs = {p.get("name") for p in spec.get("inputs") or []}
        static_outputs = {p.get("name") for p in spec.get("outputs") or []}
        dyn_inputs = [
            {"name": p.get("name"), "type": p.get("type")}
            for p in node.get("inputs") or []
            if p.get("name") and p.get("type") and p.get("name") not in static_inputs
        ]
        dyn_outputs = [
            {"name": p.get("name"), "type": p.get("type")}
            for p in node.get("outputs") or []
            if p.get("name") and p.get("type") and p.get("name") not in static_outputs
        ]
        merged["inputs"] = [*(spec.get("inputs") or []), *dyn_inputs]
        merged["outputs"] = [*(spec.get("outputs") or []), *dyn_outputs]
        return merged

    def _coerce_property(self, value, prop: dict):
        ptype = prop.get("type")
        if ptype == "bool":
            return bool(value)
        if ptype == "int":
            return int(_num(value, prop.get("default", 0)))
        if ptype == "number":
            return _num(value, prop.get("default", 0))
        if ptype == "enum":
            options = prop.get("options") or []
            return value if value in options else prop.get("default", options[0] if options else "")
        return "" if prop.get("name") in _SENSITIVE_PROPS else (value if value is not None else prop.get("default", ""))

    def _normalize_links(self, raw_links: list[dict], local_specs: dict[str, dict]) -> list[dict]:
        links = []
        for raw in raw_links:
            if not isinstance(raw, dict):
                continue
            link = {
                "from": str(raw.get("from") or "").strip(),
                "out": str(raw.get("out") or "").strip(),
                "to": str(raw.get("to") or "").strip(),
                "in": str(raw.get("in") or "").strip(),
                "optional": bool(raw.get("optional", False)),
            }
            try:
                self._validate_link(link, local_specs)
            except AIBuilderError:
                if link["optional"]:
                    continue
                raise
            links.append(link)
        return links

    def _validate_link(self, link: dict, local_specs: dict[str, dict]) -> None:
        src_spec = self._spec_for_ref(link["from"], local_specs)
        dst_spec = self._spec_for_ref(link["to"], local_specs)
        if not src_spec or not dst_spec:
            raise AIBuilderError(tr(self.lang, "ai_builder.bad_graph_patch",
                                    "模型连线引用了不存在的节点：{value}",
                                    value=f"{link['from']} -> {link['to']}"))
        out_port = self._port(src_spec, "outputs", link["out"])
        in_port = self._port(dst_spec, "inputs", link["in"])
        if not out_port or not in_port:
            raise AIBuilderError(tr(self.lang, "ai_builder.bad_graph_patch",
                                    "模型连线使用了不存在的端口：{value}",
                                    value=f"{src_spec['type']}.{link['out']} -> {dst_spec['type']}.{link['in']}"))
        if not T.compatible(str(out_port.get("type")), str(in_port.get("type"))):
            raise AIBuilderError(tr(self.lang, "ai_builder.bad_graph_patch",
                                    "模型连线端口类型不兼容：{value}",
                                    value=f"{out_port.get('type')} -> {in_port.get('type')}"))

    def _spec_for_ref(self, ref: str, local_specs: dict[str, dict]) -> dict | None:
        if ref in local_specs:
            return local_specs[ref]
        if ref in self.current_specs:
            return self.current_specs[ref]
        return None

    def _port(self, spec: dict, group: str, name: str) -> dict | None:
        for port in spec.get(group) or []:
            if port.get("name") == name:
                return port
        return None

    def _valid_entry(self, entry: str | None, local_specs: dict[str, dict]) -> str | None:
        if entry and entry in local_specs:
            spec = local_specs[entry]
            if any(p.get("name") == "in" and p.get("type") == "exec" for p in spec.get("inputs") or []):
                return entry
        for nid, spec in local_specs.items():
            if any(p.get("name") == "in" and p.get("type") == "exec" for p in spec.get("inputs") or []):
                return nid
        return None

    def _has_generated_start(self, nodes: list[dict]) -> bool:
        return any(n.get("type") == "flow/start" for n in nodes)


_AI_BUILD_TOOLS = {
    "inspect_canvas": "read",
    "list_node_types": "read",
    "read_node_spec": "read",
    "create_node": "write",
    "set_node_property": "write",
    "set_node_ports": "write",
    "connect_nodes": "write",
    "delete_node": "write",
    "delete_link": "write",
    "validate_canvas": "read",
    "finish_build": "read",
}


def ai_build_tool_schemas(lang: str = "zh") -> list[dict]:
    """Return OpenAI-compatible canvas tool schemas for direct AI building."""
    def tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        }

    ref_desc = "Node reference. Use n1/n2 handles returned by create_node, or external:<canvas_node_id>."
    port_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": sorted(_SCRIPT_EXEC_DYNAMIC_TYPES),
                },
            },
            "required": ["name", "type"],
            "additionalProperties": False,
        },
    }
    return [
        tool("inspect_canvas", "Read the current LiteGraph canvas summary and known handles.", {
            "include_existing": {"type": "boolean", "default": True},
            "include_created": {"type": "boolean", "default": True},
        }),
        tool("list_node_types", "List available graph node types from the node catalog, optionally by category.", {
            "category": {"type": "string", "description": "Optional category, e.g. flow, action, vision."},
        }),
        tool("read_node_spec", "Read one node type's inputs, outputs, properties, and usage summary.", {
            "type": {"type": "string", "description": "Node type, e.g. action/click."},
        }, ["type"]),
        tool("create_node", "Create a real LiteGraph node on the user's canvas.", {
            "type": {"type": "string"},
            "title": {"type": "string"},
            "pos": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "properties": {"type": "object"},
        }, ["type"]),
        tool("set_node_property", "Set a property on an existing canvas node.", {
            "ref": {"type": "string", "description": ref_desc},
            "name": {"type": "string"},
            "value": {},
        }, ["ref", "name", "value"]),
        tool("set_node_ports", "Set dynamic data inputs and result outputs on a script/exec node.", {
            "ref": {"type": "string", "description": ref_desc},
            "inputs": port_schema,
            "outputs": port_schema,
        }, ["ref"]),
        tool("connect_nodes", "Connect two nodes by named output/input ports.", {
            "from": {"type": "string", "description": ref_desc},
            "out": {"type": "string"},
            "to": {"type": "string", "description": ref_desc},
            "in": {"type": "string"},
            "optional": {"type": "boolean", "default": False},
        }, ["from", "out", "to", "in"]),
        tool("delete_node", "Delete a node from the real canvas.", {
            "ref": {"type": "string", "description": ref_desc},
        }, ["ref"]),
        tool("delete_link", "Delete a link by endpoint references and port names.", {
            "from": {"type": "string", "description": ref_desc},
            "out": {"type": "string"},
            "to": {"type": "string", "description": ref_desc},
            "in": {"type": "string"},
        }, ["from", "out", "to", "in"]),
        tool("validate_canvas", "Validate current canvas structure after edits.", {}),
        tool("finish_build", "Declare the build complete. The frontend will validate before final completion.", {
            "summary": {"type": "string"},
        }, ["summary"]),
    ]


def build_ai_build_messages(init: dict, docs: list[dict], session: dict, lang: str = "zh") -> list[dict]:
    """Build model messages for direct canvas tool-calling mode."""
    message = init.get("message") or ""
    history = init.get("history") or session.get("messages") or []
    graph_summary = _current_graph_summary(init.get("current_graph") or {})
    rejected = ((session.get("build_state") or {}).get("rejected_operations") or [])[-8:]
    doc_text = "\n\n".join(f"### {d.get('name', 'case.txt')}\n{(d.get('text') or '')[:6000]}" for d in docs) or "(none)"
    payload = {
        "user_instruction": message,
        "recent_chat": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in history[-16:] if isinstance(m, dict) and m.get("content")
        ],
        "documents": doc_text,
        "current_canvas_summary": graph_summary,
        "form_values": init.get("form_values") or {},
        "soft_rejected_operations": rejected,
    }
    system = """
You are an expert QA automation flow builder operating a real LiteGraph canvas through tools.
Do not output a final graph JSON. Build the graph step by step by calling tools.
Use list_node_types and read_node_spec before creating unfamiliar nodes. Use only node types, ports, and properties from the catalog.
Write tools mutate the user's actual canvas and may require confirmation. If a tool fails, inspect/read specs and repair with different parameters.
If a user previously rejected an operation, treat it as a soft hint and avoid repeating it unless the user explicitly changed requirements.
For HTTP/API calls, use api/request and connect its status/body/ok outputs to logs, scripts, assertions, or result nodes as needed. Use JSON/form serialization nodes for request/response conversion. Do not put network calls inside Python scripts.
Use script/python + script/exec only when it materially simplifies complex logic: loops, repeated UI operations, combined conditions, variable calculations, or tangled graph wiring. Keep simple click/wait/OCR/assert flows as visual nodes.
When using scripts, create script/python and script/exec, call set_node_ports on script/exec for resource inputs and bool/text/etc result outputs, then connect resources and assertions. Pass devices, template pictures, masks, OCR engines, text, numbers, and booleans through ports instead of hard-coding them.
Script business failures should usually set_result('ok', boolean) and connect that result to assert/check and test/result. Reserve raise for unexpected errors.
AI-generated scripts must not use file, network, OS, subprocess, eval, exec, or package-install operations.
When the graph is structurally complete, call finish_build with a concise summary. The frontend will run validate_canvas; repair any validation errors.
Never ask the frontend to run the test flow. Do not include hidden reasoning; short visible status messages are enough.
""".strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def run_ai_build_loop(
    init: dict,
    docs: list[dict],
    session: dict,
    send_tool_call: Callable[[dict], Awaitable[None]],
    wait_tool_result: Callable[[str], Awaitable[dict]],
    on_event: Callable[[dict], Awaitable[None]],
    should_stop: Callable[[], bool],
    lang: str = "zh",
) -> dict:
    """Run the backend model loop for WebSocket direct AI building."""
    ai_cfg = init.get("ai_settings") or ((init.get("form_values") or {}).get("ai_settings") or {})
    _require_ai_config(ai_cfg, lang)
    client, params_base = _model_client_params(ai_cfg, lang)
    messages = build_ai_build_messages(init, docs, session, lang)
    limits = init.get("limits") or {}
    max_tool_calls = int(limits.get("max_tool_calls") or ai_cfg.get("max_tool_calls") or 40)
    max_repair_rounds = int(limits.get("max_repair_rounds") or ai_cfg.get("max_repair_rounds") or 5)
    timeout_seconds = float(limits.get("timeout_seconds") or ai_cfg.get("timeout_seconds") or 120)
    retry_attempts = int(limits.get("retry_attempts") or ai_cfg.get("retry_attempts") or 3)
    deadline = time.monotonic() + max(5, timeout_seconds)
    tool_count = 0
    repair_rounds = 0
    last_failed_key = ""
    summary = ""

    await on_event({"type": "status", "status": "running", "message": tr(lang, "ai_builder.ws.running", "正在搭建流程...")})
    while True:
        if should_stop():
            raise AIBuilderStopped("user_stop")
        if time.monotonic() > deadline:
            raise AIBuilderStopped("timeout")
        if tool_count >= max_tool_calls:
            raise AIBuilderStopped("max_tool_calls")

        params = {
            **params_base,
            "messages": messages,
            "tools": ai_build_tool_schemas(lang),
            "tool_choice": "auto",
        }
        resp = await _chat_create_with_retry_async(
            client, params, lang, on_event=on_event, should_stop=should_stop,
            attempts=max(1, min(10, retry_attempts)))
        msg = resp.choices[0].message
        usage = _usage_dict(getattr(resp, "usage", None))
        if usage:
            await on_event({"type": "usage", "usage": usage})
        tool_calls = getattr(msg, "tool_calls", None) or []
        content = (getattr(msg, "content", None) or "").strip()
        messages.append(_message_to_dict(msg))
        if content:
            await on_event({"type": "message", "role": "assistant", "content": content})
        if not tool_calls:
            raise AIBuilderError(tr(lang, "ai_builder.ws.no_tool_call",
                                    "当前模型没有发起工具调用，无法使用 AI 直接搭建。请更换支持 tool calling 的模型或接口。"))

        for call in tool_calls:
            if should_stop():
                raise AIBuilderStopped("user_stop")
            if tool_count >= max_tool_calls:
                raise AIBuilderStopped("max_tool_calls")
            fn = getattr(call, "function", None)
            tool_name = getattr(fn, "name", "")
            raw_args = getattr(fn, "arguments", "") or "{}"
            try:
                args = json.loads(raw_args)
            except Exception:
                args = {}
            call_id = getattr(call, "id", "") or f"call_{tool_count + 1}"
            risk = _AI_BUILD_TOOLS.get(tool_name, "read")
            if tool_name not in _AI_BUILD_TOOLS:
                result = {"ok": False, "error": {"code": "UNKNOWN_TOOL", "message": f"unknown tool: {tool_name}"}}
            else:
                failed_key = _tool_call_key(tool_name, args)
                if failed_key and failed_key == last_failed_key:
                    result = {
                        "ok": False,
                        "error": {
                            "code": "DUPLICATE_FAILED_CALL",
                            "message": tr(lang, "ai_builder.ws.duplicate_failed_call",
                                          "相同工具调用刚刚失败，请先 inspect/read_node_spec 或更换参数/方案。"),
                        },
                    }
                else:
                    await send_tool_call({
                        "type": "tool_call",
                        "id": call_id,
                        "tool": tool_name,
                        "risk": risk,
                        "args": args,
                    })
                    tool_event = await wait_tool_result(call_id)
                    if tool_event.get("status") == "rejected":
                        await on_event({"type": "tool_step", "step": _tool_log(tool_name, args, tool_event, call_id)})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": json.dumps(tool_event.get("result") or {}, ensure_ascii=False),
                        })
                        return {"status": "stopped", "reason": "user_rejected", "summary": summary}
                    result = tool_event.get("result") if isinstance(tool_event.get("result"), dict) else tool_event
                    await on_event({"type": "tool_step", "step": _tool_log(tool_name, args, tool_event, call_id)})
                    if tool_name == "finish_build":
                        summary = str(args.get("summary") or summary or "")
            tool_count += 1
            ok = bool(isinstance(result, dict) and result.get("ok"))
            if ok:
                last_failed_key = ""
            else:
                last_failed_key = _tool_call_key(tool_name, args)
                repair_rounds += 1
                if repair_rounds > max_repair_rounds:
                    raise AIBuilderStopped("max_repair_rounds")
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            })
            if tool_name == "finish_build" and ok:
                return {"status": "completed", "summary": summary or tr(lang, "ai_builder.ws.completed", "流程已搭建完成。")}


def _tool_call_key(tool: str, args: dict) -> str:
    try:
        return tool + ":" + json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
    except Exception:
        return tool


def _tool_log(tool: str, args: dict, event: dict, call_id: str = "") -> dict:
    status = event.get("status") or ("ok" if (event.get("result") or {}).get("ok") else "error")
    return {
        "call_id": call_id,
        "tool": tool,
        "args": _redact_tool_payload(args),
        "result": _redact_tool_payload(event.get("result") or {}),
        "status": status,
        "time": time.time(),
    }


def _redact_tool_payload(value, depth: int = 0):
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            skey = str(key)
            if skey.lower() in _SENSITIVE_PROPS:
                out[skey] = "***"
            else:
                out[skey] = _redact_tool_payload(item, depth + 1)
        return out
    if isinstance(value, list):
        if len(value) > 80:
            return [_redact_tool_payload(v, depth + 1) for v in value[:80]] + [f"... {len(value) - 80} more"]
        return [_redact_tool_payload(v, depth + 1) for v in value]
    if isinstance(value, str):
        if len(value) > 1200:
            return value[:1200] + f"... [truncated {len(value) - 1200} chars]"
        if len(value) > 200 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", value or ""):
            return value[:80] + "... [base64-like truncated]"
    return value
def _selected_node_ref(graph: dict, values: dict, key: str, expected_type: str) -> str | None:
    raw = values.get(key)
    if raw in (None, ""):
        return None
    try:
        node_id = int(raw)
    except (TypeError, ValueError):
        return None
    for node in graph.get("nodes") or []:
        if int(node.get("id", -1)) == node_id and node.get("type") == expected_type:
            return f"external:{node_id}"
    return None


def _sanitize_props(props: dict) -> dict:
    out = {}
    for key, value in (props or {}).items():
        out[key] = "" if key in _SENSITIVE_PROPS else value
    return out


def _num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
