"""计算机操作代理循环：看屏→问模型下一步动作→在设备上执行→重复，直到 finish 或达上限。

run_agent(region, goal, ai=engine, max_steps=..., on_step=callback) -> (ok, message, steps)
on_step(step, action, screen_bgr, target_xy) 每步回调（供上层回显/记日志）；target_xy 为本步
动作的像素落点（点击/滚动/拖拽起点），无则 None。中止通过 visauto 的 check_abort 协作式响应。
"""
from __future__ import annotations

import time

from ..settings import check_abort


def _norm_xy(region, ax, ay):
    """归一化 [0,1] → 绝对像素（按本区域帧宽高 + 区域原点）。"""
    screen_w = region.w or 1
    screen_h = region.h or 1
    x = region.x + int(float(ax) * screen_w)
    y = region.y + int(float(ay) * screen_h)
    return x, y


def _parse_keys(spec):
    """'ctrl+c' → ('c', ['ctrl'])；'enter' → ('enter', [])。"""
    parts = [p for p in str(spec).replace(" ", "").lower().split("+") if p]
    if not parts:
        return None, []
    return parts[-1], parts[:-1]


def _action_brief(a: dict) -> str:
    """动作简述（写日志/历史用）。"""
    n = a.get("action")
    if n == "click":
        b = a.get("button", "left"); d = "double-" if a.get("double") else ""
        return f"{d}{b}click({a.get('x')},{a.get('y')})"
    if n == "type":
        return f"type({a.get('text', '')!r})"
    if n == "key":
        return f"key({a.get('keys', '')})"
    if n == "scroll":
        return f"scroll({a.get('x')},{a.get('y')},dy={a.get('dy')})"
    if n == "drag":
        return f"drag({a.get('x1')},{a.get('y1')}→{a.get('x2')},{a.get('y2')})"
    if n == "wait":
        return f"wait({a.get('seconds')})"
    if n == "finish":
        return f"finish(success={a.get('success')})"
    return str(n)


def _execute(region, action: dict):
    """在设备上执行一个动作；返回本步像素落点 (x,y) 供标注，无则 None。"""
    n = action.get("action")
    if n == "click":
        x, y = _norm_xy(region, action.get("x", 0), action.get("y", 0))
        if action.get("double"):
            region._device.mouse.double_click(x, y)
        elif action.get("button") == "right":
            region._device.mouse.right_click(x, y)
        else:
            region._device.mouse.click(x, y)
        return (x, y)
    if n == "type":
        region.type(str(action.get("text", "")))
        return None
    if n == "key":
        key, mods = _parse_keys(action.get("keys", ""))
        if key:
            region.press_key(key, modifiers=mods or None)
        return None
    if n == "scroll":
        x, y = _norm_xy(region, action.get("x", 0.5), action.get("y", 0.5))
        region._device.mouse.scroll(x, y, 0, int(action.get("dy", -1)))
        return (x, y)
    if n == "drag":
        x1, y1 = _norm_xy(region, action.get("x1", 0), action.get("y1", 0))
        x2, y2 = _norm_xy(region, action.get("x2", 0), action.get("y2", 0))
        region._device.mouse.drag_drop(x1, y1, x2, y2)
        return (x1, y1)
    if n == "wait":
        end = time.monotonic() + float(action.get("seconds", 1) or 0)
        while time.monotonic() < end:
            check_abort()
            time.sleep(min(0.1, end - time.monotonic()))
        return None
    # 未知动作：忽略
    return None


def run_agent(region, goal, *, ai, max_steps: int = 15, on_step=None):
    """跑代理循环。返回 (ok: bool, message: str, steps: int)。"""
    history: list[str] = []
    for step in range(1, int(max_steps) + 1):
        check_abort()
        screen = region._capture()
        action = ai.next_action(screen, str(goal), "\n".join(history) or "(none)")
        if action.get("action") == "finish":
            ok = bool(action.get("success"))
            msg = str(action.get("message", ""))
            if on_step:
                on_step(step, action, screen, None)
            return ok, msg, step
        target = _execute(region, action)
        if on_step:
            on_step(step, action, screen, target)
        history.append(f"{step}. {action.get('reasoning', '')} -> {_action_brief(action)}")
    return False, f"超过最大步数 {max_steps}", int(max_steps)
