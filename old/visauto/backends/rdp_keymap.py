"""键名/字符 → RDP 输入映射。

aardwolf 的 RDP_KEYBOARD_SCANCODE 支持两种定位：
- vk_code：传 VK 名（如 'VK_RETURN'），aardwolf 内部查 __vk_to_sc 表得扫描码/扩展位；
- keyCode：直接给 PC/AT 扫描码（set 1）。

策略：
- 具名键（回车/方向键/修饰键/F 区…）→ VK 名（NAME_TO_VK），交给 aardwolf 解析；
- 组合键里的单字符（Ctrl+V 的 'v'）→ 扫描码（CHAR_TO_SCANCODE），以便与修饰键组合；
- 任意文本（含中文）走 Unicode 键事件，不经此表。
"""
from __future__ import annotations

# 规范键名（见 visauto.input.Key）→ aardwolf VK 名
NAME_TO_VK = {
    "enter": "VK_RETURN",
    "return": "VK_RETURN",
    "tab": "VK_TAB",
    "backspace": "VK_BACK",
    "delete": "VK_DELETE",
    "esc": "VK_ESCAPE",
    "escape": "VK_ESCAPE",
    "up": "VK_UP",
    "down": "VK_DOWN",
    "left": "VK_LEFT",
    "right": "VK_RIGHT",
    "home": "VK_HOME",
    "end": "VK_END",
    "pageup": "VK_PRIOR",
    "pagedown": "VK_NEXT",
    "insert": "VK_INSERT",
    "caps_lock": "VK_CAPITAL",
    # 修饰键（默认左键）
    "ctrl": "VK_LCONTROL",
    "control": "VK_LCONTROL",
    "alt": "VK_LMENU",
    "option": "VK_LMENU",
    "shift": "VK_LSHIFT",
    "cmd": "VK_LWIN",
    "meta": "VK_LWIN",
    "win": "VK_LWIN",
    "super": "VK_LWIN",
    **{f"f{i}": f"VK_F{i}" for i in range(1, 13)},
}

# US 布局 PC/AT 扫描码（set 1，make 码）——仅用于组合键中的单字符。
CHAR_TO_SCANCODE = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    " ": 57, "space": 57,
    "-": 12, "=": 13, "[": 26, "]": 27, ";": 39, "'": 40, "`": 41,
    "\\": 43, ",": 51, ".": 52, "/": 53,
}
