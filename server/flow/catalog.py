"""Graph node catalog loader.

The graph module documentation under ``graph_skills/`` is the source of truth:

graph_skills/
  DOC.md
  device/
    DOC.md
    device_rdp/
      DOC.md
      node.json

``node_catalog()`` reads those node.json files and returns the structure used by
the frontend palette and backend helpers.
"""
from __future__ import annotations

import json
from copy import deepcopy
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from . import types as T


GRAPH_SKILLS_ROOT = Path(__file__).with_name("graph_skills")


def _ver(pkg: str) -> "str | None":
    """Return installed package version without importing the package."""
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return None


def _engine_title(name: str, pkg: str) -> str:
    v = _ver(pkg)
    return f"{name} (v{v})" if v else f"{name} (未安装)"


def _load_node(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        node = json.load(f)
    if not isinstance(node, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if not node.get("type"):
        raise ValueError(f"{path} missing required field: type")
    if not node.get("category"):
        raise ValueError(f"{path} missing required field: category")
    if not node.get("title"):
        raise ValueError(f"{path} missing required field: title")
    title_pkg = node.pop("title_package", None)
    if title_pkg:
        node["title"] = _engine_title(str(node["title"]), str(title_pkg))
    node.setdefault("inputs", [])
    node.setdefault("outputs", [])
    node.setdefault("properties", [])
    return node


def _iter_node_files(root: Path):
    if not root.exists():
        raise FileNotFoundError(f"graph skills directory not found: {root}")
    yield from root.glob("*/*/node.json")


def node_catalog() -> dict:
    nodes = [_load_node(path) for path in _iter_node_files(GRAPH_SKILLS_ROOT)]
    nodes.sort(key=lambda n: (int(n.get("order", 10_000)), str(n.get("type", ""))))
    for n in nodes:
        n.pop("order", None)
    return {"types": deepcopy(T.TYPE_COLORS), "nodes": nodes}
