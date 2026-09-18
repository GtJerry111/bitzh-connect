from PySide6.QtCore import QSize

from views.toggle_switch import ToggleSwitch


def test_toggle_size_and_checkable(qtbot):
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    assert sw.isCheckable()
    assert sw.size() == QSize(38, 23)
    assert not sw.isChecked()


def test_toggle_click_toggles(qtbot):
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.click()
    assert sw.isChecked()
    sw.click()
    assert not sw.isChecked()


def test_knob_snaps_under_reduce_motion(qtbot, monkeypatch):
    monkeypatch.setattr("views.toggle_switch.reduce_motion", lambda: True)
    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.setChecked(True)
    assert sw._knob == 1.0
