"""节点目录：节点类型规格的单一真源（前端建 LiteGraph 面板、后端引擎据此校验）。

每个节点：type/category/title + description(组件说明) + inputs/outputs(端口) + properties(可配项)。
端口：{name, type, cardinality('*'|'1'|'n'), required(bool), kind('exec'|'data'), desc(说明)}。
属性：{name, type, default, ...?options, desc(说明)}。
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from . import types as T


def _ver(pkg: str) -> "str | None":
    """读已装包版本（不导入包本身，未装返回 None）。"""
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return None


def _engine_title(name: str, pkg: str) -> str:
    v = _ver(pkg)
    return f"{name} (v{v})" if v else f"{name} (未安装)"


# 变量 value 端口可选类型（自定义连接点类型）
_VAR_TYPES = [T.MATCH, T.POINT, T.TEXT, T.NUMBER, T.BOOL, T.PICTURE, T.MASK, T.OCR]


def _p(name, ptype, card="1", required=False, desc=""):
    return {"name": name, "type": ptype, "cardinality": card,
            "required": required, "kind": "exec" if ptype == T.EXEC else "data",
            "desc": desc}


def _exec_in(name="in", desc="执行入口：上游执行流到达即运行本节点"):
    return _p(name, T.EXEC, "1", True, desc)


def _exec_out(name="out", desc="执行出口：本节点完成后从这里继续"):
    return _p(name, T.EXEC, "1", False, desc)


def _pr(name, ptype, default=None, desc="", **extra):
    """属性（widget 配置项），带 desc 说明。"""
    return {"name": name, "type": ptype, "default": default, "desc": desc, **extra}


def _note():
    """常量节点的备注属性：仅供标注用途，不参与运行。"""
    return _pr("备注", "string", "", "备注：说明此常量的用途（仅展示，不参与运行）")


# 设备节点共享的输入/输出（仅属性不同）
def _device_inputs():
    return [_exec_in(),
            _p("mouse", T.MOUSE, "*", desc="鼠标控制：接「点击/滚动/拖拽」等动作的 mouse 输出，由本设备执行"),
            _p("keyboard", T.KEYBOARD, "*", desc="键盘控制：接「输入文本」等动作的 keyboard 输出，由本设备执行")]


def _device_outputs():
    return [_exec_out(),
            _p("video", T.VIDEO, "*", desc="设备实时画面：连「人机交互」显示，或连「找图/找文字/等待」作查找源"),
            _p("width", T.NUMBER, "*", desc="屏幕宽度（像素）；被拉取时会连接设备"),
            _p("height", T.NUMBER, "*", desc="屏幕高度（像素）；被拉取时会连接设备")]


# Python 脚本节点注入的内置函数(等价各组件)与对象，供「组件说明」详细展示
def _fn(sig, desc):
    return {"sig": sig, "desc": desc}


_SCRIPT_FUNCS = [
    _fn("image(name)", "按文件名加载模板图片（等价「模板图片」）"),
    _fn("find_image(template, similarity=0.7, mask=None, timeout=0)",
        "找图：在画面找模板，命中返回 Match，否则 None（等价「找图」）"),
    _fn("find_text(text, regex=False, ocr=None, timeout=0)",
        "找文字(OCR)：命中返回 Match，否则 None；ocr 缺省用会话默认引擎（等价「找文字」）"),
    _fn("find_all(template, similarity=0.7)", "找全部：返回所有命中的 Match 列表（等价「找全部」）"),
    _fn("wait_appear(template, timeout=10)", "等出现：出现返回 Match，超时返回 None（等价「等出现」）"),
    _fn("wait_vanish(template, timeout=10)", "等消失：消失返回 True，超时返回 False（等价「等消失」）"),
    _fn("to_point(match, anchor='center', dx=0, dy=0)",
        "Match→坐标点；anchor=center/top-left/…，再加偏移（等价「坐标转换」）"),
    _fn("click(target, button='left', double=False)", "在点坐标点击；target 可为 Location/Match（等价「点击」）"),
    _fn("type_text(text, paste=False)", "输入文本；paste=True 走剪贴板粘贴（等价「输入文本」）"),
    _fn("scroll(target, dy=-1)", "在点坐标滚动滚轮（等价「滚动」）"),
    _fn("drag(src, dst)", "从 src 点拖拽到 dst 点（等价「拖拽」）"),
    _fn("delay(seconds=1.0)", "延时若干秒，可被中止（等价「延时」）"),
    _fn("log(value, label='')", "把值写入运行日志（等价「日志」）"),
    _fn("alert(message, level='info')", "弹出非阻塞提示，level=info/warn/error（等价「提示」）"),
    _fn("get_var(name, default=None)", "读取 flow 变量（等价「取变量」）"),
    _fn("set_var(name, value)", "写入 flow 变量（等价「设变量」）"),
]

_SCRIPT_INJECTS = [
    {"name": "dev", "desc": "默认设备(visauto Device/Region)；可直接 dev.find / dev.click / dev.capture 等"},
    {"name": "visauto", "desc": "visauto 模块（Image / Pattern / Location / Region / Match / Key 等）"},
    {"name": "Pattern", "desc": "模板匹配类：Pattern(img, similarity=…, mask=…)"},
    {"name": "vars", "desc": "flow 变量字典（与 get_var/set_var 同一份）"},
    {"name": "flow", "desc": "上述内置函数所在对象，亦可 flow.find_image(...) 这样调用"},
]


# ---- 节点定义 ----
_NODES = [
    # ===== 设备 =====
    {"type": "device/local", "category": "设备", "title": "本地设备",
     "description": "本机屏幕作为被测设备：采集指定显示器画面，并把鼠标/键盘动作回放到本机。",
     "inputs": _device_inputs(), "outputs": _device_outputs(),
     "properties": [_pr("monitor", "int", 1, "显示器编号（多屏时选第几块，默认 1）")]},
    {"type": "device/novnc", "category": "设备", "title": "noVNC 设备",
     "description": "通过 VNC/websockify 连接远程桌面作为被测设备。依赖 websocket-client。",
     "inputs": _device_inputs(), "outputs": _device_outputs(),
     "properties": [_pr("url", "string", "ws://127.0.0.1:6080/websockify", "websockify 地址（ws/wss）"),
                    _pr("password", "password", "", "VNC 连接密码（可空）")]},
    {"type": "device/rdp", "category": "设备", "title": "RDP/xrdp 设备",
     "description": "通过 RDP 协议连接 Windows/xrdp 远程桌面作为被测设备。依赖 aardwolf。",
     "inputs": _device_inputs(), "outputs": _device_outputs(),
     "properties": [_pr("host", "string", "127.0.0.1", "RDP 主机地址"),
                    _pr("port", "int", 3389, "RDP 端口（默认 3389）"),
                    _pr("username", "string", "", "登录用户名"),
                    _pr("password", "password", "", "登录密码"),
                    _pr("domain", "string", "", "登录域（可空）"),
                    _pr("auth", "enum", "auto", "认证方式：auto 自动 / tls / nla",
                        options=["auto", "tls", "nla"]),
                    _pr("width", "int", 1280, "请求的桌面宽度"),
                    _pr("height", "int", 800, "请求的桌面高度")]},
    {"type": "device/pve", "category": "设备", "title": "PVE 设备",
     "description": "通过 Proxmox VE API 连接虚拟机控制台作为被测设备。仅需 websocket-client。",
     "inputs": _device_inputs(), "outputs": _device_outputs(),
     "properties": [_pr("host", "string", "127.0.0.1", "PVE 主机地址"),
                    _pr("port", "int", 8006, "PVE Web 端口（默认 8006）"),
                    _pr("node", "string", "pve", "PVE 节点名"),
                    _pr("vmid", "int", 100, "虚拟机 ID"),
                    _pr("vmtype", "enum", "qemu", "虚拟机类型：qemu(虚拟机) / lxc(容器)",
                        options=["qemu", "lxc"]),
                    _pr("username", "string", "root@pam", "登录用户名（含认证域，如 root@pam）"),
                    _pr("password", "password", "", "登录密码"),
                    _pr("verify_tls", "bool", False, "是否校验 TLS 证书")]},
    {"type": "device/vmware", "category": "设备", "title": "VMware 设备",
     "description": "通过 VMware WebMKS 连接虚拟机控制台作为被测设备。依赖 pyvmomi。",
     "inputs": _device_inputs(), "outputs": _device_outputs(),
     "properties": [_pr("host", "string", "127.0.0.1", "vCenter/ESXi 主机地址"),
                    _pr("port", "int", 443, "HTTPS 端口（默认 443）"),
                    _pr("username", "string", "", "登录用户名"),
                    _pr("password", "password", "", "登录密码"),
                    _pr("vm", "string", "", "目标虚拟机（名称或 MoID）"),
                    _pr("verify_tls", "bool", False, "是否校验 TLS 证书")]},

    # ===== 交互/显示 =====
    {"type": "io/interaction", "category": "交互", "title": "人机交互",
     "description": "在节点内显示上游设备的实时画面，鼠标移入即把鼠标/键盘转发回设备；可点「📷 截图」抓帧裁剪并自动生成模板图片节点。",
     "inputs": [_p("video", T.VIDEO, "1", desc="要显示并交互的设备画面")],
     "outputs": [_p("mouse", T.MOUSE, "*", desc="转发的鼠标控制（回连设备 mouse 输入）"),
                 _p("keyboard", T.KEYBOARD, "*", desc="转发的键盘控制（回连设备 keyboard 输入）")],
     "properties": [], "widget": "video"},

    # ===== 采集 =====
    {"type": "vision/preview", "category": "视觉", "title": "图片预览",
     "description": "显示连入的图片，支持滚轮缩放 / 右键拖拽平移；可串在图片连线中间查看，原样透传。",
     "inputs": [_p("picture", T.PICTURE, "1", True, desc="要预览的图片")],
     "outputs": [_p("picture", T.PICTURE, "*", desc="原样透传输入图片")],
     "properties": [], "widget": "preview"},

    # ===== 遮罩 =====
    {"type": "mask/create", "category": "视觉", "title": "创建遮罩",
     "description": "以上游模板图为底涂抹要忽略的区域生成遮罩（点「✏ 编辑遮罩」用画笔涂抹）。遮罩语义：白=参与匹配，涂抹处=忽略。",
     "inputs": [_p("picture", T.PICTURE, "1", True, desc="作为底图的模板图片")],
     "outputs": [_p("mask", T.MASK, "*", desc="生成的遮罩，连到「找图」的 mask 输入")],
     "properties": [_pr("mask", "image", "", "遮罩图（由「编辑遮罩」交互写入，无需手填）")], "widget": "mask"},

    # ===== 查找 =====
    {"type": "vision/find_image", "category": "视觉", "title": "找图",
     "description": "在设备画面上找模板图：命中走 found 并输出 match，否则走 notFound。可用 mask 忽略模板部分区域。",
     "script": "find_image(template, similarity=0.7, mask=None, timeout=0)",
     "inputs": [_exec_in(),
                _p("video", T.VIDEO, "1", True, desc="查找源画面（来自设备 video）"),
                _p("template", T.PICTURE, "1", desc="要查找的模板图片"),
                _p("mask", T.MASK, "1", desc="可选遮罩：涂抹处不参与匹配")],
     "outputs": [_exec_out("found", "命中分支：在画面中找到模板时走这里"),
                 _exec_out("notFound", "未命中分支：找不到模板时走这里"),
                 _p("match", T.MATCH, "*", desc="命中结果（位置矩形 + 相似度）"),
                 _p("ok", T.BOOL, desc="是否命中（true/false）")],
     "properties": [_pr("similarity", "number", 0.7, "相似度阈值（0~1，越高越严格）"),
                    _pr("timeout", "number", 0, "等待秒数：0=只查一次，>0=在超时内反复查直到命中")]},
    {"type": "vision/find_text", "category": "视觉", "title": "找文字(OCR)",
     "description": "用 OCR 在设备画面里查找文字：命中走 found 并输出 match，否则走 notFound。ocr 不接则用会话默认引擎。",
     "script": "find_text(text, regex=False, ocr=None, timeout=0)",
     "inputs": [_exec_in(),
                _p("video", T.VIDEO, "1", True, desc="查找源画面（来自设备 video）"),
                _p("text", T.TEXT, "1", desc="要查找的文字（或正则）"),
                _p("ocr", T.OCR, "1", desc="可选 OCR 引擎实例；不接用会话默认引擎")],
     "outputs": [_exec_out("found", "命中分支：识别到目标文字时走这里"),
                 _exec_out("notFound", "未命中分支：未识别到时走这里"),
                 _p("match", T.MATCH, "*", desc="命中文字的位置矩形 + 置信度"),
                 _p("ok", T.BOOL, desc="是否命中（true/false）")],
     "properties": [_pr("regex", "bool", False, "把 text 当正则表达式匹配"),
                    _pr("timeout", "number", 0, "等待秒数：0=只查一次，>0=在超时内反复查")]},
    {"type": "vision/find_all", "category": "视觉", "title": "找全部",
     "description": "找出画面中模板的所有匹配，输出匹配列表与数量。",
     "script": "find_all(template, similarity=0.7)",
     "inputs": [_exec_in(),
                _p("video", T.VIDEO, "1", True, desc="查找源画面（来自设备 video）"),
                _p("template", T.PICTURE, "1", desc="要查找的模板图片")],
     "outputs": [_exec_out(),
                 _p("matches", T.MATCH, "*", desc="所有命中结果的列表"),
                 _p("count", T.NUMBER, desc="命中数量")],
     "properties": [_pr("similarity", "number", 0.7, "相似度阈值（0~1）")]},

    # ===== OCR 引擎 =====
    {"type": "ocr/tesseract", "category": "OCR", "title": _engine_title("Tesseract 引擎", "pytesseract"),
     "description": "提供 Tesseract OCR 引擎实例，连到「找文字」的 ocr 输入。需 pytesseract + 系统 tesseract。引擎按配置全局缓存复用。",
     "inputs": [], "outputs": [_p("ocr", T.OCR, "*", desc="OCR 引擎实例（连到「找文字」的 ocr）")],
     "properties": [_pr("lang", "string", "eng", "识别语言（如 eng、chi_sim）"),
                    _pr("config", "string", "", "传给 tesseract 的额外配置参数"),
                    _pr("min_confidence", "number", 0, "最低置信度阈值（低于则丢弃）")]},
    {"type": "ocr/paddle", "category": "OCR", "title": _engine_title("PaddleOCR 引擎", "paddleocr"),
     "description": "提供 PaddleOCR 引擎实例，连到「找文字」的 ocr 输入。需 paddleocr+paddlepaddle，2.x/3.x API 自动适配。引擎全局缓存复用。",
     "inputs": [], "outputs": [_p("ocr", T.OCR, "*", desc="OCR 引擎实例（连到「找文字」的 ocr）")],
     "properties": [_pr("ocr_version", "enum", "auto", "模型版本：auto 自动 / PP-OCRv5 / v4 / v3",
                        options=["auto", "PP-OCRv5", "PP-OCRv4", "PP-OCRv3"]),
                    _pr("lang", "string", "ch", "识别语言（如 ch、en）"),
                    _pr("use_gpu", "bool", False, "是否用 GPU 加速"),
                    _pr("use_angle_cls", "bool", True, "是否启用方向分类（识别旋转文字）"),
                    _pr("det", "bool", True, "是否启用文字检测（关闭则只识别整图）"),
                    _pr("min_confidence", "number", 0, "最低置信度阈值")]},

    # ===== 坐标转换（Match → Point）=====
    {"type": "geom/to_point", "category": "动作", "title": "坐标转换",
     "description": "把找图/OCR 的 match 按锚点 + 偏移算成点坐标，供动作使用。",
     "script": "to_point(match, anchor='center', dx=0, dy=0)",
     "inputs": [_p("match", T.MATCH, "1", True, desc="找图/找文字输出的命中结果")],
     "outputs": [_p("point", T.POINT, "*", desc="算出的点坐标，供动作 target 使用")],
     "properties": [_pr("anchor", "enum", "center", "锚点：取矩形的哪个位置",
                        options=["center", "top-left", "top-right", "bottom-left", "bottom-right"]),
                    _pr("dx", "int", 0, "X 方向像素偏移"),
                    _pr("dy", "int", 0, "Y 方向像素偏移")]},

    # ===== 动作（入参为点坐标 Point）=====
    {"type": "action/click", "category": "动作", "title": "点击",
     "description": "在给定点坐标点击。mouse 输出需回连设备的 mouse 输入以解析目标设备。",
     "script": "click(target, button='left', double=False)",
     "inputs": [_exec_in(), _p("target", T.POINT, "1", desc="点击位置（点坐标）")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*", desc="鼠标控制，回连设备 mouse 输入")],
     "properties": [_pr("button", "enum", "left", "鼠标按键",
                        options=["left", "right", "middle"]),
                    _pr("double", "bool", False, "是否双击")]},
    {"type": "action/type", "category": "动作", "title": "输入文本",
     "description": "在当前焦点处输入文本。keyboard 输出需回连设备的 keyboard 输入。",
     "script": "type_text(text, paste=False)",
     "inputs": [_exec_in(), _p("text", T.TEXT, "1", desc="要输入的文本")],
     "outputs": [_exec_out(), _p("keyboard", T.KEYBOARD, "*", desc="键盘控制，回连设备 keyboard 输入")],
     "properties": [_pr("paste", "bool", False, "走剪贴板粘贴（适合长文本/中文）")]},
    {"type": "action/scroll", "category": "动作", "title": "滚动",
     "description": "在给定点坐标处滚动鼠标滚轮。mouse 输出需回连设备 mouse 输入。",
     "script": "scroll(target, dy=-1)",
     "inputs": [_exec_in(), _p("target", T.POINT, "1", desc="滚动位置（点坐标）")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*", desc="鼠标控制，回连设备 mouse 输入")],
     "properties": [_pr("dy", "int", -1, "滚动量（负=向下，正=向上）")]},
    {"type": "action/drag", "category": "动作", "title": "拖拽",
     "description": "从起点拖到终点。mouse 输出需回连设备 mouse 输入。",
     "script": "drag(src, dst)",
     "inputs": [_exec_in(),
                _p("src", T.POINT, "1", desc="拖拽起点"),
                _p("dst", T.POINT, "1", desc="拖拽终点")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*", desc="鼠标控制，回连设备 mouse 输入")],
     "properties": []},

    # ===== 等待 =====
    {"type": "wait/appear", "category": "等待", "title": "等出现",
     "description": "等模板在画面中出现：出现走 out 并输出 match，超时走 timeout 分支。",
     "script": "wait_appear(template, timeout=10)",
     "inputs": [_exec_in(),
                _p("video", T.VIDEO, "1", desc="监视的设备画面"),
                _p("template", T.PICTURE, "1", desc="要等待出现的模板图片")],
     "outputs": [_exec_out("out", "出现分支：模板出现时走这里"),
                 _exec_out("timeout", "超时分支：超时仍未出现时走这里"),
                 _p("match", T.MATCH, desc="出现时的命中结果")],
     "properties": [_pr("timeout", "number", 10, "最长等待秒数")]},
    {"type": "wait/vanish", "category": "等待", "title": "等消失",
     "description": "等模板从画面中消失：消失走 out，超时仍在走 timeout 分支。",
     "script": "wait_vanish(template, timeout=10)",
     "inputs": [_exec_in(),
                _p("video", T.VIDEO, "1", desc="监视的设备画面"),
                _p("template", T.PICTURE, "1", desc="要等待消失的模板图片")],
     "outputs": [_exec_out("out", "消失分支：模板消失时走这里"),
                 _exec_out("timeout", "超时分支：超时仍未消失时走这里")],
     "properties": [_pr("timeout", "number", 10, "最长等待秒数")]},
    {"type": "wait/delay", "category": "等待", "title": "延时",
     "description": "固定延时若干秒后继续。",
     "script": "delay(seconds=1.0)",
     "inputs": [_exec_in()], "outputs": [_exec_out()],
     "properties": [_pr("seconds", "number", 1.0, "延时秒数")]},

    # ===== 断言/结果 =====
    {"type": "assert/check", "category": "测试", "title": "断言",
     "description": "条件为真走 pass，否则走 fail；结果记入测试报告（失败自动抓帧存证据）。",
     "inputs": [_exec_in(), _p("cond", T.BOOL, "1", True, desc="要断言的布尔条件")],
     "outputs": [_exec_out("pass", "断言通过分支"),
                 _exec_out("fail", "断言失败分支")],
     "properties": [_pr("message", "string", "", "断言说明（记入报告）")]},
    {"type": "test/result", "category": "测试", "title": "测试结果",
     "description": "汇总所有断言，产出通过/失败结论与测试报告。",
     "inputs": [_exec_in()], "outputs": [], "properties": []},

    # ===== 控制流 =====
    {"type": "flow/start", "category": "控制流", "title": "开始",
     "description": "流程入口：运行从这里开始。",
     "inputs": [], "outputs": [_exec_out("out", "流程起点，连向第一个节点")], "properties": []},
    {"type": "flow/if", "category": "控制流", "title": "条件分支",
     "description": "按布尔条件走分支：真走 true，假走 false。",
     "inputs": [_exec_in(), _p("cond", T.BOOL, "1", True, desc="判断条件")],
     "outputs": [_exec_out("true", "条件为真分支"),
                 _exec_out("false", "条件为假分支")], "properties": []},
    {"type": "flow/loop", "category": "控制流", "title": "循环",
     "description": "循环执行：每轮走 body，达到次数后走 done。",
     "inputs": [_exec_in(), _p("count", T.NUMBER, "1", desc="循环次数")],
     "outputs": [_exec_out("body", "循环体分支：每轮执行"),
                 _exec_out("done", "结束分支：循环完成后走这里")], "properties": []},
    {"type": "flow/sequence", "category": "控制流", "title": "顺序",
     "description": "依次执行多个分支：1 → 2 → 3。可用「+ 出口 / - 出口」动态增减出口端口(按槽位顺序执行)。",
     "inputs": [_exec_in()],
     "outputs": [_exec_out("1", "第 1 个执行分支"),
                 _exec_out("2", "第 2 个执行分支"),
                 _exec_out("3", "第 3 个执行分支")],
     "properties": []},

    # ===== 常量 =====
    {"type": "const/image", "category": "数据", "title": "模板图片",
     "description": "提供一张模板图片。通过「📁 上传图片 / 📋 粘贴图片」选图并命名，节点上回显，文件名可点击复制 / ✎ 重命名。",
     "script": "image(name)",
     "inputs": [], "outputs": [_p("picture", T.PICTURE, "*", desc="模板图片，连到找图/等待的 template")],
     "properties": [_pr("name", "image", "", "图片文件名（images/ 下，由上传/粘贴写入）"), _note()], "widget": "image"},
    {"type": "const/text", "category": "数据", "title": "文本常量",
     "description": "提供一个固定文本值。",
     "inputs": [], "outputs": [_p("text", T.TEXT, "*", desc="文本值")],
     "properties": [_pr("value", "string", "", "文本内容"), _note()]},
    {"type": "const/number", "category": "数据", "title": "数值常量",
     "description": "提供一个固定数值。",
     "inputs": [], "outputs": [_p("number", T.NUMBER, "*", desc="数值")],
     "properties": [_pr("value", "number", 0, "数值内容"), _note()]},
    {"type": "const/bool", "category": "数据", "title": "布尔常量",
     "description": "提供一个固定布尔值（true/false）。",
     "inputs": [], "outputs": [_p("bool", T.BOOL, "*", desc="布尔值")],
     "properties": [_pr("value", "bool", False, "布尔内容（开=true）"), _note()]},
    {"type": "const/point", "category": "数据", "title": "坐标常量",
     "description": "提供一个固定坐标点，直接供动作使用。接了 x/y 输入则用输入值，否则用属性默认值。",
     "inputs": [_p("x", T.NUMBER, "1", desc="X 坐标（可选，接了用输入值）"),
                _p("y", T.NUMBER, "1", desc="Y 坐标（可选，接了用输入值）")],
     "outputs": [_p("point", T.POINT, "*", desc="点坐标，供动作 target 使用")],
     "properties": [_pr("x", "int", 0, "X 坐标默认值"),
                    _pr("y", "int", 0, "Y 坐标默认值"), _note()]},

    # ===== 变量（value 连接点类型可自定义，前端随 type 属性切换）=====
    {"type": "var/set", "category": "数据", "title": "设变量",
     "description": "把每个已连动态端口的值写入同名变量——一次可设多个。「+ 变量」起名加端口（端口名=变量名），「- 变量」选删。",
     "script": "set_var(name, value)",
     "inputs": [_exec_in()], "outputs": [_exec_out()],
     "properties": [_pr("type", "enum", _VAR_TYPES[0], "新增变量端口的默认类型", options=_VAR_TYPES)]},
    {"type": "var/get", "category": "数据", "title": "取变量",
     "description": "按 name 取变量值输出。type 可切换输出类型（切换后断开不兼容旧连线）；变量名需与「设变量」端口名一致。",
     "script": "get_var(name, default=None)",
     "inputs": [], "outputs": [_p("value", _VAR_TYPES[0], "*", desc="变量值（类型随 type 属性切换）")],
     "properties": [_pr("name", "string", "v", "变量名（与「设变量」端口名一致）"),
                    _pr("type", "enum", _VAR_TYPES[0], "输出值类型", options=_VAR_TYPES)]},

    # ===== 脚本/日志 =====
    {"type": "script/python", "category": "脚本", "title": "Python 脚本",
     "description": "在节点内多行编辑器写 Python（语法高亮 + jedi 补全 + 语法检查）。已注入默认设备与等价各组件的"
                    "内置函数，详见下方「注入对象」与「内置函数」。",
     "functions": _SCRIPT_FUNCS,
     "injects": _SCRIPT_INJECTS,
     "inputs": [_exec_in()],
     "outputs": [_exec_out()],
     "properties": [_pr("code", "code",
                        "# m = find_image('btn.png')\n# if m:\n#     click(to_point(m))\n",
                        "Python 代码（节点内编辑器）")],
     "widget": "code"},
    {"type": "util/log", "category": "脚本", "title": "日志",
     "description": "把连入的值打印到运行日志。",
     "script": "log(value, label='')",
     "inputs": [_exec_in(), _p("value", T.ANY, "1", desc="要打印的值（任意类型）")],
     "outputs": [_exec_out()],
     "properties": [_pr("label", "string", "", "日志前缀标签")]},
    {"type": "util/alert", "category": "脚本", "title": "提示",
     "description": "运行到此弹出非阻塞 toast。接了 text 优先用它，否则用 message。",
     "script": "alert(message, level='info')",
     "inputs": [_exec_in(), _p("text", T.TEXT, "1", desc="提示内容（优先于 message 属性）")],
     "outputs": [_exec_out()],
     "properties": [_pr("message", "string", "", "默认提示文案（未接 text 时用）"),
                    _pr("level", "enum", "info", "提示级别",
                        options=["info", "warn", "error"])]},
]


def node_catalog() -> dict:
    return {"types": T.TYPE_COLORS, "nodes": _NODES}