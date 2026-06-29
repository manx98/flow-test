"""全局可调参数与分级日志（对应 design 第 12 节 Settings/Debug）。"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass


@dataclass
class _Settings:
    """脚本行为的“旋钮”。可在运行时直接修改字段。"""

    # —— 找图 ——
    min_similarity: float = 0.7          # 默认相似度阈值
    auto_wait_timeout: float = 3.0       # find/wait 默认等待秒数
    wait_scan_rate: float = 3.0          # 每秒轮询次数（wait/exists）
    observe_scan_rate: float = 3.0       # 每秒轮询次数（observe）

    # —— 输入 ——
    move_delay: float = 0.0              # 鼠标移动后到按下前的停顿
    click_delay: float = 0.0             # 按下到释放的停顿
    type_delay: float = 0.0              # 逐字符键入间隔
    double_click_interval: float = 0.1   # 双击两次之间的间隔

    # —— 可视化调试 ——
    highlight: bool = False              # 命中后是否高亮
    highlight_duration: float = 1.0

    # —— 变化检测（observe on_change）——
    min_change_pixels: int = 50          # 变化区域最小像素面积阈值


Settings = _Settings()


# ---------------------------------------------------------------------------
# 协作式中止（供 GUI 的 Stop 取消长 wait/observe；纯库用户不设则行为不变）
# ---------------------------------------------------------------------------
_abort_event = None  # threading.Event | None


def set_abort_event(event) -> None:
    """注册一个 threading.Event；置位后 wait/observe 轮询循环会抛 ScriptAborted。"""
    global _abort_event
    _abort_event = event


def clear_abort_event() -> None:
    global _abort_event
    _abort_event = None


def check_abort() -> None:
    """若已注册的 abort 事件被置位则抛 ScriptAborted。无事件时为零开销空操作。"""
    ev = _abort_event
    if ev is not None and ev.is_set():
        from .exceptions import ScriptAborted
        raise ScriptAborted("脚本被中止")


class _Debug:
    """极简分级日志：level 越大越啰嗦。

    level: -1 关闭, 0 用户级, 1 信息, 2 动作, 3 追踪。
    """

    level: int = 0

    @classmethod
    def set_level(cls, level: int) -> None:
        cls.level = level

    @classmethod
    def is_enabled(cls, level: int) -> bool:
        return cls.level >= level

    @classmethod
    def _log(cls, level: int, tag: str, msg: str) -> None:
        if cls.level >= level:
            ts = time.strftime("%H:%M:%S")
            print(f"[visauto {ts} {tag}] {msg}", file=sys.stderr)

    @classmethod
    def user(cls, msg: str) -> None:
        cls._log(0, "user", msg)

    @classmethod
    def info(cls, msg: str) -> None:
        cls._log(1, "info", msg)

    @classmethod
    def action(cls, msg: str) -> None:
        cls._log(2, "action", msg)

    @classmethod
    def trace(cls, msg: str) -> None:
        cls._log(3, "trace", msg)

    @classmethod
    def error(cls, msg: str) -> None:
        # 错误始终打印
        ts = time.strftime("%H:%M:%S")
        print(f"[visauto {ts} ERROR] {msg}", file=sys.stderr)


Debug = _Debug
