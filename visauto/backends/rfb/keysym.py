"""键名/字符 → X11 keysym 映射（用于 RFB KeyEvent）。"""
from __future__ import annotations

# 规范键名（见 visauto.input.Key）→ X11 keysym
NAMED_KEYSYMS = {
    "enter": 0xFF0D,
    "return": 0xFF0D,
    "tab": 0xFF09,
    "space": 0x0020,
    "backspace": 0xFF08,
    "delete": 0xFFFF,
    "esc": 0xFF1B,
    "escape": 0xFF1B,
    "up": 0xFF52,
    "down": 0xFF54,
    "left": 0xFF51,
    "right": 0xFF53,
    "home": 0xFF50,
    "end": 0xFF57,
    "pageup": 0xFF55,
    "pagedown": 0xFF56,
    "insert": 0xFF63,
    "caps_lock": 0xFFE5,
    # 修饰键（默认左键）
    "ctrl": 0xFFE3,
    "control": 0xFFE3,
    "alt": 0xFFE9,
    "option": 0xFFE9,
    "shift": 0xFFE1,
    "cmd": 0xFFEB,
    "meta": 0xFFEB,
    "win": 0xFFEB,
    "super": 0xFFEB,
    # 功能键 F1..F12 = 0xFFBE..0xFFC9
    **{f"f{i}": 0xFFBE + (i - 1) for i in range(1, 13)},
}


def keysym_for_char(ch: str) -> int:
    """单个字符 → keysym。Latin-1 直接用码点，其它走 Unicode keysym。"""
    code = ord(ch)
    if code < 0x100:
        return code
    return 0x01000000 + code


def keysym_for_key(key: str) -> int:
    """规范键名或单字符 → keysym。"""
    if len(key) == 1:
        return keysym_for_char(key)
    sym = NAMED_KEYSYMS.get(key.lower())
    if sym is None:
        raise KeyError(f"未知键名：{key}")
    return sym
