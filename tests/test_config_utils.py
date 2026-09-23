def test_menu_bar_speed_default_off(qtbot):
    from utils.config_utils import load_config

    assert load_config()["menu_bar_speed"] is False
