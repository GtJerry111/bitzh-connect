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
