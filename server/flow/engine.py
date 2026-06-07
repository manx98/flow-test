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

    def capture_evidence(self, node_id):
        """抓当前帧作为失败证据；返回引用(URL/文件名)或 None。

        设备解析已改为「值携带句柄」，断言节点本身不绑定设备，这里尽力而为：
        取任一已连接的设备抓一帧（仅用于报告截图，非控制路径）。
        """
        if self.evidence_sink is None:
            return None
        dev = next(iter(self.devices.values()), None)
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

    def report_error(self, node_id, exc, evidence=None):
        """在出错的源节点记录错误(报告+标红+消息)，并标记异常已上报，
        使上层链路节点只标红、不重复展示同一条错误。"""
        self.report.add_error(node_id, str(exc), evidence)
        self.on_state(node_id, "fail", str(exc))
        try:
            exc._flow_reported = True
        except Exception:
            pass

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
            if getattr(e, "_flow_reported", False):
                self.on_state(node["id"], "fail", "")   # 链路标红：错误已由触发节点展示，本层不重复
            else:
                self.report_error(node["id"], e, self.capture_evidence(node["id"]))
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
# ---- 设备：纯数据源，输出 device 句柄（被拉取时惰性连接/复用）----
def _eval_device(ctx, node):
    return {"device": ctx.get_device(node)}


for _dt in ("device/local", "device/novnc", "device/rdp", "device/pve", "device/vmware"):
    HANDLERS.setdefault(_dt, {})["eval"] = _eval_device


# ---- 设备属性：把 device 句柄拆成各能力端口（video/mouse/keyboard 的值都=该设备）----
@handler("device/attrs", "eval")
def _eval_device_attrs(ctx, node):
    dev = ctx.get_input(node, "device")
    if dev is None:
        return {}
    return {"video": dev, "mouse": dev, "keyboard": dev,
            "width": int(dev.w), "height": int(dev.h)}


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
    name = ctx.graph.prop(node, "name", "v")
    if name not in ctx.vars:
        # 变量未设置：错误归到取变量节点自身（标红+展示），上层拉取它的节点只标红
        exc = RuntimeError(f"取变量失败：变量「{name}」未设置（请先用「设变量」对它赋值）")
        ctx.report_error(node["id"], exc)
        raise exc
    return {"value": ctx.vars[name]}


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
    mask = ctx.get_input(node, "mask")   # 可选遮罩（255 参与/0 忽略）
    timeout = float(ctx.graph.prop(node, "timeout", 10))
    m = dev.exists(Pattern(tmpl, mask=mask), timeout=timeout)
    ctx.set_output(node, "match", m)
    _echo_match(ctx, node, dev, [m] if m is not None else [])
    return "out" if m is not None else "timeout"


@handler("wait/vanish", "run")
def _run_wait_vanish(ctx, node):
    dev = _need_dev_in(ctx, node)
    tmpl = ctx.get_input(node, "template")
    mask = ctx.get_input(node, "mask")   # 可选遮罩（255 参与/0 忽略）
    timeout = float(ctx.graph.prop(node, "timeout", 10))
    gone = dev.wait_vanish(Pattern(tmpl, mask=mask), timeout=timeout)
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
    _echo_match(ctx, node, dev, [m] if m is not None else [])
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
    _echo_match(ctx, node, dev, [m] if m is not None else [])
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
    _echo_match(ctx, node, dev, ms)
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
    """点坐标取 (x, y)；兼容 Match/Region（取中心）与 (x, y) 元组/列表（脚本里方便）。"""
    c = getattr(p, "center", None)
    if c is not None:
        return c.x, c.y
    if isinstance(p, (tuple, list)) and len(p) >= 2:
        return p[0], p[1]
    return p.x, p.y


def _mouse_dev(ctx, node):
    # mouse 输入的值即设备句柄（来自「设备属性」的 mouse 输出）
    dev = ctx.get_input(node, "mouse")
    if dev is None:
        raise RuntimeError("动作节点未连接设备(mouse)，请经「设备属性」接入")
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
    dev = ctx.get_input(node, "keyboard")   # keyboard 输入的值即设备句柄
    if dev is None:
        raise RuntimeError("输入文本节点未连接设备(keyboard)，请经「设备属性」接入")
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


class ScriptDevice:
    """脚本里的设备句柄：把各组件功能绑定到某一台设备，用「设备.方法()」调用。"""

    def __init__(self, dev):
        self._dev = dev

    @property
    def raw(self):
        """原始 visauto Device（dev.find / dev.mouse 等底层 API）。"""
        return self._dev

    def _pattern(self, template, similarity=0.7, mask=None):
        if isinstance(template, Pattern):
            return template
        return Pattern(template, similarity=similarity, mask=mask)

    def find_image(self, template, similarity=0.7, mask=None, timeout=0):
        """找图（等价「找图」）：命中返回 Match，否则 None。"""
        return self._dev.exists(self._pattern(template, similarity, mask), timeout=timeout)

    def find_text(self, text, regex=False, ocr=None, timeout=0):
        """找文字(OCR)（等价「找文字」）：命中返回 Match，否则 None。"""
        return self._dev.exists(text=text, regex=regex, ocr=ocr, timeout=timeout)

    def find_all(self, template, similarity=0.7):
        """找全部（等价「找全部」）：返回 Match 列表。"""
        return self._dev.find_all(self._pattern(template, similarity))

    def wait_appear(self, template, timeout=10, mask=None):
        """等出现（等价「等出现」）：出现返回 Match，超时 None。可选 mask 忽略部分区域。"""
        return self._dev.exists(self._pattern(template, mask=mask), timeout=timeout)

    def wait_vanish(self, template, timeout=10, mask=None):
        """等消失（等价「等消失」）：消失 True，超时 False。可选 mask 忽略部分区域。"""
        return self._dev.wait_vanish(self._pattern(template, mask=mask), timeout=timeout)

    def click(self, target, button="left", double=False):
        """点击（等价「点击」）。target 可为 Location/Match/点。"""
        x, y = _xy(target)
        if double:
            self._dev.mouse.double_click(x, y)
        elif button == "right":
            self._dev.mouse.right_click(x, y)
        else:
            self._dev.mouse.click(x, y)

    def type_text(self, text, paste=False):
        """输入文本（等价「输入文本」）。"""
        if paste:
            self._dev.paste(text)
        else:
            self._dev.type(text)

    def scroll(self, target, dy=-1):
        """滚动（等价「滚动」）。"""
        x, y = _xy(target)
        self._dev.mouse.scroll(x, y, 0, int(dy))

    def drag(self, src, dst):
        """拖拽（等价「拖拽」）：从 src 拖到 dst。"""
        sx, sy = _xy(src)
        dx, dy = _xy(dst)
        self._dev.mouse.drag_drop(sx, sy, dx, dy)


class ScriptGlobals:
    """脚本里设备无关的全局函数。"""

    def __init__(self, ctx, node):
        self._ctx = ctx
        self._node = node

    @staticmethod
    def image(name):
        """按文件名加载模板图片（等价「模板图片」）。"""
        return visauto.Image(name)

    @staticmethod
    def to_point(match, anchor="center", dx=0, dy=0):
        """坐标转换（等价「坐标转换」）：Match → Location。"""
        return _match_to_point(match, anchor, dx, dy)

    def delay(self, seconds=1.0):
        """延时（等价「延时」）：可中止。"""
        end = time.monotonic() + float(seconds)
        while time.monotonic() < end:
            check_abort()
            time.sleep(min(0.1, end - time.monotonic()))

    def log(self, value, label=""):
        """日志（等价「日志」）：写入运行日志。"""
        self._ctx.report.log(f"{label}{value}" if label else str(value))

    def alert(self, message, level="info"):
        """提示（等价「提示」）：弹出非阻塞提示。"""
        self._ctx.emit({"type": "alert", "id": self._node["id"],
                        "level": level, "message": str(message)})
        self._ctx.report.log(f"[提示] {message}")

    def get_var(self, name, default=None):
        """取变量（等价「取变量」）。"""
        return self._ctx.vars.get(name, default)

    def set_var(self, name, value):
        """设变量（等价「设变量」）。"""
        self._ctx.vars[name] = value


@handler("script/python", "run")
def _run_script(ctx, node):
    code = ctx.graph.prop(node, "code", "")
    g = ScriptGlobals(ctx, node)
    # 动态命名 device 输入：每个口名 → 设备句柄（devs[名]，合法标识符再注入同名变量）
    devs: dict = {}
    for slot in node.get("inputs") or []:
        if slot.get("type") == "device":
            d = ctx.get_input(node, slot.get("name"))
            if d is not None:
                devs[slot["name"]] = ScriptDevice(d)
    ns = {
        "visauto": visauto,
        "Pattern": Pattern,
        "vars": ctx.vars,
        "devs": devs,
        # 设备无关的全局函数
        "image": g.image,
        "to_point": g.to_point,
        "delay": g.delay,
        "log": g.log,
        "alert": g.alert,
        "get_var": g.get_var,
        "set_var": g.set_var,
    }
    for name, sd in devs.items():
        if name.isidentifier() and name not in ns:
            ns[name] = sd
    exec(compile(code, "<script-node>", "exec"), ns)
    return "out"


def _need_dev_in(ctx, node):
    # video 输入的值即设备句柄（来自「设备属性」的 video 输出）
    dev = ctx.get_input(node, "video")
    if dev is None:
        raise RuntimeError(f"节点 {node.get('type')} 未连接设备(video)，请经「设备属性」接入")
    return dev


def _echo_match(ctx, node, dev, matches):
    """抓当前帧并在命中区域画红框，存盘后通知前端在该节点上回显（找图/找文字/等出现用）。

    matches 为 Match 列表（可空）；无命中也回显原帧，便于查看当时画面。失败静默忽略。
    """
    sink = ctx.evidence_sink
    if sink is None or dev is None:
        return
    try:
        import cv2
        # 用与查找完全相同的取帧方式：_search 用 dev._capture()(=backend.capture(设备区域))，
        # 命中坐标即相对该帧。某些设备 capture()(全屏 None) 与之朝向/尺寸不一致，会让框落到帧外。
        frame = dev._capture() if hasattr(dev, "_capture") else dev.capture()
        ox, oy = int(getattr(dev, "x", 0)), int(getattr(dev, "y", 0))   # 区域原点(命中为绝对坐标)
        H, W = frame.shape[:2]
        # 标注画在副本上，再半透明叠加回原帧（alpha），既醒目又不挡住底图。
        # 线宽随分辨率，并在命中中心画十字(带白描边)，缩小显示仍可见。
        th = max(1, round(max(W, H) / 700))   # 1920 → ~3px
        ml = th * 3                           # 十字标记臂长
        alpha = 0.6                           # 标注不透明度
        red, white = (0, 0, 255), (255, 255, 255)
        overlay = frame.copy()
        drawn = False
        for m in matches:
            if m is None:
                continue
            drawn = True
            x, y = int(getattr(m, "x", 0)) - ox, int(getattr(m, "y", 0)) - oy
            w, h = int(getattr(m, "w", 0)), int(getattr(m, "h", 0))
            cx, cy = (x + w // 2, y + h // 2) if (w > 0 and h > 0) else (x, y)
            if w > 0 and h > 0:
                cv2.rectangle(overlay, (x - th, y - th), (x + w + th, y + h + th), white, th + 2)
                cv2.rectangle(overlay, (x - th, y - th), (x + w + th, y + h + th), red, th)
            for (dx, dy) in ((1, 0), (0, 1)):   # 十字：先白后红，任何背景都可见
                p1, p2 = (cx - dx * ml, cy - dy * ml), (cx + dx * ml, cy + dy * ml)
                cv2.line(overlay, p1, p2, white, th + 2)
                cv2.line(overlay, p1, p2, red, th)
        if drawn:
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        ref = sink(node["id"], frame)
        if ref:
            ctx.emit({"type": "node_shot", "id": node["id"], "url": ref})
    except Exception:
        pass
