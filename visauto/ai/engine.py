"""AIEngine：封装视觉大模型（OpenAI / Ollama，官方 openai SDK，惰性导入、单实例复用）。

让模型按描述在画面里定位一个目标，返回归一化坐标框。OpenAI 与 Ollama 都走
OpenAI 兼容的 chat.completions（含图片输入），仅 base_url/model/api_key 不同。
"""
from __future__ import annotations

import base64
import json
import re
from typing import TYPE_CHECKING

from ..exceptions import VisautoError

if TYPE_CHECKING:
    import numpy as np

# provider → 默认接口地址（base_url 留空时用）
_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}

# 严格 JSON 输出约定：found + 归一化框 [x,y,w,h]（左上角+宽高，0~1）+ confidence
_SYS = (
    "You are a precise UI element locator. You are given a screenshot and a target "
    "description. Return ONLY a compact JSON object, no prose, no code fences:\n"
    '{"found": true|false, "box": [x, y, w, h], "confidence": 0.0-1.0}\n'
    "box is the target bounding box in NORMALIZED coordinates relative to the image: "
    "x,y = top-left corner, w,h = width,height, each a float in [0,1]. "
    "If the target is not present, return found=false and box=[0,0,0,0]."
)


def build_prompt(kind: str, desc: str) -> str:
    """按查找类型生成用户提示词。kind: 'image'(视觉元素) | 'text'(文字)。"""
    if kind == "text":
        return (f"Locate the on-screen text that matches: \"{desc}\". "
                f"Return the tight bounding box around that text.")
    return (f"Locate the UI element / icon / image described as: \"{desc}\". "
            f"Return the tight bounding box around it.")


def _to_data_url(image_bgr: "np.ndarray", max_side: int = 1280) -> str:
    """BGR ndarray → PNG base64 data URL；长边超过 max_side 时等比缩小省 token。

    坐标用归一化，下采样不影响后续映射。
    """
    import cv2
    img = image_bgr
    h, w = img.shape[:2]
    scale = max_side / max(w, h)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise VisautoError("AI 引擎：图像编码失败")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class AIEngine:
    """视觉大模型定位引擎。

        AIEngine(provider="openai", model="gpt-4o", api_key="...")
        AIEngine(provider="ollama", model="llava")
    需 pip install openai。
    """

    def __init__(self, provider: str = "openai", base_url: str = "",
                 model: str = "gpt-4o", api_key: str = "", temperature: float = 0.0):
        self.provider = (provider or "openai").lower()
        self.model = model or "gpt-4o"
        self.temperature = float(temperature or 0.0)
        base = (base_url or "").strip() or _DEFAULT_BASE.get(self.provider, "")
        if not base:
            raise VisautoError("AI 引擎：custom 服务商需填写 base_url")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise VisautoError("AIEngine 需要 openai：pip install openai") from e
        # Ollama 不校验 key，但 SDK 要求非空，给个占位
        key = api_key or ("ollama" if self.provider == "ollama" else "")
        self._client = OpenAI(base_url=base, api_key=key or "none")

    def locate(self, image_bgr: "np.ndarray", prompt: str):
        """调用模型定位目标。返回 (found: bool, box: [x,y,w,h]|None 归一化, confidence: float)。"""
        data_url = _to_data_url(image_bgr)
        resp = self._client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        return _parse(content)


def _parse(content: str):
    """从模型文本里解析 JSON（容忍代码围栏/前后缀文字）。"""
    text = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return False, None, 0.0
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return False, None, 0.0
    if not obj.get("found"):
        return False, None, float(obj.get("confidence", 0.0) or 0.0)
    box = obj.get("box") or []
    if not (isinstance(box, (list, tuple)) and len(box) == 4):
        return False, None, 0.0
    x, y, w, h = (float(v) for v in box)
    if w <= 0 or h <= 0:
        return False, None, float(obj.get("confidence", 0.0) or 0.0)
    return True, [x, y, w, h], float(obj.get("confidence", 1.0) or 1.0)
