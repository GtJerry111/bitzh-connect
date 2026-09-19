"""reduce-motion 各平台探测（不碰真实系统设置，全走 mock）。"""

import utils.motion_utils as mu


def test_linux_reduce_motion_follows_gsettings(monkeypatch):
    """Ubuntu(GNOME)：enable-animations=false 即减少动态效果"""
    monkeypatch.setattr(mu, "system", lambda: "Linux")

    class R:
        def __init__(self, out):
            self.stdout = out

    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: R("false\n")
    )
    assert mu.reduce_motion() is True

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R("true\n"))
    assert mu.reduce_motion() is False


def test_linux_reduce_motion_degrades_when_no_gsettings(monkeypatch):
    """无 gsettings 的桌面（命令缺失/超时）→ False（播放动画，与现状一致）"""
    monkeypatch.setattr(mu, "system", lambda: "Linux")

    import subprocess

    def _boom(*a, **k):
        raise FileNotFoundError("gsettings missing")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert mu.reduce_motion() is False


def test_animated_height_toggle_final_frame_reanchors(qtbot):
    """终态必须再调一次 on_frame（maxHeight 释放后）：
    动画掉帧时最后一帧未必是终值，缺这一步宿主窗口会卡在中间尺寸
    （真实案例：菜单栏面板工具条被窗口底边裁掉一截）。"""
    from PySide6.QtWidgets import QWidget

    from utils.motion_utils import animated_height_toggle

    w = QWidget()
    qtbot.addWidget(w)
    w.show()
    calls = []
    animated_height_toggle(w, True, max_height=120, on_frame=lambda: calls.append(w.maximumHeight()))
    # 动画完成 = maximumHeight 释放回 QWIDGETSIZE_MAX
    qtbot.waitUntil(lambda: w.maximumHeight() == 16777215, timeout=2000)
    # 终态 on_frame 必须发生在 maxHeight 释放之后（最后一帧记录为 MAX）
    assert calls and calls[-1] == 16777215
