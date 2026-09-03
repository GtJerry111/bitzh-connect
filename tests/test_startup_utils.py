"""B6：macOS 登录项检测 + Windows 注册表值名（APP_NAME 换皮）+ Linux XDG autostart。"""
import sys
import types

import pytest

import utils.startup_utils as su


def test_darwin_get_launch_at_login_derives_bundle_name(monkeypatch):
    """打包后 argv[0] 形如 <App>.app/Contents/MacOS/<二进制名>，
    二进制名 ≠ 登录项名，必须先从路径推导出 .app 再取 basename。"""
    monkeypatch.setattr(
        su.sys,
        "argv",
        ["/Applications/BITZH Connect.app/Contents/MacOS/bitzh-connect-bin"],
    )

    class FakeResult:
        stdout = "BITZH Connect, Some Other App"

    monkeypatch.setattr(
        su.subprocess, "run", lambda *args, **kwargs: FakeResult()
    )

    assert su.get_launch_at_login() is True


class _FakeRegKey:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def windows_env(monkeypatch):
    """在非 Windows 平台伪造 winreg + system()，验证注册表值名。"""
    store = {}
    calls = {"set": [], "delete": [], "query": []}
    fake = types.SimpleNamespace()
    fake.HKEY_CURRENT_USER = "HKCU"
    fake.KEY_SET_VALUE = 1
    fake.KEY_READ = 2
    fake.REG_SZ = 1
    fake.OpenKey = lambda root, path, reserved, access: _FakeRegKey(store)

    def set_value_ex(key, name, reserved, type_, value):
        calls["set"].append(name)
        store[name] = value

    def delete_value(key, name):
        calls["delete"].append(name)
        store.pop(name, None)

    def query_value_ex(key, name):
        calls["query"].append(name)
        return (store[name], 1)

    fake.SetValueEx = set_value_ex
    fake.DeleteValue = delete_value
    fake.QueryValueEx = query_value_ex

    monkeypatch.setattr(su, "system", lambda: "Windows")
    monkeypatch.setattr(su, "winreg", fake, raising=False)
    return calls


def test_windows_set_launch_at_login_uses_app_name(windows_env):
    from common.constants import APP_NAME

    su.set_launch_at_login(True)
    assert windows_env["set"] == [APP_NAME]


def test_windows_get_launch_at_login_uses_app_name(windows_env):
    from common.constants import APP_NAME

    su.set_launch_at_login(True)  # 先写入，保证查询路径无异常（macOS 无 WindowsError 内建）
    assert su.get_launch_at_login() is True
    assert windows_env["query"] == [APP_NAME]


# ---- Linux：XDG autostart ----


@pytest.fixture
def linux_env(monkeypatch, tmp_path):
    """伪造 Linux 平台 + 隔离的 XDG_CONFIG_HOME。"""
    monkeypatch.setattr(su, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path


def test_linux_launch_at_login_roundtrip(linux_env):
    """XDG autostart：开启写 .desktop、查询为真、关闭删除文件"""
    desktop = linux_env / "autostart" / "bitzh-connect.desktop"
    assert su.get_launch_at_login() is False
    su.set_launch_at_login(True)
    assert desktop.exists()
    content = desktop.read_text()
    assert "[Desktop Entry]" in content and "Exec=" in content
    assert su.get_launch_at_login() is True
    su.set_launch_at_login(False)
    assert not desktop.exists()
    assert su.get_launch_at_login() is False


def test_linux_exec_line_dev_mode_uses_python(linux_env, monkeypatch):
    """开发态：Exec 带 python 解释器 + 脚本绝对路径（双 token，desktop 规范引号）"""
    monkeypatch.setattr(su.sys, "argv", ["app/main.py"])
    su.set_launch_at_login(True)
    content = (linux_env / "autostart" / "bitzh-connect.desktop").read_text()
    assert f'"{sys.executable}"' in content
    assert "main.py" in content


def test_linux_exec_line_packaged_uses_binary(linux_env, monkeypatch):
    """打包态（Nuitka __compiled__）：Exec 直接是二进制本体"""
    monkeypatch.setattr(su.sys, "argv", ["/usr/lib/bitzh-connect/bitzh-connect"])
    monkeypatch.setattr(su, "__compiled__", None, raising=False)  # 存在即打包态
    su.set_launch_at_login(True)
    content = (linux_env / "autostart" / "bitzh-connect.desktop").read_text()
    assert 'Exec="/usr/lib/bitzh-connect/bitzh-connect"' in content
