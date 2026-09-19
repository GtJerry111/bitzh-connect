# tests/test_macos_sf_symbols.py
"""SF Symbols 桥接：offscreen/非 macOS 一律 None（调用方回退自绘），不触碰 AppKit。"""
import pytest


def test_unknown_kind_returns_none(qtbot):
    from utils.macos_sf_symbols import sf_symbol_pixmap

    assert sf_symbol_pixmap("not_a_kind", 15, "#000000") is None


def test_offscreen_returns_none(qtbot):
    """offscreen 平台（非 cocoa）守卫：不桥接，返回 None。"""
    from utils.macos_sf_symbols import sf_symbol_pixmap

    assert sf_symbol_pixmap("gear", 15, "#000000") is None


def test_non_darwin_returns_none(qtbot, monkeypatch):
    from utils import macos_sf_symbols

    monkeypatch.setattr(macos_sf_symbols, "system", lambda: "Linux")
    _CACHE = macos_sf_symbols._CACHE.clear()
    assert macos_sf_symbols.sf_symbol_pixmap("gear", 15, "#000000") is None


def test_symbol_names_cover_panel_icons():
    """面板用到的语义名都在映射表里（防改名漂移）。"""
    from utils.macos_sf_symbols import SF_NAMES

    for kind in ("gear", "power", "swap", "grid", "window", "chevron_right"):
        assert kind in SF_NAMES
