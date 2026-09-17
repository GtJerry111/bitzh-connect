from platform import system

import pytest


def test_menu_bar_mode_default_false(qtbot):
    from utils.config_utils import load_config

    assert load_config()["menu_bar_mode"] is False


def test_menu_bar_mode_roundtrip(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)
    assert load_config()["menu_bar_mode"] is True


def test_menu_bar_mode_loaded_to_window(qtbot):
    from utils.config_utils import load_config, save_config

    config = load_config()
    config["menu_bar_mode"] = True
    save_config(config)

    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    assert w.menu_bar_mode is True
    w.reconnect_manager.cancel()
