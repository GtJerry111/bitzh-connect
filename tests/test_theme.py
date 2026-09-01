import re

import pytest

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_semantic_colors_all_valid_hex():
    from common import theme

    for name in ("idle", "working", "connected", "error",
                 "accent", "accent_pressed", "accent_text", "secondary_text"):
        assert HEX_RE.match(theme.semantic_color(name)), name


def test_is_dark_returns_bool():
    from common import theme

    assert theme.is_dark() in (True, False)


def test_card_background_valid_hex():
    from common import theme

    assert HEX_RE.match(theme.card_background())


def test_font_hierarchy():
    from common import theme

    assert theme.status_title_font().pointSize() >= 18
    assert theme.status_title_font().letterSpacing() < 100  # 负字距
    assert theme.card_value_font().pointSize() >= 14
    assert theme.card_title_font().pointSize() < theme.card_value_font().pointSize()


def test_reduce_motion_returns_bool():
    from utils.motion_utils import reduce_motion

    assert reduce_motion() in (True, False)


def test_animate_label_color_immediate_when_reduce_motion(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: True)
    label = QLabel("●")
    qtbot.addWidget(label)
    motion_utils.animate_label_color(label, "#28C840")
    assert "#28c840" in label.styleSheet().lower()
    assert label._theme_color == "#28C840"


def test_animated_height_toggle_immediate_when_reduce_motion(qtbot, monkeypatch):
    from PySide6.QtWidgets import QTextEdit

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: True)
    w = QTextEdit()
    qtbot.addWidget(w)
    motion_utils.animated_height_toggle(w, expanding=False)
    assert not w.isVisible()
    motion_utils.animated_height_toggle(w, expanding=True)
    assert w.isVisible()


def test_animate_label_color_interrupt_restarts_from_presentation_value(qtbot, monkeypatch):
    from PySide6.QtCore import QAbstractAnimation
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QLabel

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: False)
    label = QLabel("●")
    qtbot.addWidget(label)
    label.setStyleSheet("color: #000000;")
    label._theme_color = "#000000"

    anim1 = motion_utils.animate_label_color(label, "#FF9500", duration=500)
    qtbot.waitUntil(lambda: "#000000" not in label.styleSheet(), timeout=2000)
    assert anim1.state() == QAbstractAnimation.State.Running  # 确在动画进行中打断
    displayed = re.search(r"color:\s*(#[0-9A-Fa-f]{6})", label.styleSheet()).group(1)
    assert displayed.lower() not in ("#000000", "#ff9500")  # 展示色确为中间态

    anim2 = motion_utils.animate_label_color(label, "#16AE68", duration=500)
    # 新动画起点 = 打断时刻的展示色，不回跳到逻辑初值
    assert QColor(anim2.startValue()) == QColor(displayed)

    qtbot.waitUntil(lambda: label._theme_color == "#16AE68", timeout=2000)
    assert "#16ae68" in label.styleSheet().lower()


def test_animate_label_color_recall_after_completion_no_crash(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: False)
    label = QLabel("●")
    qtbot.addWidget(label)
    label._theme_color = "#000000"

    motion_utils.animate_label_color(label, "#FF9500", duration=10)
    qtbot.wait(200)  # 越过动画终点，让事件循环处理 DeleteWhenStopped 的删除
    # 上一次动画已自然完成、C++ 对象已删除；再次调用不得对已删除对象 stop()
    motion_utils.animate_label_color(label, "#16AE68", duration=10)
    qtbot.wait(200)
    assert label._theme_color == "#16AE68"


def test_animated_height_toggle_expand_interrupts_collapse_stays_visible(qtbot, monkeypatch):
    from PySide6.QtWidgets import QTextEdit

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: False)
    w = QTextEdit()
    qtbot.addWidget(w)
    w.show()
    motion_utils.animated_height_toggle(w, expanding=True, duration=10)
    qtbot.wait(100)  # 等完全展开

    motion_utils.animated_height_toggle(w, expanding=False, duration=200)
    qtbot.wait(80)  # 收起进行中
    motion_utils.animated_height_toggle(w, expanding=True, duration=200)  # 打断
    qtbot.wait(300)  # 等展开动画结束

    assert w.isVisible()  # 被停的收起动画不得把 widget 隐藏
