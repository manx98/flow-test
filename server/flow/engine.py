"""流程执行引擎：worker 线程解释器（exec 走图 + data 按需拉取 memo + 控制流 + 设备解析 + abort）。

用法：Engine(graph_data).run(on_state, abort_event, device_provider) → Report
- on_state(node_id, status, info)：status ∈ running/ok/fail/skip
- abort_event：threading.Event；置位则中止（复用 visauto 的协作式中止）
- device_provider(device_node)->Device：解析设备节点为 visauto Device（默认连真实设备）
"""
from __future__ import annotations

import threading
import time

import visauto
from visauto import Pattern, ScriptAborted
from visauto.settings import check_abort

from .graph import GraphModel

# 节点处理器注册表：type -> {"eval": fn(ctx,node)->dict, "run": fn(ctx,node)->next_slot|None}
HANDLERS: dict[str, dict] = {}

# 这些节点在 run() 内自行上报状态（pass/fail/日志），_run_node 不再补 ok
_SELF_REPORT = {"assert/check", "util/log", "util/alert"}


def handler(ntype, kind):
    def deco(fn):
        HANDLERS.setdefault(ntype, {})[kind] = fn
        return fn
    return deco


class RunContext:
    def __init__(self, graph: GraphModel, on_state, abort_event, device_provider, report,
                 evidence_sink=None, on_event=None):
        self.graph = graph
        self.on_state = on_state or (lambda *a, **k: None)
        self.on_event = on_event or (lambda ev: None)   # 通用事件通道（如提示弹窗）
        self.abort = abort_event
        self.device_provider = device_provider
        self.report = report
        self.evidence_sink = evidence_sink   # callable(node_id, frame_bgr) -> ref|None
        self.values: dict = {}        # (node_id, out_slot_idx) -> value（latched/memo）
        self.evaluated: set = set()   # 已 pure 求值的节点
        self.vars: dict = {}
        self.devices: dict = {}       # device_node_id -> Device

    # ---- data 拉取 ----
    def get_input(self, node, name):
        src = self.graph.input_source(node, name)
        if not src:
            return None
        src_node, oslot = src
        key = (src_node["id"], oslot)
        if key in self.values:
            return self.values[key]
        h = HANDLERS.get(src_node["type"])
        if h and "eval" in h and src_node["id"] not in self.evaluated:
            outs = h["eval"](self, src_node) or {}
            self.evaluated.add(src_node["id"])
            for nm, val in outs.items():
                idx = GraphModel.out_slot_index(src_node, nm)
                if idx >= 0:
                    self.values[(src_node["id"], idx)] = val
        return self.values.get(key)

    def set_output(self, node, name, value):
        idx = GraphModel.out_slot_index(node, name)
        if idx >= 0:
            self.values[(node["id"], idx)] = value

    def emit(self, ev: dict):
        self.on_event(ev)

    # ---- 设备解析 ----
    def get_device(self, device_node):
        nid = device_node["id"]
        if nid not in self.devices:
            self.devices[nid] = self.device_provider(device_node)
        return self.devices[nid]

    def device_from_input(self, node, slot="video"):
        src = self.graph.input_source(node, slot)
        if not src:
            return None
        src_node, _ = src
        t = src_node["type"]
        if t.startswith("device/"):
            return self.get_device(src_node)
        return None

    def device_from_output(self, node, slot):
        for tnode, _ in self.graph.output_targets(node, slot):
            if tnode["type"].startswith("device/"):
                return self.get_device(tnode)
        return None

    def default_device(self):
        return next(iter(self.devices.values()), None)

    def capture_evidence(self, node_id):
        """抓当前帧作为失败证据；返回引用(URL/文件名)或 None。"""
        if self.evidence_sink is None:
            return None
        dev = self.default_device()
        if dev is None:
            return None
        try:
            frame = dev.capture()
            return self.evidence_sink(node_id, frame)
        except Exception:
            return None

    # ---- exec 走图 ----
    def run_chain_from(self, node):
        cur = node
        while cur is not None:
            check_abort()
            slot = self._run_node(cur)
            if slot is None:
                break
            cur = self.graph.next_exec(cur, slot)

    def run_branch(self, node, slot_name):
        target = self.graph.next_exec(node, slot_name)
        if target is not None:
            self.run_chain_from(target)

    def _run_node(self, node):
        h = HANDLERS.get(node["type"])
        if not h or "run" not in h:
            self.on_state(node["id"], "skip", "")
            return None
        self.on_state(node["id"], "running", "")
        try:
            nxt = h["run"](self, node)
        except ScriptAborted:
            raise
        except Exception as e:
            ref = self.capture_evidence(node["id"])
            self.report.add_error(node["id"], str(e), ref)
            self.on_state(node["id"], "fail", str(e))
            raise
        # 自报状态的节点（断言/日志）不再补 ok，避免把 fail 覆盖掉
        if node["type"] not in _SELF_REPORT:
            self.on_state(node["id"], "ok", "")
        return nxt


class Engine:
    def __init__(self, graph_data: dict):
        self.graph = GraphModel(graph_data)

    def run(self, on_state=None, abort_event=None, device_provider=None, evidence_sink=None,
            on_event=None):
        from .report import Report
        report = Report()
        abort_event = abort_event or threading.Event()
        provider = device_provider or _default_device_provider
        ctx = RunContext(self.graph, on_state, abort_event, provider, report,
                         evidence_sink=evidence_sink, on_event=on_event)

        visauto.set_abort_event(abort_event)
        try:
            starts = self.graph.nodes_of_type("flow/start")
            if not starts:
                raise RuntimeError("流程缺少「开始」节点")
            ctx.run_chain_from(starts[0])
            report.finalize()
        except ScriptAborted:
            report.finalize("已中止")
        except Exception as e:
            report.finalize(str(e))
        finally:
            visauto.clear_abort_event()
            _cleanup_owned(ctx)
        return report


# ======================= 默认设备 provider =======================
_OWNED = "__owned_session__"


def _default_device_provider(device_node):
    from ..devices import DeviceSession
    kind = device_node["type"].split("/")[1]
    config = dict(device_node.get("properties") or {})
    sess = DeviceSession(id=f"run-{device_node['id']}", kind=kind, config=config)
    sess.connect()
    setattr(sess.device, _OWNED, sess)
    return sess.device


def _cleanup_owned(ctx: RunContext):
    for dev in ctx.devices.values():
        sess = getattr(dev, _OWNED, None)
        if sess is not None:
            sess.close()


# ======================= 节点处理器 =======================
# ---- 设备（exec 经过时确保连接，再放行）----
def _run_device(ctx, node):
    ctx.get_device(node)   # 连接/复用设备
    return "out"


def _eval_device(ctx, node):
    dev = ctx.get_device(node)   # 屏幕尺寸（按需连接设备）
    return {"width": int(dev.w), "height": int(dev.h)}


for _dt in ("device/local", "device/novnc", "device/rdp", "device/pve", "device/vmware"):
    HANDLERS.setdefault(_dt, {})["run"] = _run_device
    HANDLERS[_dt]["eval"] = _eval_device


# ---- 纯数据（eval）----
@handler("const/image", "eval")
def _eval_image(ctx, node):
    name = ctx.graph.prop(node, "name", "")
    return {"picture": visauto.Image(name)} if name else {"picture": None}


@handler("vision/preview", "eval")
def _eval_preview(ctx, node):
    return {"picture": ctx.get_input(node, "picture")}   # 透传，仅用于查看


@handler("mask/create", "eval")
def _eval_mask(ctx, node):
    """遮罩节点：加载绘制好的遮罩图（白=参与匹配 255 / 黑=忽略 0），输出灰度 ndarray。"""
    name = ctx.graph.prop(node, "mask", "")
    if not name:
        return {"mask": None}
    import cv2
    mat = visauto.Image(name).mat
    return {"mask": cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)}


@handler("const/text", "eval")
def _eval_text(ctx, node):
    return {"text": ctx.graph.prop(node, "value", "")}


@handler("const/point", "eval")
def _eval_point_const(ctx, node):
    xi, yi = ctx.get_input(node, "x"), ctx.get_input(node, "y")
    x = int(xi) if xi is not None else int(ctx.graph.prop(node, "x", 0))
    y = int(yi) if yi is not None else int(ctx.graph.prop(node, "y", 0))
    return {"point": visauto.Location(x, y)}


@handler("const/number", "eval")
def _eval_number(ctx, node):
    return {"number": ctx.graph.prop(node, "value", 0)}


@handler("const/bool", "eval")
def _eval_bool(ctx, node):
    return {"bool": bool(ctx.graph.prop(node, "value", False))}


@handler("var/get", "eval")
def _eval_var_get(ctx, node):
    return {"value": ctx.vars.get(ctx.graph.prop(node, "name", "v"))}


# ---- 控制流（run）----
@handler("flow/start", "run")
def _run_start(ctx, node):
    return "out"


@handler("flow/if", "run")
def _run_if(ctx, node):
    return "true" if ctx.get_input(node, "cond") else "false"


@handler("flow/loop", "run")
def _run_loop(ctx, node):
    count = ctx.get_input(node, "count")
    count = int(count if count is not None else 0)
    for _ in range(max(0, count)):
        check_abort()
        ctx.run_branch(node, "body")
    return "done"


@handler("flow/sequence", "run")
def _run_sequence(ctx, node):
    # 出口可动态增减：按槽位顺序依次执行所有 exec 出口分支
    for slot in node.get("outputs") or []:
        if slot.get("type") == "exec":
            ctx.run_branch(node, slot.get("name"))
    return None


# ---- 等待 ----
@handler("wait/delay", "run")
def _run_delay(ctx, node):
    secs = float(ctx.graph.prop(node, "seconds", 1.0))
    end = time.monotonic() + secs
    while time.monotonic() < end:
        check_abort()
        time.sleep(min(0.1, end - time.monotonic()))
    return "out"


@handler("wait/appear", "run")
def _run_wait_appear(ctx, node):
    dev = _need_dev_in(ctx, node)
    tmpl = ctx.get_input(node, "template")
    timeout = float(ctx.graph.prop(node, "timeout", 10))
    m = dev.exists(Pattern(tmpl), timeout=timeout)
    ctx.set_output(node, "match", m)
    return "out" if m is not None else "timeout"


@handler("wait/vanish", "run")
def _run_wait_vanish(ctx, node):
    dev = _need_dev_in(ctx, node)
    tmpl = ctx.get_input(node, "template")
    timeout = float(ctx.graph.prop(node, "timeout", 10))
    gone = dev.wait_vanish(Pattern(tmpl), timeout=timeout)
    return "out" if gone else "timeout"


# ---- 查找 ----
@handler("vision/find_image", "run")
def _run_find_image(ctx, node):
    dev = _need_dev_in(ctx, node)
    tmpl = ctx.get_input(node, "template")
    if tmpl is None:
        raise RuntimeError("找图节点缺少模板")
    mask = ctx.get_input(node, "mask")   # 可选遮罩（ndarray，255 参与/0 忽略）
    sim = float(ctx.graph.prop(node, "similarity", 0.7))
    timeout = float(ctx.graph.prop(node, "timeout", 0))
    m = dev.exists(Pattern(tmpl, similarity=sim, mask=mask), timeout=timeout)
    ctx.set_output(node, "match", m)
    ctx.set_output(node, "ok", m is not None)
    return "found" if m is not None else "notFound"


@handler("vision/find_text", "run")
def _run_find_text(ctx, node):
    dev = _need_dev_in(ctx, node)
    text = ctx.get_input(node, "text") or ""
    ocr = ctx.get_input(node, "ocr")   # 可选；缺省回退会话默认引擎
    regex = bool(ctx.graph.prop(node, "regex", False))
    timeout = float(ctx.graph.prop(node, "timeout", 0))
    m = dev.exists(text=text, regex=regex, ocr=ocr, timeout=timeout)
    ctx.set_output(node, "match", m)
    ctx.set_output(node, "ok", m is not None)
    return "found" if m is not None else "notFound"


# ---- OCR 引擎（构造较重，按配置全局缓存复用）----
_OCR_CACHE: dict = {}


@handler("ocr/tesseract", "eval")
def _eval_ocr_tesseract(ctx, node):
    key = ("tesseract", ctx.graph.prop(node, "lang", "eng"),
           ctx.graph.prop(node, "config", ""), float(ctx.graph.prop(node, "min_confidence", 0)))
    eng = _OCR_CACHE.get(key)
    if eng is None:
        from visauto.ocr.tesseract import TesseractEngine
        eng = TesseractEngine(lang=key[1], config=key[2], min_confidence=key[3])
        _OCR_CACHE[key] = eng
    return {"ocr": eng}


@handler("ocr/paddle", "eval")
def _eval_ocr_paddle(ctx, node):
    key = ("paddle", ctx.graph.prop(node, "ocr_version", "auto"),
           ctx.graph.prop(node, "lang", "ch"),
           bool(ctx.graph.prop(node, "use_gpu", False)),
           bool(ctx.graph.prop(node, "use_angle_cls", True)),
           bool(ctx.graph.prop(node, "det", True)),
           float(ctx.graph.prop(node, "min_confidence", 0)))
    eng = _OCR_CACHE.get(key)
    if eng is None:
        from visauto.ocr.paddle import PaddleEngine
        eng = PaddleEngine(ocr_version=key[1], lang=key[2], use_gpu=key[3],
                           use_angle_cls=key[4], det=key[5], min_confidence=key[6])
        _OCR_CACHE[key] = eng
    return {"ocr": eng}


@handler("vision/find_all", "run")
def _run_find_all(ctx, node):
    dev = _need_dev_in(ctx, node)
    tmpl = ctx.get_input(node, "template")
    sim = float(ctx.graph.prop(node, "similarity", 0.7))
    ms = dev.find_all(Pattern(tmpl, similarity=sim))
    ctx.set_output(node, "matches", ms)
    ctx.set_output(node, "count", len(ms))
    return "out"


# ---- 坐标转换（Match → Point）----
def _match_to_point(m, anchor="center", dx=0, dy=0):
    """Match → Location：按锚点取矩形位置再加偏移。m 为 None 时返回 None。"""
    if m is None:
        return None
    dx, dy = int(dx), int(dy)
    if anchor == "top-left":
        x, y = m.x, m.y
    elif anchor == "top-right":
        x, y = m.x + m.w, m.y
    elif anchor == "bottom-left":
        x, y = m.x, m.y + m.h
    elif anchor == "bottom-right":
        x, y = m.x + m.w, m.y + m.h
    else:  # center
        c = m.center
        x, y = c.x, c.y
    return visauto.Location(x + dx, y + dy)


@handler("geom/to_point", "eval")
def _eval_to_point(ctx, node):
    m = ctx.get_input(node, "match")
    anchor = ctx.graph.prop(node, "anchor", "center")
    dx, dy = ctx.graph.prop(node, "dx", 0), ctx.graph.prop(node, "dy", 0)
    return {"point": _match_to_point(m, anchor, dx, dy)}


# ---- 动作（按点坐标执行；设备经 mouse 输出连线解析）----
def _xy(p):
    """点坐标取 (x, y)；兼容直接传入 Match/Region（取中心）。"""
    c = getattr(p, "center", None)
    if c is not None:
        return c.x, c.y
    return p.x, p.y


def _mouse_dev(ctx, node):
    dev = ctx.device_from_output(node, "mouse") or ctx.default_device()
    if dev is None:
        raise RuntimeError("动作节点未连到设备(Mouse)")
    return dev


@handler("action/click", "run")
def _run_click(ctx, node):
    p = ctx.get_input(node, "target")
    if p is None:
        raise RuntimeError("点击节点缺少目标点(target)")
    x, y = _xy(p)
    dev = _mouse_dev(ctx, node)
    if ctx.graph.prop(node, "double", False):
        dev.mouse.double_click(x, y)
    elif ctx.graph.prop(node, "button", "left") == "right":
        dev.mouse.right_click(x, y)
    else:
        dev.mouse.click(x, y)
    return "out"


@handler("action/type", "run")
def _run_type(ctx, node):
    text = ctx.get_input(node, "text") or ""
    dev = ctx.device_from_output(node, "keyboard") or ctx.default_device()
    if dev is None:
        raise RuntimeError("输入节点未连到设备(Keyboard)")
    if ctx.graph.prop(node, "paste", False):
        dev.paste(text)
    else:
        dev.type(text)
    return "out"


@handler("action/scroll", "run")
def _run_scroll(ctx, node):
    p = ctx.get_input(node, "target")
    if p is None:
        raise RuntimeError("滚动节点缺少目标点(target)")
    x, y = _xy(p)
    dy = int(ctx.graph.prop(node, "dy", -1))
    _mouse_dev(ctx, node).mouse.scroll(x, y, 0, dy)
    return "out"


@handler("action/drag", "run")
def _run_drag(ctx, node):
    src = ctx.get_input(node, "src")
    dst = ctx.get_input(node, "dst")
    if src is None or dst is None:
        raise RuntimeError("拖拽节点缺少 src/dst 点")
    sx, sy = _xy(src)
    dx, dy = _xy(dst)
    _mouse_dev(ctx, node).mouse.drag_drop(sx, sy, dx, dy)
    return "out"


# ---- 断言/结果 ----
@handler("assert/check", "run")
def _run_assert(ctx, node):
    cond = bool(ctx.get_input(node, "cond"))
    msg = ctx.graph.prop(node, "message", "")
    evidence = None if cond else ctx.capture_evidence(node["id"])
    ctx.report.add_assert(cond, msg, node["id"], evidence=evidence)
    ctx.on_state(node["id"], "ok" if cond else "fail", msg)
    return "pass" if cond else "fail"


@handler("test/result", "run")
def _run_result(ctx, node):
    return None


# ---- 变量/脚本/日志 ----
@handler("var/set", "run")
def _run_var_set(ctx, node):
    # 动态端口：每个数据输入端口名 = 变量名，一次可设多个
    for inp in node.get("inputs") or []:
        nm = inp.get("name")
        if not nm or inp.get("type") == "exec":
            continue
        ctx.vars[nm] = ctx.get_input(node, nm)
    return "out"


@handler("util/log", "run")
def _run_log(ctx, node):
    label = ctx.graph.prop(node, "label", "")
    val = ctx.get_input(node, "value")
    line = f"{label}: {val}" if label else str(val)
    ctx.report.log(line)
    ctx.on_state(node["id"], "ok", line)
    return "out"


@handler("util/alert", "run")
def _run_alert(ctx, node):
    val = ctx.get_input(node, "text")
    msg = str(val) if val not in (None, "") else ctx.graph.prop(node, "message", "")
    level = ctx.graph.prop(node, "level", "info")
    ctx.emit({"type": "alert", "id": node["id"], "level": level, "message": msg})
    ctx.report.log(f"[提示] {msg}")
    ctx.on_state(node["id"], "ok", msg)
    return "out"


class ScriptAPI:
    """脚本节点可用的「组件功能函数」：等价于各内置组件的运行逻辑，作用于默认设备。

    注入到脚本命名空间（既可经 flow.xxx 调用，常用函数也直接以同名暴露）。
    """

    def __init__(self, ctx, node):
        self._ctx = ctx
        self._node = node

    @property
    def dev(self):
        d = self._ctx.default_device()
        if d is None:
            raise RuntimeError("脚本节点未连到任何设备")
        return d

    @staticmethod
    def image(name):
        """按文件名加载模板图片（等价「模板图片」组件）。"""
        return visauto.Image(name)

    def _pattern(self, template, similarity=0.7, mask=None):
        if isinstance(template, Pattern):
            return template
        return Pattern(template, similarity=similarity, mask=mask)

    def find_image(self, template, similarity=0.7, mask=None, timeout=0):
        """找图（等价「找图」组件）：命中返回 Match，否则 None。"""
        return self.dev.exists(self._pattern(template, similarity, mask), timeout=timeout)

    def find_text(self, text, regex=False, ocr=None, timeout=0):
        """找文字（等价「找文字(OCR)」组件）：命中返回 Match，否则 None。"""
        return self.dev.exists(text=text, regex=regex, ocr=ocr, timeout=timeout)

    def find_all(self, template, similarity=0.7):
        """找全部（等价「找全部」组件）：返回 Match 列表。"""
        return self.dev.find_all(self._pattern(template, similarity))

    def wait_appear(self, template, timeout=10):
        """等出现（等价「等出现」组件）：出现返回 Match，超时返回 None。"""
        return self.dev.exists(self._pattern(template), timeout=timeout)

    def wait_vanish(self, template, timeout=10):
        """等消失（等价「等消失」组件）：消失返回 True，超时返回 False。"""
        return self.dev.wait_vanish(self._pattern(template), timeout=timeout)

    @staticmethod
    def to_point(match, anchor="center", dx=0, dy=0):
        """坐标转换（等价「坐标转换」组件）：Match → Location。"""
        return _match_to_point(match, anchor, dx, dy)

    def click(self, target, button="left", double=False):
        """点击（等价「点击」组件）。target 可为 Location/Match/点。"""
        x, y = _xy(target)
        if double:
            self.dev.mouse.double_click(x, y)
        elif button == "right":
            self.dev.mouse.right_click(x, y)
        else:
            self.dev.mouse.click(x, y)

    def type_text(self, text, paste=False):
        """输入文本（等价「输入文本」组件）。"""
        if paste:
            self.dev.paste(text)
        else:
            self.dev.type(text)

    def scroll(self, target, dy=-1):
        """滚动（等价「滚动」组件）。"""
        x, y = _xy(target)
        self.dev.mouse.scroll(x, y, 0, int(dy))

    def drag(self, src, dst):
        """拖拽（等价「拖拽」组件）：从 src 拖到 dst。"""
        sx, sy = _xy(src)
        dx, dy = _xy(dst)
        self.dev.mouse.drag_drop(sx, sy, dx, dy)

    def delay(self, seconds=1.0):
        """延时（等价「延时」组件）：可中止。"""
        end = time.monotonic() + float(seconds)
        while time.monotonic() < end:
            check_abort()
            time.sleep(min(0.1, end - time.monotonic()))

    def log(self, value, label=""):
        """日志（等价「日志」组件）：写入运行日志。"""
        self._ctx.report.log(f"{label}{value}" if label else str(value))

    def alert(self, message, level="info"):
        """提示（等价「提示」组件）：弹出非阻塞提示。"""
        self._ctx.emit({"type": "alert", "id": self._node["id"],
                        "level": level, "message": str(message)})
        self._ctx.report.log(f"[提示] {message}")

    def get_var(self, name, default=None):
        """取变量（等价「取变量」组件）。"""
        return self._ctx.vars.get(name, default)

    def set_var(self, name, value):
        """设变量（等价「设变量」组件）。"""
        self._ctx.vars[name] = value


@handler("script/python", "run")
def _run_script(ctx, node):
    code = ctx.graph.prop(node, "code", "")
    flow = ScriptAPI(ctx, node)
    ns = {
        "visauto": visauto,
        "dev": ctx.default_device(),
        "vars": ctx.vars,
        "Pattern": Pattern,
        "flow": flow,
        # 组件功能函数：直接可用
        "image": flow.image,
        "find_image": flow.find_image,
        "find_text": flow.find_text,
        "find_all": flow.find_all,
        "wait_appear": flow.wait_appear,
        "wait_vanish": flow.wait_vanish,
        "to_point": flow.to_point,
        "click": flow.click,
        "type_text": flow.type_text,
        "scroll": flow.scroll,
        "drag": flow.drag,
        "delay": flow.delay,
        "log": flow.log,
        "alert": flow.alert,
        "get_var": flow.get_var,
        "set_var": flow.set_var,
    }
    exec(compile(code, "<script-node>", "exec"), ns)
    return "out"


def _need_dev_in(ctx, node):
    dev = ctx.device_from_input(node, "video")
    if dev is None:
        raise RuntimeError(f"节点 {node.get('type')} 未连到设备(Video)")
    return dev
