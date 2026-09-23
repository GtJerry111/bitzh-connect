"""SettingRow：左标签（+说明）+ 右控件的可复用设置行。"""


def test_setting_row_exposes_label_and_control(qtbot):
    from views.settings_row import SettingRow
    from views.toggle_switch import ToggleSwitch

    switch = ToggleSwitch()
    row = SettingRow("测试项", switch, "说明文字")
    qtbot.addWidget(row)
    assert row.label_text() == "测试项"
    assert row.control is switch


def test_setting_row_separator_only_between_rows(qtbot):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from views.settings_row import SettingRow
    from views.toggle_switch import ToggleSwitch

    host = QWidget()
    layout = QVBoxLayout(host)
    r1 = SettingRow("a", ToggleSwitch())
    r2 = SettingRow("b", ToggleSwitch())
    layout.addWidget(r1)
    layout.addWidget(r2)
    qtbot.addWidget(host)
    assert r1._has_following_row() is True
    assert r2._has_following_row() is False
