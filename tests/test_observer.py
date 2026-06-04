"""观察者单测（FakeBackend 驱动）。"""
import threading
import time

import pytest

from visauto.device import Device
from visauto.observer import EventType
from visauto.settings import Settings
from tests.fakes import FakeBackend, make_patch


@pytest.fixture(autouse=True)
def fast_observe():
    old = Settings.observe_scan_rate
    Settings.observe_scan_rate = 50.0
    yield
    Settings.observe_scan_rate = old


def test_on_appear_fires_once_on_transition():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()
    patch = make_patch(40, 30, color=(0, 180, 0))
    from visauto.pattern import Pattern

    fired = []
    dev.on_appear(Pattern(patch, similarity=0.85),
                  lambda e: fired.append(e))

    th = dev.observe(timeout=1.0, background=True)

    time.sleep(0.1)
    be.paste_patch(patch, 80, 80)   # 触发出现
    time.sleep(0.3)
    dev.stop_observe()
    if th:
        th.join(timeout=1.0)

    assert len(fired) == 1
    assert fired[0].type is EventType.APPEAR
    assert fired[0].match is not None


def test_on_change_fires_on_diff():
    be = FakeBackend(400, 300)
    dev = Device(be).connect()

    fired = []
    dev.on_change(lambda e: fired.append(e), min_area=50)

    th = dev.observe(timeout=1.0, background=True)
    time.sleep(0.1)
    from visauto.geometry import Rect
    be.fill_rect(Rect(100, 100, 80, 60), color=(255, 255, 255))
    time.sleep(0.3)
    dev.stop_observe()
    if th:
        th.join(timeout=1.0)

    assert len(fired) >= 1
    assert fired[0].type is EventType.CHANGE
    assert len(fired[0].changes) >= 1


def test_on_vanish_fires():
    be = FakeBackend(400, 300)
    patch = make_patch(40, 30, color=(0, 180, 0))
    be.paste_patch(patch, 80, 80)
    dev = Device(be).connect()
    from visauto.pattern import Pattern
    from visauto.geometry import Rect

    fired = []
    dev.on_vanish(Pattern(patch, similarity=0.85),
                  lambda e: fired.append(e))

    th = dev.observe(timeout=1.5, background=True)
    time.sleep(0.2)               # 先观察到“在”
    be.fill_rect(Rect(0, 0, 400, 300), color=(0, 0, 0))  # 消失
    time.sleep(0.3)
    dev.stop_observe()
    if th:
        th.join(timeout=1.0)

    assert len(fired) == 1
    assert fired[0].type is EventType.VANISH
