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
