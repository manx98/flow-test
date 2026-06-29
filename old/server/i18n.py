"""Server-side i18n helpers.

Chinese source strings stay as the fallback. Locale-specific overlays live in
``server/locales/<lang>.py`` so adding a language does not expand this module.
"""
from __future__ import annotations

import copy
import re
from importlib import import_module
from typing import Any

DEFAULT_LANG = "zh"
SUPPORTED_LANGS = {"zh", "en"}

_DESC_ALIASES = {
    "执行入口：上游执行流到达即运行本节点": "common.desc.exec_in",
    "执行出口：本节点完成后从这里继续": "common.desc.exec_out",
    "备注：说明此常量的用途（仅展示，不参与运行）": "common.desc.note",
    "设备句柄：连「设备属性」取出 video/mouse/keyboard 等能力，或直接连「人机交互」「脚本」": "common.desc.device_output",
}

_ERROR_ALIASES = {
    "非法工程名": "api.invalid_project_name",
    "原图片不存在": "api.original_image_not_found",
    "目标文件名已存在": "api.target_filename_exists",
    "运行记录不存在": "api.run_record_not_found",
}


def lang_from_accept_language(value: str | None, fallback: str = DEFAULT_LANG) -> str:
    """Pick the first supported language from an Accept-Language header."""
    if not value:
        return fallback
    best = (fallback, -1.0, -1)
    for idx, part in enumerate(value.split(",")):
        item = part.strip()
        if not item:
            continue
        lang, q = item, 1.0
        if ";" in item:
            lang, *params = [p.strip() for p in item.split(";")]
            for param in params:
                if param.startswith("q="):
                    try:
                        q = float(param[2:])
                    except ValueError:
                        q = 0.0
        code = normalize_lang(lang)
        if code in SUPPORTED_LANGS and (q > best[1] or (q == best[1] and idx < best[2])):
            best = (code, q, idx)
    return best[0]


def normalize_lang(value: str | None, fallback: str = DEFAULT_LANG) -> str:
    raw = (value or "").strip().lower().replace("_", "-")
    if not raw:
        return fallback
    base = raw.split("-", 1)[0]
    if base in SUPPORTED_LANGS:
        return base
    return fallback


def tr(lang: str | None, key: str, default: str = "", **vars: Any) -> str:
    code = normalize_lang(lang)
    text = _MESSAGES.get(code, {}).get(key)
    if text is None:
        text = default
    if vars:
        return str(text).format_map(_SafeDict(vars))
    return str(text)


def translate_error(lang: str | None, error: Exception | str) -> str:
    text = str(error)
    key = _ERROR_ALIASES.get(text)
    if key:
        return tr(lang, key, text)
    return text


def localize_catalog(catalog: dict, lang: str | None) -> dict:
    code = normalize_lang(lang)
    if code == DEFAULT_LANG:
        return catalog
    data = copy.deepcopy(catalog)
    for spec in data.get("nodes", []):
        ntype = spec.get("type", "")
        path = _node_path(ntype)
        spec["category"] = tr(code, f"categories.{spec.get('category')}", spec.get("category", ""))
        spec["title"] = tr(code, f"nodes.{path}.title", spec.get("title", ""))
        spec["description"] = tr(code, f"nodes.{path}.description", spec.get("description", ""))
        _localize_slots(code, f"nodes.{path}.inputs", spec.get("inputs") or [])
        _localize_slots(code, f"nodes.{path}.outputs", spec.get("outputs") or [])
        _localize_props(code, f"nodes.{path}.properties", spec.get("properties") or [])
        if "functions" in spec:
            _localize_named_desc(code, f"nodes.{path}.functions", spec["functions"], "sig")
        if "injects" in spec:
            _localize_named_desc(code, f"nodes.{path}.injects", spec["injects"], "name")
    return data


def _localize_slots(lang: str, base: str, slots: list[dict]) -> None:
    for slot in slots:
        name = slot.get("name", "")
        slot["desc"] = _desc(lang, f"{base}.{name}.desc", slot.get("desc", ""))


def _localize_props(lang: str, base: str, props: list[dict]) -> None:
    for prop in props:
        name = prop.get("name", "")
        prop["desc"] = _desc(lang, f"{base}.{name}.desc", prop.get("desc", ""))


def _localize_named_desc(lang: str, base: str, items: list[dict], key_name: str) -> None:
    for item in items:
        key = _safe_key(item.get(key_name, ""))
        item["desc"] = _desc(lang, f"{base}.{key}.desc", item.get("desc", ""))


def _desc(lang: str, key: str, default: str) -> str:
    exact = _DESC_TEXT.get(lang, {}).get(default)
    if exact:
        return exact
    exact_key = _DESC_ALIASES.get(default)
    if exact_key:
        return tr(lang, exact_key, default)
    return tr(lang, key, default)


def _node_path(ntype: str) -> str:
    return ntype.replace("/", ".")


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value)).strip("_")
    return key or "item"


def _load_messages() -> dict[str, dict[str, str]]:
    return {lang: dict(getattr(_locale_module(lang), "MESSAGES", {})) for lang in SUPPORTED_LANGS}


def _load_desc_text() -> dict[str, dict[str, str]]:
    return {lang: dict(getattr(_locale_module(lang), "DESC_TEXT", {})) for lang in SUPPORTED_LANGS}


def _locale_module(lang: str):
    return import_module(f"{__package__}.locales.{lang}")


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


_MESSAGES = _load_messages()
_DESC_TEXT = _load_desc_text()
