"""WebRTC：把 Device 视频经 aiortc 推给浏览器；DataChannel 收浏览器鼠标键盘。"""
from __future__ import annotations

import asyncio
import json
import time

import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame

from .devices import DeviceSession
from .input import dispatch_input

# 活跃的 PeerConnection（用于关闭清理）
_pcs: set[RTCPeerConnection] = set()


class DeviceVideoTrack(VideoStreamTrack):
    """从 visauto Device 持续取帧的视频轨。"""

    def __init__(self, session: DeviceSession, fps: float = 15.0):
        super().__init__()
        self._session = session
        self._min_interval = 1.0 / max(1.0, fps)
        self._last = 0.0

    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        # 限帧：避免 mss/解码过快空转
        dt = time.monotonic() - self._last
        if dt < self._min_interval:
            await asyncio.sleep(self._min_interval - dt)
        self._last = time.monotonic()

        loop = asyncio.get_event_loop()
        try:
            frame_bgr = await loop.run_in_executor(None, self._session.device.capture)
        except Exception:
            frame_bgr = None
        if frame_bgr is None or frame_bgr.size == 0:
            w, h = self._session.screen_size()
            frame_bgr = np.zeros((h, w, 3), dtype=np.uint8)

        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])  # BGR→RGB
        vf = VideoFrame.from_ndarray(rgb, format="rgb24")
        vf.pts = pts
        vf.time_base = time_base
        return vf


async def handle_offer(session: DeviceSession, sdp: str, sdp_type: str) -> dict:
    """处理浏览器 offer：加视频轨 + DataChannel(输入)，返回 answer。"""
    pc = RTCPeerConnection()
    _pcs.add(pc)

    @pc.on("connectionstatechange")
    async def _on_state():
        if pc.connectionState in ("failed", "closed"):
            await _discard(pc)

    # 服务端创建的 DataChannel 也行；这里同时接受浏览器创建的通道。
    @pc.on("datachannel")
    def _on_dc(channel):
        @channel.on("message")
        def _on_msg(message):
            try:
                evt = json.loads(message)
            except Exception:
                return
            dispatch_input(session, evt)

    pc.addTrack(DeviceVideoTrack(session))

    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    # 非 trickle：等 ICE 收集完，answer 里带齐 candidate（localhost/LAN 足够）
    await _wait_ice(pc)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


async def _wait_ice(pc: RTCPeerConnection, timeout: float = 5.0):
    if pc.iceGatheringState == "complete":
        return
    fut = asyncio.get_event_loop().create_future()

    @pc.on("icegatheringstatechange")
    def _check():
        if pc.iceGatheringState == "complete" and not fut.done():
            fut.set_result(None)

    try:
        await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        pass


async def _discard(pc: RTCPeerConnection):
    _pcs.discard(pc)
    try:
        await pc.close()
    except Exception:
        pass


async def close_all_pcs():
    for pc in list(_pcs):
        await _discard(pc)
