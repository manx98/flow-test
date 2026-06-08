"""实时路由：WebRTC offer/answer 信令 + 设备会话开关 + 运行状态 WS。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .devices import sessions
from .webrtc import handle_offer

router = APIRouter()


class ConnectBody(BaseModel):
    kind: str
    config: dict = {}
    project: str | None = None
    node_id: int | None = None


class OfferBody(BaseModel):
    session_id: str
    sdp: str
    type: str


@router.post("/api/devices/connect")
async def connect_device(body: ConnectBody):
    """连接一个设备会话（阻塞连接放线程池），返回 session_id 与屏幕尺寸。

    带 project+node_id 时按节点登记，运行流程时可复用此 live-view 连接，避免重复连。
    """
    loop = asyncio.get_event_loop()
    try:
        sess = await loop.run_in_executor(
            None, sessions.create, body.kind, body.config, body.project, body.node_id)
    except Exception as e:
        raise HTTPException(400, f"连接失败：{e}")
    w, h = sess.screen_size()
    return {"session_id": sess.id, "width": w, "height": h}


@router.post("/api/devices/{sid}/disconnect")
async def disconnect_device(sid: str):
    sessions.close(sid)
    return {"ok": True}


def _reuse_provider(project: str):
    """运行时设备解析：优先复用该工程同节点的 live-view 连接，否则新连(运行结束后由引擎关闭)。"""
    from .flow.engine import _default_device_provider
    from .project import Project

    meta = Project(project).load_meta()
    timeouts = meta.get("timeouts") or {}

    def provider(device_node):
        sess = sessions.get_by_node(project, device_node["id"])
        if sess is not None:
            return sess.device         # 复用 live-view，不标记 owned（运行结束不关）
        if device_node.get("type") == "device/rdp":
            props = dict(device_node.get("properties") or {})
            props["connect_timeout"] = timeouts.get("rdp_connect_timeout", props.get("connect_timeout", 60))
            props["first_update_timeout"] = timeouts.get(
                "rdp_first_update_timeout", props.get("first_update_timeout", 30))
            device_node = {**device_node, "properties": props}
        return _default_device_provider(device_node)
    return provider


@router.post("/api/webrtc/offer")
async def webrtc_offer(body: OfferBody):
    """浏览器 offer → 服务端 answer（视频轨 + DataChannel 输入）。"""
    sess = sessions.get(body.session_id)
    if sess is None:
        raise HTTPException(404, "设备会话不存在")
    answer = await handle_offer(sess, body.sdp, body.type)
    return answer


# 运行流程图 + 节点状态/报告推送 + 结果(报告/证据)落盘
@router.websocket("/ws/run/{name}")
async def ws_run(websocket: WebSocket, name: str):
    await websocket.accept()
    import datetime
    import json
    import os

    import cv2

    from .flow.runner import FlowRunner
    from .project import Project

    runner = FlowRunner(websocket.send_json)
    try:
        while True:
            msg = await websocket.receive_json()
            cmd = msg.get("cmd")
            if cmd == "run":
                proj = Project(name)
                if proj.exists:
                    proj.register_imagepath()   # 确保 images/ 在搜索路径（模板/截图按裸名解析）
                run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                run_dir = proj.run_dir(run_id) if proj.exists else None

                def evidence_sink(node_id, frame_bgr, _d=run_dir, _id=run_id):
                    if _d is None:
                        return None
                    fn = f"node{node_id}_{int(__import__('time').time()*1000)%100000}.png"
                    cv2.imwrite(os.path.join(_d, fn), frame_bgr)
                    return f"/api/projects/{name}/results/{_id}/{fn}"

                def on_finish(report, _d=run_dir, _id=run_id):
                    if _d is None:
                        return {"run_id": _id}
                    with open(os.path.join(_d, "report.json"), "w", encoding="utf-8") as f:
                        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
                    with open(os.path.join(_d, "report.junit.xml"), "w", encoding="utf-8") as f:
                        f.write(report.to_junit(f"flow:{name}"))
                    base = f"/api/projects/{name}/results/{_id}"
                    out = {
                        "run_id": _id,
                        "report_url": f"{base}/report.json",
                        "junit_url": f"{base}/report.junit.xml",
                    }
                    # PDF（reportlab 缺失或失败不影响其余）
                    try:
                        from .flow.pdf_report import build_pdf
                        build_pdf(report.to_dict(), os.path.join(_d, "report.pdf"),
                                  f"测试报告  {name} / {_id}", _d)
                        out["pdf_url"] = f"{base}/report.pdf"
                    except Exception as e:
                        print(f"[warn] PDF 生成失败：{e}")
                    return out

                runner.start(msg.get("graph") or {},
                             device_provider=_reuse_provider(name),
                             evidence_sink=evidence_sink, on_finish=on_finish)
            elif cmd == "stop":
                runner.stop()
    except WebSocketDisconnect:
        pass
    finally:
        await runner.close()
