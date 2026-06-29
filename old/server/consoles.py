"""VMware / Proxmox(PVE) 控制台接入。

两者的图形控制台本质都是 RFB(VNC) over WebSocket：
- PVE：调 Proxmox API 登录取认证票据 → /vncproxy 取 VNC 票据+端口 → 连 vncwebsocket。
- VMware：用 pyVmomi 登录 → vm.AcquireTicket("webmks") → 连 WebMKS 的 wss。
取到 ws 地址与票据后，统一用现有 visauto noVNC 后端(RFB over WS)连接。
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

import visauto

from .i18n import tr


# ===================== Proxmox VE =====================
def _pve_api(base, path, data=None, *, cookie=None, csrf=None, verify=True, lang: str = "zh"):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(
        base + path, data=body, method="POST" if data is not None else "GET")
    if cookie:
        req.add_header("Cookie", cookie)
    if csrf:
        req.add_header("CSRFPreventionToken", csrf)
    ctx = None if verify else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            return json.load(r)["data"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(tr(lang, "device.pve_api_failed", "PVE API {path} 失败：{code} {reason}",
                              path=path, code=e.code, reason=e.reason)) from e


def connect_pve(cfg: dict):
    lang = cfg.get("__lang", "zh")
    host = cfg.get("host", "127.0.0.1")
    port = int(cfg.get("port", 8006))
    node = cfg.get("node", "")
    vmid = int(cfg.get("vmid", 0))
    vmtype = cfg.get("vmtype", "qemu")           # qemu | lxc
    username = cfg.get("username", "")            # 形如 root@pam
    password = cfg.get("password") or ""
    verify = bool(cfg.get("verify_tls", False))
    if not (node and vmid):
        raise ValueError(tr(lang, "device.pve_missing_node_vmid", "PVE 设备需要 node 与 vmid"))
    base = f"https://{host}:{port}"

    # 1) 登录取认证票据 + CSRF
    auth = _pve_api(base, "/api2/json/access/ticket",
                    {"username": username, "password": password}, verify=verify, lang=lang)
    cookie = "PVEAuthCookie=" + auth["ticket"]
    csrf = auth["CSRFPreventionToken"]

    # 2) 取 VNC 代理票据与端口
    vnc = _pve_api(base, f"/api2/json/nodes/{node}/{vmtype}/{vmid}/vncproxy",
                   {"websocket": 1}, cookie=cookie, csrf=csrf, verify=verify, lang=lang)
    vncticket, vport = vnc["ticket"], vnc["port"]

    # 3) 连 vncwebsocket（RFB over WS，VNC 密码=vncticket，带认证 Cookie）
    ws = (f"wss://{host}:{port}/api2/json/nodes/{node}/{vmtype}/{vmid}/vncwebsocket"
          f"?port={vport}&vncticket={urllib.parse.quote(vncticket)}")
    kw = {"cookie": cookie}
    if not verify:
        kw["sslopt"] = {"cert_reqs": ssl.CERT_NONE}
    return visauto.connect_novnc(ws, password=vncticket, **kw)


# ===================== VMware (WebMKS) =====================
def connect_vmware(cfg: dict):
    lang = cfg.get("__lang", "zh")
    try:
        from pyVim.connect import Disconnect, SmartConnect
        from pyVmomi import vim
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(tr(lang, "device.vmware_needs_pyvmomi",
                              "VMware 设备需要 pyVmomi：pip install pyvmomi")) from e

    host = cfg.get("host", "")
    port = int(cfg.get("port", 443))
    username = cfg.get("username", "")
    password = cfg.get("password") or ""
    vmref = cfg.get("vm", "")                      # VM 名称或 MoID
    verify = bool(cfg.get("verify_tls", False))
    if not (host and vmref):
        raise ValueError(tr(lang, "device.vmware_missing_host_vm", "VMware 设备需要 host 与 vm"))

    ctx = None if verify else ssl._create_unverified_context()
    si = SmartConnect(host=host, user=username, pwd=password, port=port, sslContext=ctx)
    try:
        vm = _find_vm(si.RetrieveContent(), vmref, vim)
        if vm is None:
            raise ValueError(tr(lang, "device.vmware_vm_not_found", "找不到虚拟机：{vm}", vm=vmref))
        t = vm.AcquireTicket("webmks")            # WebMKS 票据（一次性）
        ws = f"wss://{t.host}:{t.port}/ticket/{t.ticket}"
        kw = {"subprotocols": ("binary",)}        # WebMKS：RFB over WS，无密码(票据已在 URL)
        if not verify:
            kw["sslopt"] = {"cert_reqs": ssl.CERT_NONE}
        return visauto.connect_novnc(ws, password=None, **kw)
    finally:
        try:
            Disconnect(si)                        # 票据已用于建连，控制连接可断开
        except Exception:
            pass


def _find_vm(content, ref, vim):
    view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True)
    try:
        for vm in view.view:
            if vm._moId == ref or vm.name == ref:
                return vm
    finally:
        view.Destroy()
    return None
