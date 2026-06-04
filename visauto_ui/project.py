"""工程 bundle 读写：工程目录/ = script.py + images/ + project.json。"""
from __future__ import annotations

import json
import os

SCRIPT_NAME = "script.py"
IMAGES_DIR = "images"
META_NAME = "project.json"


class Project:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)

    @property
    def script_path(self) -> str:
        return os.path.join(self.path, SCRIPT_NAME)

    @property
    def images_dir(self) -> str:
        return os.path.join(self.path, IMAGES_DIR)

    @property
    def meta_path(self) -> str:
        return os.path.join(self.path, META_NAME)

    # ---- 创建/打开 ----
    def ensure(self) -> None:
        os.makedirs(self.images_dir, exist_ok=True)

    def load_script(self) -> str:
        if os.path.exists(self.script_path):
            with open(self.script_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def save_script(self, text: str) -> None:
        self.ensure()
        with open(self.script_path, "w", encoding="utf-8") as f:
            f.write(text)

    def load_meta(self) -> dict:
        if os.path.exists(self.meta_path):
            try:
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_meta(self, meta: dict) -> None:
        self.ensure()
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def image_path(self, name: str) -> str:
        return os.path.join(self.images_dir, name)
