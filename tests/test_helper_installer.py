import os

from utils import helper_installer as hi


def test_can_install_false_without_bundled_helper(monkeypatch):
    """无 app bundle 内 helper（源码/测试环境）→ 不可安装，走回退。"""
    monkeypatch.setattr(hi, "is_supported", lambda: True)
    monkeypatch.setattr(hi, "bundled_helper_path", lambda: "/nonexistent/bitzh-helper")
    monkeypatch.setattr(hi, "bundled_kernel_path", lambda: "/nonexistent/zju-connect")
    assert hi.can_install() is False


def test_can_install_true_with_sources(monkeypatch, tmp_path):
    helper = tmp_path / "bitzh-helper"
    kernel = tmp_path / "zju-connect"
    helper.write_text("x")
    kernel.write_text("x")
    monkeypatch.setattr(hi, "is_supported", lambda: True)
    monkeypatch.setattr(hi, "bundled_helper_path", lambda: str(helper))
    monkeypatch.setattr(hi, "bundled_kernel_path", lambda: str(kernel))
    assert hi.can_install() is True


def test_is_usable_requires_installed_and_version(monkeypatch):
    monkeypatch.setattr(hi, "is_installed", lambda: True)
    monkeypatch.setattr(hi, "installed_version", lambda: hi.PROTOCOL_VERSION)
    assert hi.is_usable() is True
    monkeypatch.setattr(hi, "installed_version", lambda: 999)
    assert hi.is_usable() is False


def test_build_install_script_contains_key_operations(monkeypatch, tmp_path):
    helper = tmp_path / "bitzh-helper"
    kernel = tmp_path / "zju-connect"
    helper.write_text("x")
    kernel.write_text("x")
    monkeypatch.setattr(hi, "bundled_helper_path", lambda: str(helper))
    monkeypatch.setattr(hi, "bundled_kernel_path", lambda: str(kernel))
    script = hi.build_install_script(allowed_uid=501)
    assert "mkdir -p" in script and hi.HELPER_DIR in script
    assert hi.HELPER_BIN in script and hi.KERNEL_BIN in script
    assert "xattr -rd com.apple.quarantine" in script      # 自动清 quarantine
    assert hi.LAUNCHD_PLIST in script
    assert "launchctl bootstrap system" in script
    assert "--allowed-uid" in script and "501" in script
    assert script.startswith("#!/bin/sh")


def test_build_uninstall_script_contains_key_operations():
    script = hi.build_uninstall_script()
    assert "launchctl bootout" in script
    assert hi.LAUNCHD_PLIST in script
    assert hi.HELPER_DIR in script
    assert "rm -rf" in script
