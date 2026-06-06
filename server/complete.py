"""脚本节点的后端代码补全：jedi 语义补全 + 注入运行时命名空间类型。

脚本运行时会注入 dev/visauto/vars/Pattern + flow(ScriptAPI) 及其组件功能函数
（见 flow/engine.py 的 ScriptAPI / _run_script）。这里用一段「前导」把这些名字以类型
注解声明给 jedi，使其能补全真实成员（如 dev.find、find_image(...)）。
补全请求的行号需加上前导行数偏移。
"""
from __future__ import annotations

import os

# 用类型化的 def 桩声明注入的组件功能函数（不 import 工程包，避免 jedi 追进 visauto/engine
# 触发重型静态分析导致整体补全失败）。返回类型用 visauto 自带类型，便于链式补全。
_PREAMBLE = (
    "import visauto\n"
    "from visauto import Pattern, Image, Region, Match, Key, Location, Rect\n"
    "dev: visauto.Device\n"
    "vars: dict = {}\n"
    "def image(name) -> Image: ...\n"
    "def find_image(template, similarity=0.7, mask=None, timeout=0) -> Match: ...\n"
    "def find_text(text, regex=False, ocr=None, timeout=0) -> Match: ...\n"
    "def find_all(template, similarity=0.7) -> list: ...\n"
    "def wait_appear(template, timeout=10) -> Match: ...\n"
    "def wait_vanish(template, timeout=10) -> bool: ...\n"
    "def to_point(match, anchor='center', dx=0, dy=0) -> Location: ...\n"
    "def click(target, button='left', double=False) -> None: ...\n"
    "def type_text(text, paste=False) -> None: ...\n"
    "def scroll(target, dy=-1) -> None: ...\n"
    "def drag(src, dst) -> None: ...\n"
    "def delay(seconds=1.0) -> None: ...\n"
    "def log(value, label='') -> None: ...\n"
    "def alert(message, level='info') -> None: ...\n"
    "def get_var(name, default=None): ...\n"
    "def set_var(name, value) -> None: ...\n"
    "class _Flow:\n"
    "    image = image; find_image = find_image; find_text = find_text; find_all = find_all\n"
    "    wait_appear = wait_appear; wait_vanish = wait_vanish; to_point = to_point\n"
    "    click = click; type_text = type_text; scroll = scroll; drag = drag; delay = delay\n"
    "    log = log; alert = alert; get_var = get_var; set_var = set_var\n"
    "flow: _Flow\n"
)
_OFFSET = _PREAMBLE.count("\n")   # 前导占用的行数

# jedi 环境/工程缓存：每次 Script() 重新推断环境(扫 sys.path)很贵，缓存后单次耗时减半以上
_CTX = None   # (environment, project)；None 表示未初始化


def _jedi_ctx():
    global _CTX
    if _CTX is None:
        import jedi
        try:
            env = jedi.get_default_environment()
            proj = jedi.Project(path=os.getcwd(), environment_path=env.executable)
            _CTX = (env, proj)
        except Exception:
            _CTX = (None, None)   # 推断失败则退回 jedi 默认
    return _CTX


def complete(code: str, line: int, column: int, limit: int = 40) -> list[dict]:
    """line 为 1 基（用户代码内），column 为 0 基。返回 [{name, type}]。"""
    import jedi
    src = _PREAMBLE + (code or "")
    lines = src.split("\n")
    # 钳制到有效范围：jedi 越界(行/列超出)会直接返回空，这里兜底到最近合法位置
    tline = max(1, min(int(line) + _OFFSET, len(lines)))
    tcol = max(0, min(int(column), len(lines[tline - 1])))
    env, proj = _jedi_ctx()
    try:
        comps = jedi.Script(src, environment=env, project=proj).complete(tline, tcol)
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
