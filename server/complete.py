"""脚本节点的后端代码补全：jedi 语义补全 + 注入运行时命名空间类型。

脚本运行时会注入 dev/visauto/inp/out/vars/Pattern（见 flow/engine.py 的 _run_script）。
这里用一段「前导」把这些名字以类型注解声明给 jedi，使其能补全真实成员（如 dev.find）。
补全请求的行号需加上前导行数偏移。
"""
from __future__ import annotations

_PREAMBLE = (
    "import visauto\n"
    "from visauto import Pattern, Image, Region, Match, Key, Location, Rect\n"
    "dev: visauto.Device\n"
    "inp: dict = {}\n"
    "out: dict = {}\n"
    "vars: dict = {}\n"
)
_OFFSET = _PREAMBLE.count("\n")   # 前导占用的行数


def complete(code: str, line: int, column: int, limit: int = 40) -> list[dict]:
    """line 为 1 基（用户代码内），column 为 0 基。返回 [{name, type}]。"""
    import jedi
    src = _PREAMBLE + (code or "")
    lines = src.split("\n")
    # 钳制到有效范围：jedi 越界(行/列超出)会直接返回空，这里兜底到最近合法位置
    tline = max(1, min(int(line) + _OFFSET, len(lines)))
    tcol = max(0, min(int(column), len(lines[tline - 1])))
    try:
        comps = jedi.Script(src).complete(tline, tcol)
    except Exception:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for c in comps:
        if c.name.startswith("__") or c.name in seen:
            continue
        seen.add(c.name)
        out.append({"name": c.name, "type": c.type})
        if len(out) >= limit:
            break
    return out
