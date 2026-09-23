"""SettingRow：左标签（+说明）+ 右控件的可复用设置行。"""


def test_setting_row_exposes_label_and_control(qtbot):
    from views.settings_row import SettingRow
    from views.toggle_switch import ToggleSwitch

    switch = ToggleSwitch()
    row = SettingRow("测试项", switch, "说明文字")
    qtbot.addWidget(row)
    assert row.label_text() == "测试项"
    assert row.control is switch
