"""把执行引擎(worker 线程)桥接到 async WebSocket：跑流程、推节点状态/报告，支持停止。"""
from __future__ import annotations

import asyncio
import threading

from .engine import Engine


class FlowRunner:
    def __init__(self, send_async):
        self._send = send_async                  # async fn(dict)
        self._loop = asyncio.get_event_loop()
        self._q: asyncio.Queue = asyncio.Queue()
        self._consumer = self._loop.create_task(self._drain())
        self._thread: threading.Thread | None = None
        self._abort: threading.Event | None = None

    async def _drain(self):
        try:
            while True:
                ev = await self._q.get()
                await self._send(ev)
        except asyncio.CancelledError:
            pass

    def _emit(self, ev: dict):
        # 从引擎线程安全投递
        self._loop.call_soon_threadsafe(self._q.put_nowait, ev)

    def start(self, graph: dict, device_provider=None, evidence_sink=None, on_finish=None, lang: str = "zh"):
        if self._thread and self._thread.is_alive():
            return
        self._abort = threading.Event()

        def work():
            def on_state(nid, status, info):
                self._emit({"type": "node", "id": nid, "status": status, "info": info})
            self._emit({"type": "run", "status": "start"})
            try:
                report = Engine(graph, lang=lang).run(
                    on_state=on_state, abort_event=self._abort,
                    device_provider=device_provider, evidence_sink=evidence_sink,
                    on_event=self._emit)
                extra = on_finish(report) if on_finish else {}
                self._emit({"type": "run", "status": "done",
                            "report": report.to_dict(), **(extra or {})})
            except Exception as e:  # 引擎外层兜底
                self._emit({"type": "run", "status": "error", "error": str(e)})

        self._thread = threading.Thread(target=work, daemon=True, name="flow-run")
        self._thread.start()

    def stop(self):
        if self._abort:
            self._abort.set()

    async def close(self):
        self.stop()
        self._consumer.cancel()
