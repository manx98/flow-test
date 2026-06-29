"""把浏览器经 DataChannel 发来的输入事件派发到设备后端。

事件(JSON)：
  {"t":"move","x":,"y":}
  {"t":"down"|"up","x":,"y":,"button":"left"|"right"|"middle"}
  {"t":"scroll","x":,"y":,"dy":}
  {"t":"text","text":"abc"}              # Unicode 文本输入
  {"t":"key","name":"enter","down":true} # 具名特殊键
坐标为设备像素（前端已按视频分辨率换算）。
"""
from __future__ import annotations

from visauto.backends.base import Button

from .devices import DeviceSession

_BTN = {"left": Button.LEFT, "right": Button.RIGHT, "middle": Button.MIDDLE}


def dispatch_input(session: DeviceSession, evt: dict) -> None:
    dev = session.device
    if dev is None:
        return
    be = dev.backend
    t = evt.get("t")
    try:
        if t == "move":
            be.mouse_move(int(evt["x"]), int(evt["y"]))
        elif t == "down":
            be.mouse_move(int(evt["x"]), int(evt["y"]))
            be.mouse_press(_BTN.get(evt.get("button", "left"), Button.LEFT))
        elif t == "up":
            be.mouse_release(_BTN.get(evt.get("button", "left"), Button.LEFT))
        elif t == "scroll":
            be.mouse_move(int(evt["x"]), int(evt["y"]))
            be.mouse_scroll(int(evt.get("dx", 0)), int(evt.get("dy", 0)))
        elif t == "text":
            be.type_text(str(evt.get("text", "")))
        elif t == "key":
            name = str(evt.get("name", ""))
            if not name:
                return
            if evt.get("down", True):
                be.key_press(name)
            else:
                be.key_release(name)
    except Exception:
        # 输入失败不应打断会话
        pass
