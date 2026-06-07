"""AI 视觉引擎：用大模型按自然语言描述在画面里定位元素/文字。"""
from .engine import AIEngine, build_prompt

__all__ = ["AIEngine", "build_prompt"]
