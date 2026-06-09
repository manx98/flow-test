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

from ..i18n import tr
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
                 evidence_sink=None, on_event=None, lang: str = "zh"):
        self.graph = graph
        self.on_state = on_state or (lambda *a, **k: None)
        self.on_event = on_event or (lambda ev: None)   # 通用事件通道（如提示弹窗）
        self.abort = abort_event
        self.device_provider = device_provider
        self.report = report
        self.evidence_sink = evidence_sink   # callable(node_id, frame_bgr) -> ref|None
        self.lang = lang
        self.values: dict = {}        # (node_id, out_slot_idx) -> value（latched/memo）
        self.evaluated: set = set()   # 已 pure 求值的节点
        self.vars: dict = {}
        self.devices: dict = {}       # device_node_id -> Device
        self.catch_depth = 0           # >0 时节点异常由外层 try/catch 接管，不写入最终报告错误

    def tr(self, key: str, default: str = "", **vars):
        return tr(self.lang, key, default, **vars)

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
            try:
                outs = h["eval"](self, src_node) or {}
            except Exception as e:
                if not hasattr(e, "_flow_node_id"):
                    try:
                        e._flow_node_id = src_node["id"]
                        e._flow_node_type = src_node.get("type")
                    except Exception:
                        pass
                if self.catch_depth > 0 and not getattr(e, "_flow_reported", False):
                    self.on_state(src_node["id"], "fail", str(e))
                    try:
                        e._flow_reported = True
                    except Exception:
                        pass
                raise
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
        if not hasattr(exc, "_flow_node_id"):
            try:
                exc._flow_node_id = node_id
            except Exception:
                pass
        if self.catch_depth <= 0:
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
            if not hasattr(e, "_flow_node_id"):
                try:
                    e._flow_node_id = node["id"]
                    e._flow_node_type = node.get("type")
                except Exception:
                    pass
            if getattr(e, "_flow_reported", False):
                self.on_state(node["id"], "fail", "")   # 链路标红：错误已由触发节点展示，本层不重复
            elif self.catch_depth > 0:
                self.on_state(node["id"], "fail", str(e))
                try:
                    e._flow_reported = True
                except Exception:
                    pass
            else:
                self.report_error(node["id"], e, self.capture_evidence(node["id"]))
            raise
        # 自报状态的节点（断言/日志）不再补 ok，避免把 fail 覆盖掉
        if node["type"] not in _SELF_REPORT:
            self.on_state(node["id"], "ok", "")
        return nxt


class Engine:
    def __init__(self, graph_data: dict, lang: str = "zh"):
        self.graph = GraphModel(graph_data)
        self.lang = lang

    def run(self, on_state=None, abort_event=None, device_provider=None, evidence_sink=None,
            on_event=None):
        from .report import Report
        report = Report()
        abort_event = abort_event or threading.Event()
        provider = device_provider or _default_device_provider
        ctx = RunContext(self.graph, on_state, abort_event, provider, report,
                         evidence_sink=evidence_sink, on_event=on_event, lang=self.lang)

        visauto.set_abort_event(abort_event)
        try:
            starts = self.graph.nodes_of_type("flow/start")
            if not starts:
                raise RuntimeError(tr(self.lang, "engine.missing_start", "流程缺少「开始」节点"))
            ctx.run_chain_from(starts[0])
            report.finalize()
        except ScriptAborted:
            report.finalize(tr(self.lang, "engine.aborted", "已中止"))
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
        exc = RuntimeError(ctx.tr(
            "engine.var_not_set",
            "取变量失败：变量「{name}」未设置（请先用「设变量」对它赋值）",
            name=name))
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


@handler("flow/try_catch", "run")
def _run_try_catch(ctx, node):
    caught = None
    ctx.catch_depth += 1
    try:
        ctx.run_branch(node, "try")
    except ScriptAborted:
        raise
    except Exception as e:
        caught = e
    finally:
        ctx.catch_depth -= 1

    if caught is None:
        return "done"

    ctx.set_output(node, "error", str(caught))
    ctx.set_output(node, "error_type", type(caught).__name__)
    ctx.set_output(node, "error_node", getattr(caught, "_flow_node_id", None))
    ctx.on_state(node["id"], "ok", ctx.tr("engine.caught", "已捕获：{error}", error=caught))
    ctx.run_branch(node, "catch")
    return "done"


@handler("flow/raise", "run")
def _run_raise(ctx, node):
    msg = ctx.get_input(node, "message")
    if msg in (None, ""):
        msg = ctx.graph.prop(node, "message", ctx.tr("engine.raise_default", "主动抛出异常"))
    raise RuntimeError(str(msg))


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
        raise RuntimeError(ctx.tr("engine.find_image_missing_template", "找图节点缺少模板"))
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


# ---- AI 视觉引擎（构造惰性，按配置全局缓存复用）----
_AI_CACHE: dict = {}


@handler("ai/engine", "eval")
def _eval_ai_engine(ctx, node):
    p = ctx.graph.prop
    key = ("ai", p(node, "provider", "openai"), p(node, "base_url", ""),
           p(node, "model", "gpt-4o"), p(node, "api_key", ""),
           float(p(node, "temperature", 0)))
    eng = _AI_CACHE.get(key)
    if eng is None:
        from visauto.ai.engine import AIEngine
        eng = AIEngine(provider=key[1], base_url=key[2], model=key[3],
                       api_key=key[4], temperature=key[5])
        _AI_CACHE[key] = eng
    return {"ai": eng}


def _run_ai_find(ctx, node, kind):
    dev = _need_dev_in(ctx, node)
    ai = ctx.get_input(node, "ai")
    if ai is None:
        raise RuntimeError(ctx.tr("engine.ai_find_missing_engine", "AI 查找未连接「AI 引擎」(ai 输入)"))
    desc = ctx.get_input(node, "desc")
    if desc in (None, ""):
        desc = ctx.graph.prop(node, "prompt", "")
    if not desc:
        raise RuntimeError(ctx.tr("engine.ai_find_missing_desc", "AI 查找缺少描述（连 desc 或填 prompt 属性）"))
    m = dev.ai_locate(desc, ai=ai, kind=kind)
    minc = float(ctx.graph.prop(node, "min_confidence", 0))
    if m is not None and getattr(m, "score", 1.0) < minc:
        m = None
    ctx.set_output(node, "match", m)
    ctx.set_output(node, "ok", m is not None)
    _echo_match(ctx, node, dev, [m] if m is not None else [])
    return "found" if m is not None else "notFound"


@handler("ai/find_image", "run")
def _run_ai_find_image(ctx, node):
    return _run_ai_find(ctx, node, "image")


@handler("ai/find_text", "run")
def _run_ai_find_text(ctx, node):
    return _run_ai_find(ctx, node, "text")


def _echo_agent_step(ctx, node, frame, target):
    """AI 交互每步回显：在 AI 看到的帧上标注本步落点（点击/滚动点），推 node_shot。"""
    sink = ctx.evidence_sink
    if sink is None or frame is None:
        return
    try:
        import cv2
        out = frame
        if target is not None:
            H, W = frame.shape[:2]
            th = max(1, round(max(W, H) / 700))
            ml = th * 6
            cx, cy = int(target[0]), int(target[1])
            red, white = (0, 0, 255), (255, 255, 255)
            overlay = frame.copy()
            cv2.circle(overlay, (cx, cy), ml, red, th)
            for (dx, dy) in ((1, 0), (0, 1)):
                p1, p2 = (cx - dx * ml, cy - dy * ml), (cx + dx * ml, cy + dy * ml)
                cv2.line(overlay, p1, p2, white, th + 2)
                cv2.line(overlay, p1, p2, red, th)
            out = frame.copy()
            cv2.addWeighted(overlay, 0.6, out, 0.4, 0, out)
        ref = sink(node["id"], out)
        if ref:
            ctx.emit({"type": "node_shot", "id": node["id"], "url": ref})
    except Exception:
        pass


@handler("io/ai_agent", "run")
def _run_ai_agent(ctx, node):
    dev = ctx.get_input(node, "device")
    if dev is None:
        raise RuntimeError(ctx.tr("engine.ai_agent_missing_device", "AI 交互未连接设备(device 输入)"))
    ai = ctx.get_input(node, "ai")
    if ai is None:
        raise RuntimeError(ctx.tr("engine.ai_agent_missing_engine", "AI 交互未连接「AI 引擎」(ai 输入)"))
    goal = ctx.get_input(node, "goal")
    if goal in (None, ""):
        goal = ctx.graph.prop(node, "prompt", "")
    if not goal:
        raise RuntimeError(ctx.tr("engine.ai_agent_missing_goal", "AI 交互缺少目标（连 goal 或填 prompt 属性）"))
    max_steps = int(ctx.graph.prop(node, "max_steps", 15))

    from visauto.ai.agent import _action_brief

    def on_step(step, action, screen, target):
        _echo_agent_step(ctx, node, screen, target)
        if action.get("action") != "finish":
            ctx.report.log(ctx.tr(
                "engine.ai_step", "[AI第{step}步] {reasoning} → {action}",
                step=step, reasoning=action.get("reasoning", ""), action=_action_brief(action)))

    ok, msg, steps = dev.ai_agent(goal, ai=ai, max_steps=max_steps, on_step=on_step)
    ctx.report.log(ctx.tr(
        "engine.ai_done", "[AI交互] {status}（{steps}步）：{message}",
        status=ctx.tr("engine.done", "完成") if ok else ctx.tr("engine.failed", "失败"),
        steps=steps, message=msg))
    ctx.set_output(node, "result", msg)
    ctx.set_output(node, "ok", ok)
    ctx.set_output(node, "steps", steps)
    return "done" if ok else "failed"


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
        raise RuntimeError(ctx.tr("engine.action_missing_mouse", "动作节点未连接设备(mouse)，请经「设备属性」接入"))
    return dev


@handler("action/click", "run")
def _run_click(ctx, node):
    p = ctx.get_input(node, "target")
    if p is None:
        raise RuntimeError(ctx.tr("engine.click_missing_target", "点击节点缺少目标点(target)"))
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
        raise RuntimeError(ctx.tr("engine.type_missing_keyboard", "输入文本节点未连接设备(keyboard)，请经「设备属性」接入"))
    if ctx.graph.prop(node, "paste", False):
        dev.paste(text)
    else:
        dev.type(text)
    return "out"


@handler("action/hotkey", "run")
def _run_hotkey(ctx, node):
    keys = ctx.get_input(node, "keys")
    if keys in (None, ""):
        keys = ctx.graph.prop(node, "keys", "")
    keys = str(keys or "").strip()
    if not keys:
        raise RuntimeError(ctx.tr("engine.hotkey_missing_keys", "快捷键节点缺少按键"))
    dev = ctx.get_input(node, "keyboard")
    if dev is None:
        raise RuntimeError(ctx.tr("engine.type_missing_keyboard", "输入文本节点未连接设备(keyboard)，请经「设备属性」接入"))
    if ctx.graph.next_exec(node, "hold") is None:
        dev.keyboard.hotkey(keys)
    else:
        with dev.keyboard.hold(keys):
            ctx.run_branch(node, "hold")
    return "out"


@handler("action/scroll", "run")
def _run_scroll(ctx, node):
    p = ctx.get_input(node, "target")
    if p is None:
        raise RuntimeError(ctx.tr("engine.scroll_missing_target", "滚动节点缺少目标点(target)"))
    x, y = _xy(p)
    dy = int(ctx.graph.prop(node, "dy", -1))
    _mouse_dev(ctx, node).mouse.scroll(x, y, 0, dy)
    return "out"


@handler("action/drag", "run")
def _run_drag(ctx, node):
    src = ctx.get_input(node, "src")
    dst = ctx.get_input(node, "dst")
    if src is None or dst is None:
        raise RuntimeError(ctx.tr("engine.drag_missing_points", "拖拽节点缺少 src/dst 点"))
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
    ctx.report.log(ctx.tr("engine.alert_log", "[提示] {message}", message=msg))
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

    def ai_find_image(self, desc, ai):
        """AI 找图（等价「AI 找图」）：按描述用大模型定位，命中返回 Match，否则 None。"""
        return self._dev.ai_locate(desc, ai=ai, kind="image")

    def ai_find_text(self, desc, ai):
        """AI 找文字（等价「AI 找文字」）：按语义用大模型定位，命中返回 Match，否则 None。"""
        return self._dev.ai_locate(desc, ai=ai, kind="text")

    def ai_agent(self, goal, ai, max_steps=15):
        """AI 计算机操作代理（等价「AI 交互」）：自主多步操控完成 goal，返回 (ok, message, steps)。"""
        return self._dev.ai_agent(goal, ai=ai, max_steps=max_steps)

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

    def hotkey(self, keys):
        """快捷键（等价「快捷键」）：按下并释放组合键。"""
        self._dev.keyboard.hotkey(keys)

    def hold_keys(self, keys):
        """按住快捷键（等价「快捷键」hold 分支）：上下文退出时自动释放。"""
        return self._dev.keyboard.hold(keys)

    def scroll(self, target, dy=-1):
        """滚动（等价「滚动」）。"""
        x, y = _xy(target)
        self._dev.mouse.scroll(x, y, 0, int(dy))

    def drag(self, src, dst):
        """拖拽（等价「拖拽」）：从 src 拖到 dst。"""
        sx, sy = _xy(src)
        dx, dy = _xy(dst)
        self._dev.mouse.drag_drop(sx, sy, dx, dy)


class _ScriptCallable:
    """脚本里拿到的另一个脚本模块：可调用。helper(x=1) 用 kwargs 作入参运行，返回其 set_result 值。"""

    def __init__(self, ctx, node, sdef):
        self._ctx, self._node, self._def = ctx, node, sdef

    def __call__(self, **kwargs):
        return self._def.run(self._ctx, self._node, kwargs)


def _wrap(ctx, node, value):
    """脚本里取值的统一包装：设备→ScriptDevice，脚本定义→可调用，其余原样。"""
    if isinstance(value, visauto.Device):
        return ScriptDevice(value)
    if isinstance(value, ScriptDef):
        return _ScriptCallable(ctx, node, value)
    return value


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
        self._ctx.report.log(self._ctx.tr("engine.alert_log", "[提示] {message}", message=message))

    def get_var(self, name, default=None):
        """取变量（等价「取变量」）。设备/脚本值自动包装为 ScriptDevice/可调用。"""
        return _wrap(self._ctx, self._node, self._ctx.vars.get(name, default))

    def set_var(self, name, value):
        """设变量（等价「设变量」）。"""
        self._ctx.vars[name] = value


class ScriptDef:
    """脚本定义：持有代码；由「Python 执行」用入参调用，代码内 get_arg/set_result 交互。"""

    def __init__(self, code: str):
        self.code = code

    def run(self, ctx, node, args: dict) -> dict:
        """用 args 执行脚本，返回命名结果字典 {名: 值}（set_result 设置）。"""
        g = ScriptGlobals(ctx, node)
        results: dict = {}

        def get_arg(name, default=None):
            # 设备→ScriptDevice、脚本→可调用模块，其余原样
            return _wrap(ctx, node, args.get(name, default))

        def set_result(name, value):
            results[name] = value

        ns = {
            "visauto": visauto,
            "Pattern": Pattern,
            "vars": ctx.vars,
            "get_arg": get_arg,
            "set_result": set_result,
            # 设备无关的全局函数
            "image": g.image,
            "to_point": g.to_point,
            "delay": g.delay,
            "log": g.log,
            "alert": g.alert,
            "get_var": g.get_var,
            "set_var": g.set_var,
        }
        exec(compile(self.code, "<script-node>", "exec"), ns)
        return results


@handler("script/python", "eval")
def _eval_script_def(ctx, node):
    # 脚本定义节点：只输出一个可调用的脚本句柄，不自己执行
    return {"script": ScriptDef(ctx.graph.prop(node, "code", ""))}


@handler("script/exec", "run")
def _run_script_exec(ctx, node):
    sdef = ctx.get_input(node, "script")
    if sdef is None:
        raise RuntimeError(ctx.tr("engine.python_missing_script", "Python 执行未连接「Python 脚本」(script 输入)"))
    # 动态命名入参口 → args（排除 exec 与 script 定义口本身；script 类型的「参数」口仍纳入）
    args = {}
    for slot in node.get("inputs") or []:
        if slot.get("type") != "exec" and slot.get("name") != "script":
            args[slot["name"]] = ctx.get_input(node, slot["name"])
    results = sdef.run(ctx, node, args)
    for slot in node.get("outputs") or []:
        if slot.get("type") != "exec":
            ctx.set_output(node, slot["name"], results.get(slot["name"]))
    return "out"


class ToolDef:
    """agent 工具定义。invoke(ctx, args)：把参数写进 arg 输出口 → 触发 exec out 跑实现子流程
    → 读 result 输入口返回 {名:值}。供「Agent」节点按 name/description/args/results 调用。"""

    def __init__(self, node, name, description, args, results):
        self.node = node
        self.name = name
        self.description = description
        self.args = args          # [{name, type, desc}]
        self.results = results    # [{name, type, desc}]

    def invoke(self, ctx, arg_values: dict):
        for a in self.args:
            ctx.set_output(self.node, a["name"], arg_values.get(a["name"]))
        ctx.run_branch(self.node, "out")
        return {r["name"]: ctx.get_input(self.node, r["name"]) for r in self.results}


@handler("agent/tool", "eval")
def _eval_agent_tool(ctx, node):
    p = ctx.graph.prop
    adescs = p(node, "argDescs", {}) or {}
    rdescs = p(node, "resultDescs", {}) or {}
    args = [{"name": s["name"], "type": s["type"], "desc": adescs.get(s["name"], "")}
            for s in (node.get("outputs") or []) if s.get("type") not in ("exec", "tool")]
    results = [{"name": s["name"], "type": s["type"], "desc": rdescs.get(s["name"], "")}
               for s in (node.get("inputs") or []) if s.get("type") != "exec"]
    return {"tool": ToolDef(node, p(node, "name", "tool"), p(node, "description", ""), args, results)}


@handler("agent/run", "run")
def _run_agent(ctx, node):
    ai = ctx.get_input(node, "ai")
    if ai is None:
        raise RuntimeError(ctx.tr("engine.agent_missing_engine", "Agent 未连接「AI 引擎」(ai 输入)"))
    task = ctx.get_input(node, "task")
    if task in (None, ""):
        task = ctx.graph.prop(node, "prompt", "")
    if not task:
        raise RuntimeError(ctx.tr("engine.agent_missing_task", "Agent 缺少任务（连 task 或填 prompt 属性）"))
    max_steps = int(ctx.graph.prop(node, "max_steps", 10))
    # 收集 tool 输入口 → ToolDef + 给模型的 schema
    tools, schema = {}, []
    for slot in node.get("inputs") or []:
        if slot.get("type") == "tool":
            td = ctx.get_input(node, slot["name"])
            if td is not None:
                tools[td.name] = td
                schema.append({"name": td.name, "description": td.description,
                               "args": td.args, "results": td.results})

    def _emit(step, **kw):
        ctx.emit({"type": "agent_step", "id": node["id"], "step": step, **kw})

    history, ok, result = [], False, ""
    for step in range(1, max_steps + 1):
        check_abort()
        action = ai.next_tool_action(task, schema, "\n".join(history) or "(none)")
        reasoning = str(action.get("reasoning", ""))
        if action.get("action") == "finish":
            ok = bool(action.get("success"))
            result = str(action.get("result", ""))
            _emit(step, reasoning=reasoning, finish=True, success=ok, result=result)
            ctx.report.log(f"[Agent第{step}步] {reasoning} → finish(success={ok}): {result}")
            break
        tname = action.get("tool")
        args = action.get("args") or {}
        td = tools.get(tname)
        res = {"error": ctx.tr("engine.unknown_tool", "未知工具 {name}", name=tname)} if td is None else td.invoke(ctx, args)
        _emit(step, reasoning=reasoning, tool=str(tname), args=str(args), result=str(res))
        ctx.report.log(f"[Agent第{step}步] {reasoning} → {tname}({args}) = {res}")
        history.append(f"{step}. {reasoning} -> {tname}({args}) = {res}")
    else:
        result = ctx.tr("engine.agent_exceeded_steps", "超过最大步数 {max_steps}", max_steps=max_steps)
        ctx.report.log(ctx.tr("engine.agent_failed", "[Agent] 失败：{result}", result=result))
    ctx.set_output(node, "result", result)
    return "done" if ok else "failed"


def _need_dev_in(ctx, node):
    # video 输入的值即设备句柄（来自「设备属性」的 video 输出）
    dev = ctx.get_input(node, "video")
    if dev is None:
        raise RuntimeError(ctx.tr(
            "engine.video_missing_device",
            "节点 {type} 未连接设备(video)，请经「设备属性」接入",
            type=node.get("type")))
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
