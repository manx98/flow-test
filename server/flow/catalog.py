"""节点目录：节点类型规格的单一真源（前端建 LiteGraph 面板、后端引擎据此校验）。

每个节点：type/category/title + inputs/outputs(端口) + properties(可配项)。
端口：{name, type, cardinality('*'|'1'|'n'), required(bool), kind('exec'|'data')}。
"""
from __future__ import annotations

from . import types as T


def _p(name, ptype, card="1", required=False):
    return {"name": name, "type": ptype, "cardinality": card,
            "required": required, "kind": "exec" if ptype == T.EXEC else "data"}


def _exec_in(name="in"):
    return _p(name, T.EXEC, "1", True)


def _exec_out(name="out"):
    return _p(name, T.EXEC, "1", False)


# ---- 节点定义 ----
_NODES = [
    # ===== 设备 =====
    {"type": "device/local", "category": "设备", "title": "本地设备",
     "inputs": [_exec_in(), _p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "outputs": [_exec_out(), _p("video", T.VIDEO, "*")],
     "properties": [{"name": "monitor", "type": "int", "default": 1}]},
    {"type": "device/novnc", "category": "设备", "title": "noVNC 设备",
     "inputs": [_exec_in(), _p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "outputs": [_exec_out(), _p("video", T.VIDEO, "*")],
     "properties": [{"name": "url", "type": "string", "default": "ws://127.0.0.1:6080/websockify"},
                    {"name": "password", "type": "password", "default": ""}]},
    {"type": "device/rdp", "category": "设备", "title": "RDP/xrdp 设备",
     "inputs": [_exec_in(), _p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "outputs": [_exec_out(), _p("video", T.VIDEO, "*")],
     "properties": [{"name": "host", "type": "string", "default": "127.0.0.1"},
                    {"name": "port", "type": "int", "default": 3389},
                    {"name": "username", "type": "string", "default": ""},
                    {"name": "password", "type": "password", "default": ""},
                    {"name": "domain", "type": "string", "default": ""},
                    {"name": "auth", "type": "enum", "options": ["auto", "tls", "nla"], "default": "auto"},
                    {"name": "width", "type": "int", "default": 1280},
                    {"name": "height", "type": "int", "default": 800}]},
    {"type": "device/pve", "category": "设备", "title": "PVE 设备",
     "inputs": [_exec_in(), _p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "outputs": [_exec_out(), _p("video", T.VIDEO, "*")],
     "properties": [{"name": "host", "type": "string", "default": "127.0.0.1"},
                    {"name": "port", "type": "int", "default": 8006},
                    {"name": "node", "type": "string", "default": "pve"},
                    {"name": "vmid", "type": "int", "default": 100},
                    {"name": "vmtype", "type": "enum", "options": ["qemu", "lxc"], "default": "qemu"},
                    {"name": "username", "type": "string", "default": "root@pam"},
                    {"name": "password", "type": "password", "default": ""},
                    {"name": "verify_tls", "type": "bool", "default": False}]},
    {"type": "device/vmware", "category": "设备", "title": "VMware 设备",
     "inputs": [_exec_in(), _p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "outputs": [_exec_out(), _p("video", T.VIDEO, "*")],
     "properties": [{"name": "host", "type": "string", "default": "127.0.0.1"},
                    {"name": "port", "type": "int", "default": 443},
                    {"name": "username", "type": "string", "default": ""},
                    {"name": "password", "type": "password", "default": ""},
                    {"name": "vm", "type": "string", "default": ""},
                    {"name": "verify_tls", "type": "bool", "default": False}]},

    # ===== 交互/显示 =====
    {"type": "io/interaction", "category": "交互", "title": "人机交互",
     "inputs": [_p("video", T.VIDEO, "1")],
     "outputs": [_p("mouse", T.MOUSE, "*"), _p("keyboard", T.KEYBOARD, "*")],
     "properties": [], "widget": "video"},

    # ===== 采集 =====
    {"type": "vision/screenshot", "category": "视觉", "title": "视频截图",
     "inputs": [_p("video", T.VIDEO, "1", True)],
     "outputs": [_p("picture", T.PICTURE, "*")],
     "properties": [{"name": "crop", "type": "rect", "default": None}], "widget": "capture"},

    # ===== 查找 =====
    {"type": "vision/find_image", "category": "视觉", "title": "找图",
     "inputs": [_exec_in(), _p("video", T.VIDEO, "1", True), _p("template", T.PICTURE, "1")],
     "outputs": [_exec_out("found"), _exec_out("notFound"),
                 _p("match", T.MATCH, "*"), _p("ok", T.BOOL)],
     "properties": [{"name": "similarity", "type": "number", "default": 0.7},
                    {"name": "timeout", "type": "number", "default": 0}]},
    {"type": "vision/find_text", "category": "视觉", "title": "找文字(OCR)",
     "inputs": [_exec_in(), _p("video", T.VIDEO, "1", True), _p("text", T.TEXT, "1")],
     "outputs": [_exec_out("found"), _exec_out("notFound"),
                 _p("match", T.MATCH, "*"), _p("ok", T.BOOL)],
     "properties": [{"name": "regex", "type": "bool", "default": False},
                    {"name": "timeout", "type": "number", "default": 0}]},
    {"type": "vision/find_all", "category": "视觉", "title": "找全部",
     "inputs": [_exec_in(), _p("video", T.VIDEO, "1", True), _p("template", T.PICTURE, "1")],
     "outputs": [_exec_out(), _p("matches", T.MATCH, "*"), _p("count", T.NUMBER)],
     "properties": [{"name": "similarity", "type": "number", "default": 0.7}]},

    # ===== 动作 =====
    {"type": "action/click", "category": "动作", "title": "点击",
     "inputs": [_exec_in(), _p("target", T.MATCH, "1")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*")],
     "properties": [{"name": "button", "type": "enum", "options": ["left", "right", "middle"], "default": "left"},
                    {"name": "double", "type": "bool", "default": False}]},
    {"type": "action/type", "category": "动作", "title": "输入文本",
     "inputs": [_exec_in(), _p("text", T.TEXT, "1")],
     "outputs": [_exec_out(), _p("keyboard", T.KEYBOARD, "*")],
     "properties": [{"name": "paste", "type": "bool", "default": False}]},
    {"type": "action/scroll", "category": "动作", "title": "滚动",
     "inputs": [_exec_in(), _p("target", T.MATCH, "1")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*")],
     "properties": [{"name": "dy", "type": "int", "default": -1}]},
    {"type": "action/drag", "category": "动作", "title": "拖拽",
     "inputs": [_exec_in(), _p("src", T.MATCH, "1"), _p("dst", T.MATCH, "1")],
     "outputs": [_exec_out(), _p("mouse", T.MOUSE, "*")], "properties": []},

    # ===== 等待 =====
    {"type": "wait/appear", "category": "等待", "title": "等出现",
     "inputs": [_exec_in(), _p("video", T.VIDEO, "1"), _p("template", T.PICTURE, "1")],
     "outputs": [_exec_out(), _exec_out("timeout"), _p("match", T.MATCH)],
     "properties": [{"name": "timeout", "type": "number", "default": 10}]},
    {"type": "wait/vanish", "category": "等待", "title": "等消失",
     "inputs": [_exec_in(), _p("video", T.VIDEO, "1"), _p("template", T.PICTURE, "1")],
     "outputs": [_exec_out(), _exec_out("timeout")],
     "properties": [{"name": "timeout", "type": "number", "default": 10}]},
    {"type": "wait/delay", "category": "等待", "title": "延时",
     "inputs": [_exec_in()], "outputs": [_exec_out()],
     "properties": [{"name": "seconds", "type": "number", "default": 1.0}]},

    # ===== 断言/结果 =====
    {"type": "assert/check", "category": "测试", "title": "断言",
     "inputs": [_exec_in(), _p("cond", T.BOOL, "1", True)],
     "outputs": [_exec_out("pass"), _exec_out("fail")],
     "properties": [{"name": "message", "type": "string", "default": ""}]},
    {"type": "test/result", "category": "测试", "title": "测试结果",
     "inputs": [_exec_in()], "outputs": [], "properties": []},

    # ===== 控制流 =====
    {"type": "flow/start", "category": "控制流", "title": "开始",
     "inputs": [], "outputs": [_exec_out()], "properties": []},
    {"type": "flow/if", "category": "控制流", "title": "条件分支",
     "inputs": [_exec_in(), _p("cond", T.BOOL, "1", True)],
     "outputs": [_exec_out("true"), _exec_out("false")], "properties": []},
    {"type": "flow/loop", "category": "控制流", "title": "循环",
     "inputs": [_exec_in(), _p("count", T.NUMBER, "1")],
     "outputs": [_exec_out("body"), _exec_out("done")], "properties": []},
    {"type": "flow/sequence", "category": "控制流", "title": "顺序",
     "inputs": [_exec_in()], "outputs": [_exec_out("1"), _exec_out("2"), _exec_out("3")],
     "properties": []},

    # ===== 常量 =====
    {"type": "const/image", "category": "数据", "title": "模板图片",
     "inputs": [], "outputs": [_p("picture", T.PICTURE, "*")],
     "properties": [{"name": "name", "type": "image", "default": ""}], "widget": "image"},
    {"type": "const/text", "category": "数据", "title": "文本常量",
     "inputs": [], "outputs": [_p("text", T.TEXT, "*")],
     "properties": [{"name": "value", "type": "string", "default": ""}]},
    {"type": "const/number", "category": "数据", "title": "数值常量",
     "inputs": [], "outputs": [_p("number", T.NUMBER, "*")],
     "properties": [{"name": "value", "type": "number", "default": 0}]},

    # ===== 变量 =====
    {"type": "var/set", "category": "数据", "title": "设变量",
     "inputs": [_exec_in(), _p("value", T.ANY, "1")], "outputs": [_exec_out()],
     "properties": [{"name": "name", "type": "string", "default": "v"}]},
    {"type": "var/get", "category": "数据", "title": "取变量",
     "inputs": [], "outputs": [_p("value", T.ANY, "*")],
     "properties": [{"name": "name", "type": "string", "default": "v"}]},

    # ===== 聚合/脚本/日志 =====
    {"type": "bundle/pack", "category": "聚合", "title": "打包",
     "inputs": [_p("a", T.ANY, "1"), _p("b", T.ANY, "1"), _p("c", T.ANY, "1")],
     "outputs": [_p("bundle", T.BUNDLE, "*")], "properties": []},
    {"type": "bundle/unpack", "category": "聚合", "title": "拆包",
     "inputs": [_p("bundle", T.BUNDLE, "1")],
     "outputs": [_p("a", T.ANY, "*"), _p("b", T.ANY, "*"), _p("c", T.ANY, "*")],
     "properties": []},
    {"type": "script/python", "category": "脚本", "title": "Python 脚本",
     "inputs": [_exec_in(), _p("bundle", T.BUNDLE, "1")],
     "outputs": [_exec_out(), _p("bundle", T.BUNDLE, "*")],
     "properties": [{"name": "code", "type": "code", "default": "# out['x'] = dev.find(...)\n"}],
     "widget": "code"},
    {"type": "util/log", "category": "脚本", "title": "日志",
     "inputs": [_exec_in(), _p("value", T.ANY, "1")], "outputs": [_exec_out()],
     "properties": [{"name": "label", "type": "string", "default": ""}]},
    {"type": "util/alert", "category": "脚本", "title": "提示",
     "inputs": [_exec_in(), _p("text", T.TEXT, "1")], "outputs": [_exec_out()],
     "properties": [{"name": "message", "type": "string", "default": ""},
                    {"name": "level", "type": "enum",
                     "options": ["info", "warn", "error"], "default": "info"}]},
]


def node_catalog() -> dict:
    return {"types": T.TYPE_COLORS, "nodes": _NODES}
