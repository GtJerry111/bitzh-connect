"""应用内更新的纯工具：资产选择、校验、解压、安装脚本生成。

不导入 Qt；便于单测，也避免与 services.update_service 循环依赖。
"""
from __future__ import annotations

import hashlib
import os
import plistlib
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from privileged_helper.protocol import (
    HELPER_DIR,
    HELPER_BIN,
    KERNEL_BIN,
    LAUNCHD_LABEL,
)

APP_BUNDLE_NAME = "BITZH Connect.app"
DOWNLOAD_LOG = "/tmp/bitzh-update.log"


def current_arch() -> str | None:
    machine = platform.machine().lower()
    return {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "amd64",
        "amd64": "amd64",
    }.get(machine)


def select_update_asset(assets, arch: str | None = None) -> dict | None:
    """从 release assets 里选当前架构的 ZIP；找不到返回 None。"""
    arch = arch or current_arch()
    if not arch:
        return None
    for asset in assets or ():
        name = str(asset.get("name", "")).lower()
        if name.endswith(".zip") and "darwin" in name and arch in name:
            return asset
    return None


def checksum_asset(assets, arch: str | None = None) -> dict | None:
    arch = arch or current_arch()
    wanted = f"checksums-darwin-{arch}.txt" if arch else ""
    for asset in assets or ():
        if str(asset.get("name", "")) == wanted:
            return asset
    for asset in assets or ():
        name = str(asset.get("name", ""))
        if name.startswith("checksums-darwin-") and name.endswith(".txt"):
            return asset
    return None


def find_checksum(text: str, asset_name: str) -> str | None:
    """解析 `sha256  filename` / `sha256 *filename`。"""
    wanted = os.path.basename(asset_name)
    for line in (text or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        if os.path.basename(name.lstrip("*")) == wanted:
            return digest.lower()
    return None


def sha256_file(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: str | os.PathLike, expected: str | None) -> bool:
    if not expected:
        return True
    return sha256_file(path) == expected.lower()


def find_app_bundle(path: str | os.PathLike | None) -> Path | None:
    if not path:
        return None
    candidate = Path(path).resolve()
    for parent in (candidate, *candidate.parents):
        if parent.suffix == ".app":
            return parent
    return None


def app_bundle_path() -> Path | None:
    """打包运行时的 .app 路径；源码运行返回 None。"""
    if "__compiled__" not in globals():
        return None
    return find_app_bundle(sys.argv[0])


def is_update_supported_bundle(bundle: Path | None) -> bool:
    if bundle is None or not bundle.is_dir():
        return False
    if "AppTranslocation" in str(bundle):
        return False
    return bundle.name == APP_BUNDLE_NAME


def extract_zip(zip_path: str | os.PathLike, dest_dir: str | os.PathLike) -> Path | None:
    os.makedirs(dest_dir, exist_ok=True)
    subprocess.run(
        ["/usr/bin/ditto", "-x", "-k", str(zip_path), str(dest_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    direct = Path(dest_dir) / APP_BUNDLE_NAME
    if direct.is_dir():
        return direct
    for candidate in Path(dest_dir).rglob("*.app"):
        if candidate.is_dir():
            return candidate
    return None


def read_bundle_version(bundle: Path) -> str | None:
    try:
        with open(bundle / "Contents" / "Info.plist", "rb") as f:
            data = plistlib.load(f)
        return str(data.get("CFBundleShortVersionString") or "") or None
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def prepare_update(zip_path: str, dest_dir: str, expected_version: str) -> Path:
    app = extract_zip(zip_path, dest_dir)
    if app is None:
        raise RuntimeError("下载包中没有找到 BITZH Connect.app")
    actual = read_bundle_version(app)
    if actual and actual != expected_version:
        raise RuntimeError(f"下载包版本不匹配：期望 {expected_version}，实际 {actual}")
    return app


def build_install_script(app_bundle: Path, new_app: Path, pid: int,
                         uid: int | None = None) -> str:
    q = shlex.quote
    uid = os.getuid() if uid is None else int(uid)
    return f"""#!/bin/sh
set -u
APP={q(str(app_bundle))}
NEW={q(str(new_app))}
BACKUP="$APP.bak.$$"
PID={int(pid)}
USER_ID={uid}
while kill -0 "$PID" 2>/dev/null; do
  sleep 0.2
done
rm -rf "$BACKUP"
mv "$APP" "$BACKUP"
if /usr/bin/ditto "$NEW" "$APP"; then
  /usr/bin/xattr -rd com.apple.quarantine "$APP" 2>/dev/null || true
  if [ -d {q(HELPER_DIR)} ]; then
    /bin/cp -f "$APP/Contents/MacOS/bitzh-helper" {q(HELPER_BIN)} 2>/dev/null || true
    /bin/cp -f "$APP/Contents/MacOS/app/core/zju-connect" {q(KERNEL_BIN)} 2>/dev/null || true
    /bin/chmod 755 {q(HELPER_BIN)} {q(KERNEL_BIN)} 2>/dev/null || true
    /usr/bin/xattr -rd com.apple.quarantine {q(HELPER_DIR)} 2>/dev/null || true
    /bin/launchctl kickstart -k system/{LAUNCHD_LABEL} 2>/dev/null || true
  fi
  rm -rf "$BACKUP"
  rm -rf "$(dirname "$NEW")"
  /bin/launchctl asuser "$USER_ID" /usr/bin/open "$APP" 2>/dev/null || /usr/bin/open "$APP"
else
  rm -rf "$APP"
  mv "$BACKUP" "$APP"
  /bin/launchctl asuser "$USER_ID" /usr/bin/open "$APP" 2>/dev/null || /usr/bin/open "$APP"
  exit 1
fi
"""


def launch_installer(script_path: str, pid: int | None = None) -> bool:
    """通过 osascript 以管理员权限后台执行安装脚本。

    `do shell script "... &"` 会立即返回；脚本自己在后台等待 App 退出后替换。
    """
    # 不能使用 nohup：osascript 提权执行时没有控制终端，macOS 的 nohup 会报
    # "can't detach from console" 并直接失败（与 TUN launcher 踩过的坑相同）。
    # 后台 + 重定向已足够；脚本自己等待 App 退出后替换。
    command = (
        f"/bin/sh {shlex.quote(script_path)} "
        f">{shlex.quote(DOWNLOAD_LOG)} 2>&1 &"
    )
    applescript = f'do shell script "{command}" with administrator privileges'
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            timeout=180,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def write_install_script(app_bundle: Path, new_app: Path, pid: int,
                         uid: int | None = None) -> str:
    fd, path = tempfile.mkstemp(prefix="bitzh-update-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(build_install_script(app_bundle, new_app, pid, uid))
    os.chmod(path, 0o700)
    return path


def cleanup_dir(path: str | None):
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)
