"""找图引擎单测（纯合成图，无需屏幕）。"""
import numpy as np

from visauto.finder import find_changes, match_all, match_template
from tests.fakes import make_patch


def _canvas(w=400, h=300):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_match_template_locates_patch():
    canvas = _canvas()
    patch = make_patch(40, 30, color=(0, 180, 0))
    canvas[50:80, 100:140] = patch
    m = match_template(canvas, patch, similarity=0.8)
    assert m is not None
    assert abs(m.x - 100) <= 1 and abs(m.y - 50) <= 1
    assert m.score > 0.95


def test_match_template_miss_returns_none():
    canvas = _canvas()
    patch = make_patch(40, 30, color=(0, 180, 0))
    # 画布里没有该图案
    assert match_template(canvas, patch, similarity=0.9) is None


def test_match_all_finds_multiple_with_nms():
    canvas = _canvas()
    patch = make_patch(30, 30, color=(200, 0, 0))
    positions = [(20, 20), (200, 20), (120, 150)]
    for x, y in positions:
        canvas[y:y + 30, x:x + 30] = patch
    matches = match_all(canvas, patch, similarity=0.85)
    assert len(matches) == 3
    found = sorted((m.x, m.y) for m in matches)
    assert found == sorted(positions)


def test_find_changes_detects_region():
    before = _canvas()
    after = before.copy()
    after[100:150, 200:260] = (255, 255, 255)
    changes = find_changes(before, after, min_area=50)
    assert len(changes) >= 1
    c = max(changes, key=lambda r: r.w * r.h)
    assert 190 <= c.x <= 205
    assert 90 <= c.y <= 105


def test_find_changes_none_when_identical():
    before = _canvas()
    assert find_changes(before, before.copy(), min_area=50) == []
