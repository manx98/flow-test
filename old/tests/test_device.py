"""Device/Region/Match 与重试语义单测（用 FakeBackend，无需真屏）。"""
import threading
import time

import numpy as np
import pytest

from visauto.device import Device
from visauto.exceptions import FindFailed, OcrNotConfigured
from visauto.image import Image
from visauto.pattern import Pattern
from visauto.settings import Settings
from tests.fakes import FakeBackend, make_patch


@pytest.fixture(autouse=True)
def fast_scan():
    old = Settings.wait_scan_rate
    Settings.wait_scan_rate = 50.0
    yield
    Settings.wait_scan_rate = old


def _dev_with_patch(at=(100, 60)):
    be = FakeBackend(400, 300)
    patch = make_patch(40, 30, color=(0, 180, 0))
    be.paste_patch(patch, *at)
    dev = Device(be).connect()
    return dev, be, patch


def test_find_returns_match_at_absolute_coords():
    dev, be, patch = _dev_with_patch(at=(100, 60))
    m = dev.find(Pattern(patch, similarity=0.85), timeout=0)
    assert abs(m.x - 100) <= 1 and abs(m.y - 60) <= 1
    assert m.center.x == m.x + m.w // 2


def test_find_raises_when_absent():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    patch = make_patch(40, 30, color=(0, 180, 0))
    with pytest.raises(FindFailed):
        dev.find(Pattern(patch, similarity=0.9), timeout=0.2)


def test_exists_returns_none_when_absent():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    patch = make_patch(40, 30, color=(0, 180, 0))
    assert dev.exists(Pattern(patch, similarity=0.9), timeout=0.1) is None


def test_click_moves_to_match_center():
    dev, be, patch = _dev_with_patch(at=(100, 60))
    p = dev.click(Pattern(patch, similarity=0.85))
    assert be.last_move() == (p.x, p.y)
    # 命中中心约在 (120, 75)
    assert abs(p.x - 120) <= 2 and abs(p.y - 75) <= 2
    kinds = [e[0] for e in be.events]
    assert "press" in kinds and "release" in kinds


def test_wait_then_appear():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    patch = make_patch(40, 30, color=(0, 180, 0))

    def appear_later():
        time.sleep(0.15)
        be.paste_patch(patch, 50, 50)

    threading.Thread(target=appear_later, daemon=True).start()
    m = dev.wait(Pattern(patch, similarity=0.85), timeout=2.0)
    assert abs(m.x - 50) <= 1 and abs(m.y - 50) <= 1


def test_wait_vanish():
    dev, be, patch = _dev_with_patch(at=(100, 60))
    # 先确认在
    assert dev.exists(Pattern(patch, similarity=0.85), timeout=0) is not None

    def clear():
        time.sleep(0.15)
        from visauto.geometry import Rect
        be.fill_rect(Rect(0, 0, 400, 300), color=(0, 0, 0))

    threading.Thread(target=clear, daemon=True).start()
    assert dev.wait_vanish(Pattern(patch, similarity=0.85), timeout=2.0) is True


def test_find_all_multiple():
    be = FakeBackend(400, 300)
    patch = make_patch(30, 30, color=(200, 0, 0))
    for x, y in [(20, 20), (200, 20), (120, 150)]:
        be.paste_patch(patch, x, y)
    dev = Device(be).connect()
    matches = dev.find_all(Pattern(patch, similarity=0.85))
    assert len(matches) == 3


def test_region_subsearch_offsets_coords():
    be = FakeBackend(400, 300)
    patch = make_patch(30, 30, color=(0, 0, 200))
    be.paste_patch(patch, 250, 200)
    dev = Device(be).connect()
    sub = dev.region(200, 150, 200, 150)
    m = sub.find(Pattern(patch, similarity=0.85), timeout=0)
    assert abs(m.x - 250) <= 1 and abs(m.y - 200) <= 1


def test_text_without_ocr_raises():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    with pytest.raises(OcrNotConfigured):
        dev.find(text="提交", timeout=0)


def test_type_and_paste_recorded():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    dev.type("hello")
    assert ("type", "hello") in be.events
    dev.paste("剪贴板内容")
    assert be.clipboard == "剪贴板内容"


def test_last_seen_optimization_hits():
    dev, be, patch = _dev_with_patch(at=(100, 60))
    img = Image(patch)
    pat = Pattern(img, similarity=0.85)
    m1 = dev.find(pat)
    assert img.last_seen is not None
    # 第二次应仍命中（走 last-seen 小窗口校验路径）
    m2 = dev.find(pat)
    assert (m1.x, m1.y) == (m2.x, m2.y)
