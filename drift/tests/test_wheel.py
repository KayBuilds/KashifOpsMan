import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from drift.config import Settings
from drift.modes import Mode
from drift.util import format_size
from drift.wheel import RadialWheel


@pytest.fixture(scope="module")
def wheel():
    app = QApplication.instance() or QApplication([])
    w = RadialWheel(Settings(wheel_diameter=340))
    yield w
    w.close()


def at(w, angle_cw_from_top, r):
    import math

    a = math.radians(angle_cw_from_top - 90)
    return QPointF(w.width() / 2 + r * math.cos(a), w.height() / 2 + r * math.sin(a))


def test_wedge_hit_testing(wheel):
    wheel.set_mode(Mode.CONVERT)  # 6 wedges, 60 degrees each, wedge 0 at top
    r = 140
    assert wheel._wedge_at(at(wheel, 0, r)) == 0
    assert wheel._wedge_at(at(wheel, 29, r)) == 0
    assert wheel._wedge_at(at(wheel, 31, r)) == 1
    assert wheel._wedge_at(at(wheel, 89, r)) == 1
    assert wheel._wedge_at(at(wheel, 91, r)) == 2
    assert wheel._wedge_at(at(wheel, 180, r)) == 3
    assert wheel._wedge_at(at(wheel, 335, r)) == 0
    assert wheel._wedge_at(at(wheel, 325, r)) == 5


def test_centre_and_outside_are_not_wedges(wheel):
    assert wheel._wedge_at(at(wheel, 45, 10)) is None
    assert wheel._wedge_at(at(wheel, 45, 175)) is None


def test_tools_mode_has_seven_wedges(wheel):
    wheel.set_mode(Mode.TOOLS)
    seen = {wheel._wedge_at(at(wheel, a, 140)) for a in range(0, 360, 5)}
    assert seen == set(range(7))
    wheel.set_mode(Mode.CONVERT)


def test_format_size():
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(5 * 1024 * 1024) == "5.0 MB"
