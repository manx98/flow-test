"""脚本节点的后端代码补全：jedi 语义补全 + 注入运行时命名空间类型。

脚本运行时注入：devs(设备字典) + 各 device 输入口的同名句柄、visauto/Pattern/vars，
以及设备无关的全局函数（image/to_point/delay/log/alert/get_var/set_var）。
设备句柄方法（find_image/click/…）经 devs['名'].xxx 调用——见 flow/engine.py 的
ScriptDevice / ScriptGlobals / _run_script。这里用「前导」把这些名字以类型注解声明给 jedi，
使其能补全真实成员（如 devs['pc'].find_image(...)）。补全请求的行号需加上前导行数偏移。
"""
from __future__ import annotations

import os
from functools import lru_cache

# 用类型化的 def 桩声明注入名（不 import 工程包，避免 jedi 追进 visauto/engine 触发重型静态
# 分析导致整体补全失败）。设备句柄方法声明在 _Dev 上，devs 标注为 dict[str, _Dev] 以支持
# devs['x']. 链式补全。返回类型用 visauto 自带类型。
_PREAMBLE = (
    "import visauto\n"
    "from visauto import Pattern, Image, Region, Match, Key, Location, Rect\n"
    "vars: dict = {}\n"
    "class _Dev:\n"
    "    raw: visauto.Device\n"
    "    def find_image(self, template, similarity=0.7, mask=None, timeout=0) -> Match: ...\n"
    "    def find_text(self, text, regex=False, ocr=None, timeout=0) -> Match: ...\n"
    "    def find_all(self, template, similarity=0.7) -> list: ...\n"
    "    def ai_find_image(self, desc, ai) -> Match: ...\n"
    "    def ai_find_text(self, desc, ai) -> Match: ...\n"
    "    def ai_agent(self, goal, ai, max_steps=15) -> tuple: ...\n"
    "    def wait_appear(self, template, timeout=10, mask=None) -> Match: ...\n"
    "    def wait_vanish(self, template, timeout=10, mask=None) -> bool: ...\n"
    "    def click(self, target, button='left', double=False) -> None: ...\n"
    "    def type_text(self, text, paste=False) -> None: ...\n"
    "    def hotkey(self, keys) -> None: ...\n"
    "    def hold_keys(self, keys): ...\n"
    "    def scroll(self, target, dy=-1) -> None: ...\n"
    "    def drag(self, src, dst) -> None: ...\n"
    # 入参/结果：get_arg 标注返回 _Dev 以支持 get_arg('设备').方法 链式补全（设备是最常见用法）
    "def get_arg(name, default=None) -> _Dev: ...\n"
    "def set_result(name, value) -> None: ...\n"
    "def image(name) -> Image: ...\n"
    "def to_point(match, anchor='center', dx=0, dy=0) -> Location: ...\n"
    "def delay(seconds=1.0) -> None: ...\n"
    "def log(value, label='') -> None: ...\n"
    "def alert(message, level='info') -> None: ...\n"
    "def get_var(name, default=None): ...\n"
    "def set_var(name, value) -> None: ...\n"
)
_OFFSET = _PREAMBLE.count("\n")   # 前导占用的行数

# jedi 环境/工程缓存：每次 Script() 重新推断环境(扫 sys.path)很贵，缓存后单次耗时减半以上
_CTX = None   # (environment, project)；None 表示未初始化


def _jedi_ctx():
    global _CTX
    if _CTX is None:
        import jedi
        # 关闭动态推断(跟踪函数调用返回/数组增量/控制流)，代码补全用不上，徒增耗时
        jedi.settings.dynamic_params = False
        jedi.settings.dynamic_array_additions = False
        jedi.settings.dynamic_flow_information = False
        try:
            env = jedi.get_default_environment()
            proj = jedi.Project(path=os.getcwd(), environment_path=env.executable)
            _CTX = (env, proj)
        except Exception:
            _CTX = (None, None)   # 推断失败则退回 jedi 默认
    return _CTX


def _complete(code: str, line: int, column: int, limit: int) -> tuple:
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
        return ()
    out: list = []
    seen: set = set()
    for c in comps:
        if c.name.startswith("__") or c.name in seen:
            continue
        seen.add(c.name)
        out.append((c.name, c.type))
        if len(out) >= limit:
            break
    return tuple(out)


# 结果记忆：同一 (代码, 行, 列) 短期内重复请求(光标往返/重新触发)直接命中，省去 jedi
@lru_cache(maxsize=128)
def _complete_memo(code: str, line: int, column: int, limit: int) -> tuple:
    return _complete(code, line, column, limit)


def complete(code: str, line: int, column: int, limit: int = 40) -> list[dict]:
    """line 为 1 基（用户代码内），column 为 0 基。返回 [{name, type}]。"""
    pairs = _complete_memo(code or "", int(line), int(column), int(limit))
    return [{"name": n, "type": t} for n, t in pairs]


def warmup() -> None:
    """后台预热：先让 jedi 解析好前导(visauto 类型)与常用 stdlib，
    把一次性的模块分析成本(可达数百 ms~1s)挪到启动期，用户首次补全即秒回。"""
    for code, ln, col in (("devs['x'].", 1, 10), ("devs['x'].find_image('a').", 1, 26),
                          ("import os\nos.", 2, 3), ("import sys\nsys.", 2, 4),
                          ("import re\nre.", 2, 3)):
        try:
            _complete(code, ln, col, 40)
        except Exception:
            pass
