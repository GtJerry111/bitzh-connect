# tests/test_glass_style.py
"""面板玻璃质感设置：配置默认值/往返、对话框行、实时换肤守卫。"""
from platform import system

import pytest


def test_glass_style_default_clear(qtbot):
    from utils.config_utils import load_config

    assert load_config()["glass_style"] == "clear"


def test_glass_style_roundtrip(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["glass_style"] = "regular"
    save_config(config)
    assert load_config()["glass_style"] == "regular"


def test_segmented_switch_custom_segments(qtbot):
    from views.mode_switch import SegmentedModeSwitch

    sw = SegmentedModeSwitch(["清透", "标准"])
    qtbot.addWidget(sw)
    assert sw._segments == ["清透", "标准"]
    sw.setCurrentIndex(1)
    assert sw.currentIndex() == 1


def test_segmented_switch_default_segments_unchanged(qtbot):
    """默认构造保持 代理模式/TUN 模式（主窗口调用方不受影响）。"""
    from views.mode_switch import SegmentedModeSwitch

    sw = SegmentedModeSwitch()
    qtbot.addWidget(sw)
    assert sw._segments == ["代理模式", "TUN 模式"]


def test_set_glass_style_offscreen_noop(qtbot):
    """offscreen：面板无玻璃垫层，切换只更新属性、不抛异常。"""
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.set_glass_style("regular")
    assert w.glass_style == "regular"
    w.set_glass_style("clear")
    assert w.glass_style == "clear"
    # 脏值兜底：非 clear 一律按 regular 归一
    w.set_glass_style("garbage")
    assert w.glass_style == "regular"
    w.reconnect_manager.cancel()


@pytest.mark.skipif(system() != "Darwin", reason="面板玻璃行仅 macOS 显示")
def test_dialog_glass_row_roundtrip_darwin(qtbot):
    from views.advanced_panel import AdvancedSettingsDialog

    dialog = AdvancedSettingsDialog()
    qtbot.addWidget(dialog)
    dialog.glass_style_switch.setCurrentIndex(1)
    assert dialog.get_settings()["glass_style"] == "regular"
