"""AI-assisted test flow planning.

The builder keeps the model-facing format intentionally small: the LLM returns a
checked step DSL, and this module compiles it into a LiteGraph-compatible draft
that the frontend can preview and insert.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from ..i18n import tr
from .catalog import node_catalog


_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
_DEVICE_TYPES = {"device/local", "device/novnc", "device/rdp", "device/pve", "device/vmware"}
_SENSITIVE_PROPS = {"api_key", "password", "token", "secret"}
_MAX_DOC_CHARS = 28000


class AIBuilderError(RuntimeError):
    """Raised for user-facing AI builder failures."""


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
    previous_dsl = state.get("draft_dsl") or None
    dsl = _ask_model(ai_cfg, state, docs, previous_dsl, lang)
    draft = compile_dsl(dsl, graph, device_cfg, ai_cfg, lang=lang)
    return {
        "message": tr(lang, "ai_builder.draft_ready", "已生成流程草稿，你可以预览后应用到画布，或继续描述修改。"),
        "forms": [],
        "draft": draft,
    }


def compile_dsl(dsl: dict, current_graph: dict | None = None, device_config: dict | None = None,
                ai_config: dict | None = None, lang: str = "zh") -> dict:
    compiler = _DraftCompiler(current_graph or {}, device_config or {}, ai_config or {}, lang)
    return compiler.compile(dsl or {})


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


def _ask_model(ai_cfg: dict, state: dict, docs: list[dict], previous_dsl: dict | None,
               lang: str) -> dict:
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

    client = OpenAI(base_url=base_url, api_key=api_key or "none")
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(state, docs, previous_dsl)},
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    obj = _extract_json(content)
    if not isinstance(obj, dict):
        raise AIBuilderError(tr(lang, "ai_builder.bad_model_json",
                                "模型没有返回可解析的流程 JSON：{snippet}", snippet=content[:200]))
    return _normalize_dsl(obj)


_SYSTEM_PROMPT = """You are an expert QA automation flow planner for a LiteGraph-based UI testing tool.
Return ONLY a compact JSON object. No prose, no markdown fences.

You create a sequential test flow DSL. Do not output LiteGraph node JSON.
Supported JSON shape:
{
  "title": "short test name",
  "summary": "what the flow does",
  "steps": [
    {"action":"log","message":"..."},
    {"action":"wait_seconds","seconds":1},
    {"action":"wait_text","text":"...", "method":"ocr|ai", "timeout":10},
    {"action":"click_text","text":"...", "method":"ocr|ai", "timeout":10, "button":"left", "double":false},
    {"action":"click_ai","description":"visual target description", "timeout":10, "button":"left", "double":false},
    {"action":"type","text":"...", "paste":true},
    {"action":"hotkey","keys":"enter|tab|ctrl+c|ctrl+shift+t"},
    {"action":"scroll_text","text":"...", "method":"ocr|ai", "dy":-3, "timeout":10},
    {"action":"assert_text","text":"...", "method":"ocr|ai", "timeout":10, "message":"..."},
    {"action":"assert_ai","description":"...", "kind":"image|text", "timeout":10, "message":"..."}
  ]
}
Rules:
- Keep it sequential. Do not create loops, custom Python, or tool-calling agents.
- Prefer OCR for exact visible text; use AI for visual elements/icons or semantic descriptions.
- If a click target is a visible label, use click_text.
- Insert short waits only when the case implies loading or transitions.
- Assertions should validate the expected final or important intermediate UI state.
- Use concise Chinese text when the user's case is Chinese; otherwise use the user's language.
"""


def _user_prompt(state: dict, docs: list[dict], previous_dsl: dict | None) -> str:
    message = state.get("message") or ""
    history = state.get("history") or []
    hist = "\n".join(
        f"{m.get('role', 'user')}: {m.get('content', '')}"
        for m in history[-12:] if m.get("content")
    )
    doc_text = "\n\n".join(
        f"### Document: {d['name']}\n{d['text']}" for d in docs
    ) or "(none)"
    prev = json.dumps(previous_dsl, ensure_ascii=False, indent=2) if previous_dsl else "(none)"
    return (
        f"Current user instruction:\n{message or '(continue with supplied context)'}\n\n"
        f"Recent chat:\n{hist or '(none)'}\n\n"
        f"Uploaded test case documents:\n{doc_text}\n\n"
        f"Previous draft DSL to modify, if any:\n{prev}\n\n"
        "Return the revised complete DSL JSON now."
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


def _normalize_dsl(obj: dict) -> dict:
    steps = obj.get("steps") or []
    if not isinstance(steps, list):
        steps = []
    out = {
        "title": str(obj.get("title") or "AI 生成测试流程")[:80],
        "summary": str(obj.get("summary") or "")[:1200],
        "steps": [],
    }
    for raw in steps[:40]:
        if not isinstance(raw, dict):
            continue
        step = dict(raw)
        action = str(step.get("action") or "").strip()
        if not action:
            continue
        step["action"] = action
        out["steps"].append(step)
    if not out["steps"]:
        out["steps"].append({"action": "log", "message": out["summary"] or out["title"]})
    return out


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


@dataclass
class _DraftCompiler:
    current_graph: dict
    device_config: dict
    ai_config: dict
    lang: str = "zh"
    nodes: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)
    _seq: int = 0
    _cursor_x: int = 120
    _flow_y: int = 330
    _data_y: int = 90
    attrs_ref: str | None = None
    ai_ref: str | None = None

    def compile(self, dsl: dict) -> dict:
        self._ensure_device()
        needs_ai = self._needs_runtime_ai(dsl)
        if needs_ai:
            self._ensure_ai()

        start_id = None
        start_external = _start_available(self.current_graph)
        if start_external is None and not _first_node(self.current_graph, "flow/start"):
            start_id = self.node("flow/start", pos=[self._cursor_x, self._flow_y])
            self._cursor_x += 260

        first_exec = None
        prev_exec = start_id
        prev_out = "out"
        for step in dsl.get("steps") or []:
            built = self._build_step(step)
            if not built:
                continue
            entry, exit_node, exit_out = built
            if first_exec is None:
                first_exec = entry
            if prev_exec is not None:
                self.link(prev_exec, prev_out, entry, "in")
            prev_exec, prev_out = exit_node, exit_out

        if first_exec is None:
            first_exec = self._log_step(dsl.get("summary", "") or dsl.get("title", ""))
            if prev_exec is not None:
                self.link(prev_exec, prev_out, first_exec, "in")
            prev_exec, prev_out = first_exec, "out"

        result = self.node("test/result", pos=[self._cursor_x, self._flow_y])
        if prev_exec is not None:
            self.link(prev_exec, prev_out, result, "in")

        notes = []
        if start_external is not None:
            notes.append(tr(self.lang, "ai_builder.note_connect_start",
                            "应用时会尝试连接到当前空闲的「开始」节点。"))
        elif _first_node(self.current_graph, "flow/start"):
            notes.append(tr(self.lang, "ai_builder.note_manual_connect",
                            "当前画布已有正在使用的「开始」节点，草稿会保持未接入，应用后可手动连接入口。"))
        return {
            "title": dsl.get("title") or tr(self.lang, "ai_builder.default_title", "AI 生成测试流程"),
            "summary": dsl.get("summary") or "",
            "dsl": dsl,
            "nodes": self.nodes,
            "links": self.links,
            "entry": first_exec,
            "auto_connect_start": start_external,
            "notes": notes,
            "stats": {"nodes": len(self.nodes), "links": len(self.links), "steps": len(dsl.get("steps") or [])},
        }

    def node(self, ntype: str, properties: dict | None = None, pos: list[int] | None = None,
             title: str = "") -> str:
        self._seq += 1
        nid = f"n{self._seq}"
        self.nodes.append({
            "id": nid,
            "type": ntype,
            "title": title,
            "pos": pos or [self._cursor_x, self._flow_y],
            "properties": properties or {},
        })
        return nid

    def link(self, src: str, out: str, dst: str, inp: str, optional: bool = False) -> None:
        self.links.append({"from": src, "out": out, "to": dst, "in": inp, "optional": optional})

    def _ensure_device(self) -> None:
        attrs = _first_node(self.current_graph, "device/attrs")
        if attrs:
            self.attrs_ref = f"external:{attrs['id']}"
            return
        dev = _first_device_source(self.current_graph)
        if dev:
            attrs_id = self.node("device/attrs", pos=[self._cursor_x, self._data_y + 170])
            self.link(f"external:{dev['id']}", "device", attrs_id, "device")
            self.attrs_ref = attrs_id
            self._cursor_x += 230
            return
        dtype = self.device_config.get("type") or "device/rdp"
        if dtype not in _DEVICE_TYPES:
            dtype = "device/rdp"
        props = _sanitize_props(self.device_config.get("properties") or {})
        dev_id = self.node(dtype, props, pos=[self._cursor_x, self._data_y])
        attrs_id = self.node("device/attrs", pos=[self._cursor_x + 240, self._data_y + 40])
        interaction_id = self.node("io/interaction", pos=[self._cursor_x + 240, self._data_y + 210])
        self.link(dev_id, "device", attrs_id, "device")
        self.link(dev_id, "device", interaction_id, "device")
        self.attrs_ref = attrs_id
        self._cursor_x += 520

    def _ensure_ai(self) -> None:
        ai = _first_node(self.current_graph, "ai/engine")
        if ai:
            self.ai_ref = f"external:{ai['id']}"
            return
        props = _sanitize_props({
            "provider": self.ai_config.get("provider", "openai"),
            "base_url": self.ai_config.get("base_url", ""),
            "model": self.ai_config.get("model", "gpt-4o"),
            "api_key": "",
            "temperature": self.ai_config.get("temperature", 0),
        })
        self.ai_ref = self.node("ai/engine", props, pos=[self._cursor_x, self._data_y])
        self._cursor_x += 260

    def _needs_runtime_ai(self, dsl: dict) -> bool:
        for step in dsl.get("steps") or []:
            action = str(step.get("action") or "")
            method = str(step.get("method") or "").lower()
            if action in {"click_ai", "assert_ai"} or method == "ai":
                return True
        return False

    def _build_step(self, step: dict):
        action = str(step.get("action") or "").strip()
        if action == "log":
            n = self._log_step(str(step.get("message") or ""))
            return n, n, "out"
        if action in {"wait_seconds", "delay"}:
            n = self._exec_node("wait/delay", {"seconds": _num(step.get("seconds"), 1.0)})
            return n, n, "out"
        if action == "type":
            text = self._text_const(str(step.get("text") or ""), "输入文本")
            n = self._exec_node("action/type", {"paste": bool(step.get("paste", True))})
            self.link(text, "text", n, "text")
            self.link(self.attrs_ref, "keyboard", n, "keyboard")
            return n, n, "out"
        if action == "hotkey":
            n = self._exec_node("action/hotkey", {"keys": str(step.get("keys") or "")})
            self.link(self.attrs_ref, "keyboard", n, "keyboard")
            return n, n, "out"
        if action == "wait_text":
            find = self._find_text_like(step)
            fail = self._raise_node(f"等待目标超时：{step.get('text') or step.get('description') or ''}")
            self.link(find, "notFound", fail, "in")
            return find, find, "found"
        if action in {"click_text", "click_ai"}:
            return self._click_target(step)
        if action == "scroll_text":
            return self._scroll_target(step)
        if action in {"assert_text", "assert_ai"}:
            return self._assert_target(step)
        # Unknown model action: keep it visible as a log instead of silently dropping it.
        n = self._log_step(json.dumps(step, ensure_ascii=False))
        return n, n, "out"

    def _exec_node(self, ntype: str, props: dict | None = None) -> str:
        n = self.node(ntype, props or {}, pos=[self._cursor_x, self._flow_y])
        self._cursor_x += 280
        return n

    def _log_step(self, message: str) -> str:
        text = self._text_const(str(message or ""), "日志")
        n = self._exec_node("util/log", {"label": "AI"})
        self.link(text, "text", n, "value")
        return n

    def _text_const(self, value: str, note: str = "") -> str:
        n = self.node("const/text", {"value": value, "备注": note}, pos=[self._cursor_x, self._data_y])
        return n

    def _bool_const(self, value: bool, note: str = "") -> str:
        y = self._data_y + (80 if value else 150)
        n = self.node("const/bool", {"value": bool(value), "备注": note}, pos=[self._cursor_x, y])
        return n

    def _find_text_like(self, step: dict) -> str:
        method = str(step.get("method") or "ocr").lower()
        timeout = _num(step.get("timeout"), 5)
        if step.get("action") in {"click_ai", "assert_ai"}:
            method = "ai"
        if method == "ai":
            kind = str(step.get("kind") or ("text" if step.get("text") else "image")).lower()
            ntype = "ai/find_text" if kind == "text" else "ai/find_image"
            desc = str(step.get("description") or step.get("text") or "")
            n = self._exec_node(ntype, {"prompt": desc, "min_confidence": 0})
            self.link(self.attrs_ref, "video", n, "video")
            self.link(self.ai_ref, "ai", n, "ai")
            return n
        text = self._text_const(str(step.get("text") or step.get("description") or ""), "查找文字")
        n = self._exec_node("vision/find_text", {"regex": bool(step.get("regex", False)), "timeout": timeout})
        self.link(self.attrs_ref, "video", n, "video")
        self.link(text, "text", n, "text")
        return n

    def _click_target(self, step: dict):
        find = self._find_text_like(step)
        point = self.node("geom/to_point", {
            "anchor": step.get("anchor") or "center",
            "dx": int(_num(step.get("dx"), 0)),
            "dy": int(_num(step.get("dy"), 0)),
        }, pos=[self._cursor_x - 120, self._data_y + 150])
        click = self._exec_node("action/click", {
            "button": step.get("button") or "left",
            "double": bool(step.get("double", False)),
        })
        fail = self._raise_node(f"找不到点击目标：{step.get('text') or step.get('description') or ''}")
        self.link(find, "match", point, "match")
        self.link(point, "point", click, "target")
        self.link(self.attrs_ref, "mouse", click, "mouse")
        self.link(find, "found", click, "in")
        self.link(find, "notFound", fail, "in")
        return find, click, "out"

    def _scroll_target(self, step: dict):
        find = self._find_text_like(step)
        point = self.node("geom/to_point", {"anchor": "center", "dx": 0, "dy": 0},
                          pos=[self._cursor_x - 120, self._data_y + 150])
        scroll = self._exec_node("action/scroll", {"dy": int(_num(step.get("dy"), -3))})
        fail = self._raise_node(f"找不到滚动目标：{step.get('text') or step.get('description') or ''}")
        self.link(find, "match", point, "match")
        self.link(point, "point", scroll, "target")
        self.link(self.attrs_ref, "mouse", scroll, "mouse")
        self.link(find, "found", scroll, "in")
        self.link(find, "notFound", fail, "in")
        return find, scroll, "out"

    def _assert_target(self, step: dict):
        find = self._find_text_like(step)
        msg = str(step.get("message") or f"应出现：{step.get('text') or step.get('description') or ''}")
        true_const = self._bool_const(True, "断言通过")
        false_const = self._bool_const(False, "断言失败")
        ok_assert = self._exec_node("assert/check", {"message": msg})
        fail_assert = self._exec_node("assert/check", {"message": msg})
        self.link(true_const, "bool", ok_assert, "cond")
        self.link(false_const, "bool", fail_assert, "cond")
        self.link(find, "found", ok_assert, "in")
        self.link(find, "notFound", fail_assert, "in")
        return find, ok_assert, "pass"

    def _raise_node(self, message: str) -> str:
        return self.node("flow/raise", {"message": message or "目标未找到"},
                         pos=[self._cursor_x - 260, self._flow_y + 180])


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
