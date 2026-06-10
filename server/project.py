"""工程 bundle 读写（服务端）：工程目录 = flow.json + images/ + project.json。

与 visauto 的 ImagePath 对接：打开工程时把 images/ 加入图片搜索路径，
节点里图片用裸文件名即可解析。
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass

import visauto

# 工程根目录（所有工程放这里）。可用环境变量覆盖。
WORKSPACE = os.environ.get(
    "FLOW_WORKSPACE",
    os.path.join(os.path.expanduser("~"), ".flow-test", "projects"),
)
SETTINGS_PATH = os.environ.get(
    "FLOW_SETTINGS_PATH",
    os.path.join(os.path.expanduser("~"), ".flow-test", "settings.json"),
)

FLOW_NAME = "flow.json"
IMAGES_DIR = "images"
META_NAME = "project.json"
RESULTS_DIR = "results"
AI_SESSIONS_DIR = "ai_sessions"


def _safe_name(name: str) -> str:
    """工程名清洗，避免路径穿越。"""
    name = os.path.basename(name.strip())
    if not name or name in (".", ".."):
        raise ValueError("非法工程名")
    return name


@dataclass
class Project:
    name: str

    @property
    def path(self) -> str:
        return os.path.join(WORKSPACE, _safe_name(self.name))

    @property
    def flow_path(self) -> str:
        return os.path.join(self.path, FLOW_NAME)

    @property
    def images_dir(self) -> str:
        return os.path.join(self.path, IMAGES_DIR)

    @property
    def meta_path(self) -> str:
        return os.path.join(self.path, META_NAME)

    @property
    def exists(self) -> bool:
        return os.path.isdir(self.path)

    # ---- 创建/删除 ----
    def ensure(self) -> "Project":
        os.makedirs(self.images_dir, exist_ok=True)
        if not os.path.exists(self.flow_path):
            self.save_flow({"nodes": [], "links": []})
        if not os.path.exists(self.meta_path):
            self.save_meta({})
        return self

    def delete(self) -> None:
        if self.exists:
            shutil.rmtree(self.path)

    # ---- flow.json ----
    def load_flow(self) -> dict:
        if os.path.exists(self.flow_path):
            with open(self.flow_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"nodes": [], "links": []}

    def save_flow(self, graph: dict) -> None:
        os.makedirs(self.path, exist_ok=True)
        with open(self.flow_path, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)

    # ---- project.json ----
    def load_meta(self) -> dict:
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_meta(self, meta: dict) -> None:
        os.makedirs(self.path, exist_ok=True)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    # ---- 图片 ----
    def list_images(self) -> list[str]:
        if not os.path.isdir(self.images_dir):
            return []
        return sorted(
            n for n in os.listdir(self.images_dir)
            if n.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))
        )

    def image_path(self, name: str) -> str:
        return os.path.join(self.images_dir, _safe_name(name))

    def rename_image(self, old: str, new: str) -> str:
        """把 images/ 里的 old 重命名为 new（new 无扩展名则沿用 old 的）。返回最终文件名。"""
        src = self.image_path(old)
        if not os.path.exists(src):
            raise FileNotFoundError("原图片不存在")
        new = _safe_name(new)
        if not os.path.splitext(new)[1]:
            new += os.path.splitext(old)[1]
        dst = os.path.join(self.images_dir, new)
        if os.path.abspath(dst) != os.path.abspath(src) and os.path.exists(dst):
            raise FileExistsError("目标文件名已存在")
        os.rename(src, dst)
        return new

    # ---- 运行结果 ----
    @property
    def results_dir(self) -> str:
        return os.path.join(self.path, RESULTS_DIR)

    def run_dir(self, run_id: str) -> str:
        d = os.path.join(self.results_dir, _safe_name(run_id))
        os.makedirs(d, exist_ok=True)
        return d

    def list_runs(self) -> list[str]:
        if not os.path.isdir(self.results_dir):
            return []
        return sorted(
            (n for n in os.listdir(self.results_dir)
             if os.path.isdir(os.path.join(self.results_dir, n))),
            reverse=True,
        )

    def result_file(self, run_id: str, fname: str) -> str:
        return os.path.join(self.results_dir, _safe_name(run_id), _safe_name(fname))

    def delete_run(self, run_id: str) -> None:
        """删除单次运行记录目录。"""
        d = os.path.join(self.results_dir, _safe_name(run_id))
        if not os.path.isdir(d):
            raise FileNotFoundError("运行记录不存在")
        shutil.rmtree(d)

    def clear_runs(self) -> int:
        """清空所有运行记录，返回删除数量。"""
        if not os.path.isdir(self.results_dir):
            return 0
        n = 0
        for name in os.listdir(self.results_dir):
            d = os.path.join(self.results_dir, name)
            if os.path.isdir(d):
                shutil.rmtree(d)
                n += 1
        return n

    def register_imagepath(self) -> None:
        """把本工程 images/ 加入 visauto 图片搜索路径。"""
        os.makedirs(self.images_dir, exist_ok=True)
        visauto.ImagePath.add(self.images_dir)

    # ---- AI 辅助搭建会话 ----
    @property
    def ai_sessions_dir(self) -> str:
        return os.path.join(self.path, AI_SESSIONS_DIR)

    def ai_session_path(self, session_id: str) -> str:
        return os.path.join(self.ai_sessions_dir, _safe_name(session_id) + ".json")

    def list_ai_sessions(self) -> list[dict]:
        if not os.path.isdir(self.ai_sessions_dir):
            return []
        sessions = []
        for name in os.listdir(self.ai_sessions_dir):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.ai_sessions_dir, name), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            sessions.append({
                "id": data.get("id") or name[:-5],
                "title": data.get("title") or "",
                "created_at": data.get("created_at") or 0,
                "updated_at": data.get("updated_at") or 0,
            })
        return sorted(sessions, key=lambda x: x.get("updated_at") or 0, reverse=True)

    def create_ai_session(self, title: str = "") -> dict:
        now = time.time()
        sid = uuid.uuid4().hex[:12]
        session = {
            "id": sid,
            "title": title or "AI 会话",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "draft": None,
            "form_values": {},
        }
        self.save_ai_session(sid, session)
        return session

    def load_ai_session(self, session_id: str) -> dict:
        path = self.ai_session_path(session_id)
        if not os.path.exists(path):
            raise FileNotFoundError("AI 会话不存在")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def save_ai_session(self, session_id: str, session: dict) -> dict:
        os.makedirs(self.ai_sessions_dir, exist_ok=True)
        now = time.time()
        session = dict(session or {})
        session["id"] = _safe_name(session_id)
        session["updated_at"] = now
        session.setdefault("created_at", now)
        session.setdefault("title", "AI 会话")
        session.setdefault("messages", [])
        session.setdefault("draft", None)
        session.setdefault("form_values", {})
        with open(self.ai_session_path(session_id), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        return session

    def delete_ai_session(self, session_id: str) -> None:
        path = self.ai_session_path(session_id)
        if not os.path.exists(path):
            raise FileNotFoundError("AI 会话不存在")
        os.remove(path)

    def clear_ai_sessions(self) -> int:
        if not os.path.isdir(self.ai_sessions_dir):
            return 0
        n = 0
        for name in os.listdir(self.ai_sessions_dir):
            if name.endswith(".json"):
                os.remove(os.path.join(self.ai_sessions_dir, name))
                n += 1
        return n


def list_projects() -> list[str]:
    os.makedirs(WORKSPACE, exist_ok=True)
    return sorted(
        n for n in os.listdir(WORKSPACE)
        if os.path.isdir(os.path.join(WORKSPACE, n))
    )


def load_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
