"""端口类型系统（对应 flow-design.md 第 2 节）。

源端口 out → 汇端口 in，单向。类型匹配：同类型或 ANY 可连；Exec 仅连 Exec；
Bundle 仅连 Bundle。基数 '*'/'1'/'n'；必选 '!'、可选 '?'。
"""
from __future__ import annotations

# 端口类型常量
EXEC = "exec"
DEVICE = "device"
SCRIPT = "script"
VIDEO = "video"
PICTURE = "picture"
MOUSE = "mouse"
KEYBOARD = "keyboard"
MATCH = "match"
TEXT = "text"
BOOL = "bool"
POINT = "point"
NUMBER = "number"
OCR = "ocr"
MASK = "mask"
BUNDLE = "bundle"
ANY = "any"

# 前端连线/端口着色
TYPE_COLORS = {
    EXEC: "#90A4AE",
    DEVICE: "#00BCD4",
    SCRIPT: "#9CCC65",
    VIDEO: "#4FC3F7",
    PICTURE: "#BA68C8",
    MOUSE: "#FFB74D",
    KEYBOARD: "#FFD54F",
    MATCH: "#81C784",
    TEXT: "#E0E0E0",
    BOOL: "#F06292",
    POINT: "#4DB6AC",
    NUMBER: "#9FA8DA",
    OCR: "#7E57C2",
    MASK: "#26A69A",
    BUNDLE: "#A1887F",
    ANY: "#BDBDBD",
}

DATA_TYPES = {DEVICE, SCRIPT, VIDEO, PICTURE, MOUSE, KEYBOARD, MATCH, TEXT, BOOL, POINT, NUMBER, OCR, MASK, BUNDLE, ANY}


def compatible(src_type: str, dst_type: str) -> bool:
    """src 的 out 端口类型能否连到 dst 的 in 端口类型。"""
    if src_type == EXEC or dst_type == EXEC:
        return src_type == EXEC and dst_type == EXEC
    if src_type == BUNDLE or dst_type == BUNDLE:
        return src_type == BUNDLE and dst_type == BUNDLE
    if src_type == ANY or dst_type == ANY:
        return True
    return src_type == dst_type
