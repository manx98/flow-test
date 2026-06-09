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


class Settings(BaseModel):
    settings: dict[str, Any]


class RenameImage(BaseModel):
    name: str   # 新文件名


class CompleteReq(BaseModel):
    code: str
    line: int       # 1 基（用户代码内）
    column: int     # 0 基


class CheckReq(BaseModel):
    code: str       # 待检查的脚本代码
