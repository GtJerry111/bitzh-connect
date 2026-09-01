"""B6：macOS 登录项检测 + Windows 注册表值名（APP_NAME 换皮）。"""
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
