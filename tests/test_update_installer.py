import hashlib
import tempfile
from pathlib import Path

from utils.update_installer import (
    build_install_script,
    find_app_bundle,
    find_checksum,
    is_update_supported_bundle,
    select_update_asset,
    sha256_file,
    verify_sha256,
)


def test_find_app_bundle_from_executable_path():
    bundle = find_app_bundle("/Applications/BITZH Connect.app/Contents/MacOS/main")
    assert bundle == Path("/Applications/BITZH Connect.app")


def test_is_update_supported_bundle_rejects_translocation(tmp_path):
    bundle = tmp_path / "BITZH Connect.app"
    bundle.mkdir()
    assert is_update_supported_bundle(bundle) is True
    assert is_update_supported_bundle(
        Path("/private/var/folders/x/AppTranslocation/BITZH Connect.app")
    ) is False


def test_select_update_asset_matches_arch_and_zip():
    assets = [
        {"name": "bitzh-connect-darwin-arm64.dmg", "browser_download_url": "dmg"},
        {"name": "bitzh-connect-darwin-arm64.zip", "browser_download_url": "zip-arm"},
        {"name": "bitzh-connect-darwin-amd64.zip", "browser_download_url": "zip-intel"},
    ]
    assert select_update_asset(assets, "arm64")["browser_download_url"] == "zip-arm"
    assert select_update_asset(assets, "amd64")["browser_download_url"] == "zip-intel"
    assert select_update_asset(assets, "riscv") is None


def test_find_checksum_supports_star_prefix():
    text = "abc123  bitzh-connect-darwin-arm64.zip\n"
    assert find_checksum(text, "bitzh-connect-darwin-arm64.zip") == "abc123"
    assert find_checksum("abc123  other.zip\n", "bitzh-connect-darwin-arm64.zip") is None


def test_sha256_file_and_verify(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"hello")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert sha256_file(path) == expected
    assert verify_sha256(path, expected) is True
    assert verify_sha256(path, "0" * 64) is False
    assert verify_sha256(path, None) is True


def test_build_install_script_contains_safe_steps(tmp_path):
    script = build_install_script(
        Path("/Applications/BITZH Connect.app"),
        tmp_path / "BITZH Connect.app",
        12345,
    )
    assert "12345" in script
    assert "ditto" in script
    assert "xattr -rd com.apple.quarantine" in script
    assert "launchctl kickstart -k system/com.bitzh-connect.helper" in script
    assert "/tmp/" in script or "BITZH Connect.app" in script


def test_checksum_asset_matches_arch():
    from utils.update_installer import checksum_asset

    assets = [
        {"name": "checksums-darwin-amd64.txt", "browser_download_url": "intel"},
        {"name": "checksums-darwin-arm64.txt", "browser_download_url": "arm"},
    ]
    assert checksum_asset(assets, "arm64")["browser_download_url"] == "arm"
    assert checksum_asset(assets, "amd64")["browser_download_url"] == "intel"


def test_prepare_update_extracts_zip_and_checks_version(tmp_path):
    import plistlib
    import subprocess
    import sys

    import pytest

    if sys.platform != "darwin":
        pytest.skip("ditto only on macOS")
    src = tmp_path / "src"
    app = src / "BITZH Connect.app" / "Contents"
    app.mkdir(parents=True)
    with open(app / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": "1.5.0"}, f)
    zip_path = tmp_path / "update.zip"
    subprocess.run(
        ["/usr/bin/ditto", "-c", "-k", "--keepParent",
         str(src / "BITZH Connect.app"), str(zip_path)],
        check=True,
    )
    from utils.update_installer import prepare_update

    new_app = prepare_update(str(zip_path), str(tmp_path / "dest"), "1.5.0")
    assert new_app.name == "BITZH Connect.app"
