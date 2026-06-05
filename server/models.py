"""请求/响应数据模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateProject(BaseModel):
    name: str


class FlowGraph(BaseModel):
    # LiteGraph 序列化结构（节点/连线/配置），直接透传存盘。
    graph: dict[str, Any]


class Meta(BaseModel):
    meta: dict[str, Any]


class RenameImage(BaseModel):
    name: str   # 新文件名
