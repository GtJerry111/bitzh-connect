"""特权 helper 的安装/卸载/状态检测（仅 macOS）。

安装/卸载都需要一次管理员授权（osascript）；复用 tun_utils 的异步提权任务，
结果回主线程回调，避免授权框停留期间冻结 GUI。
"""
import os
import shlex
import sys
import tempfile
from platform import system

from privileged_helper.protocol import (
    HELPER_BIN,
    HELPER_DIR,
    KERNEL_BIN,
    LAUNCHD_LABEL,
    LAUNCHD_PLIST,
    PROTOCOL_VERSION,
    SOCKET_PATH,
)
from . import helper_client
from .tun_utils import spawn_elevated_async


def is_supported() -> bool:
    return system() == "Darwin"


def _base_path() -> str:
    """可执行所在目录（打包后为 app bundle 的 Contents/MacOS）。"""
    if "__compiled__" in globals():
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def bundled_helper_path() -> str:
    return os.path.join(_base_path(), "bitzh-helper")


def bundled_kernel_path() -> str:
    if system() == "Windows":
        return os.path.join(_base_path(), "app", "core", "zju-connect.exe")
    return os.path.join(_base_path(), "app", "core", "zju-connect")


def _app_bundle_path():
    base = _base_path()
    suffix = "/Contents/MacOS"
    if base.endswith(suffix):
        return base[: -len(suffix)]
    return None


def can_install() -> bool:
    """本机是否具备安装条件：macOS + bundle 内有 helper 与内核。"""
    return (
        is_supported()
        and os.path.exists(bundled_helper_path())
        and os.path.exists(bundled_kernel_path())
    )


def is_installed() -> bool:
    return os.path.exists(HELPER_BIN) and os.path.exists(LAUNCHD_PLIST)


def installed_version():
    """握手取已装 helper 的协议版本；不可用返回 None。"""
    return helper_client.helper_version()


def is_usable() -> bool:
    return is_installed() and installed_version() == PROTOCOL_VERSION


def needs_update() -> bool:
    return is_installed() and installed_version() != PROTOCOL_VERSION


def _launchd_plist_xml(allowed_uid: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"  <key>Label</key><string>{LAUNCHD_LABEL}</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        f"    <string>{HELPER_BIN}</string>\n"
        "    <string>--allowed-uid</string>\n"
        f"    <string>{allowed_uid}</string>\n"
        "  </array>\n"
        "  <key>RunAtLoad</key><true/>\n"
        "  <key>KeepAlive</key><true/>\n"
        "</dict>\n"
        "</plist>\n"
    )


def build_install_script(allowed_uid: int) -> str:
    """生成安装脚本（由 root 执行）：复制 helper/内核、清 quarantine、装 LaunchDaemon。"""
    helper_src = shlex.quote(bundled_helper_path())
    kernel_src = shlex.quote(bundled_kernel_path())
    helper_dir = shlex.quote(HELPER_DIR)
    helper_bin = shlex.quote(HELPER_BIN)
    kernel_bin = shlex.quote(KERNEL_BIN)
    plist_path = shlex.quote(LAUNCHD_PLIST)
    socket_path = shlex.quote(SOCKET_PATH)
    bundle = _app_bundle_path()
    quarantine_targets = [HELPER_DIR]
    if bundle:
        quarantine_targets.append(bundle)
    xattr_lines = "\n".join(
        f"xattr -rd com.apple.quarantine {shlex.quote(t)} 2>/dev/null || true"
        for t in quarantine_targets
    )
    plist_xml = _launchd_plist_xml(allowed_uid)
    return (
        "#!/bin/sh\n"
        "set -e\n"
        f"mkdir -p {helper_dir}\n"
        f"cp -f {helper_src} {helper_bin}\n"
        f"cp -f {kernel_src} {kernel_bin}\n"
        f"chmod 755 {helper_bin} {kernel_bin}\n"
        f"chown -R root:wheel {helper_dir}\n"
        f"{xattr_lines}\n"
        f"cat > {plist_path} <<'BITZH_PLIST'\n"
        f"{plist_xml}"
        "BITZH_PLIST\n"
        f"chown root:wheel {plist_path}\n"
        f"chmod 644 {plist_path}\n"
        f"rm -f {socket_path} 2>/dev/null || true\n"
        f"launchctl bootout system {plist_path} 2>/dev/null || true\n"
        f"launchctl bootstrap system {plist_path}\n"
        # bootstrap 返回 0 只代表 launchd 已受理，不等于 helper 已监听 socket。
        # 轮询等待 socket 就绪（最多 ~10s），使成功回调发生时 helper 已可用，
        # 避免紧接的重连因 is_usable() 为 False 再弹一次安装引导。
        "i=0\n"
        "while [ $i -lt 40 ]; do\n"
        f"  [ -S {socket_path} ] && break\n"
        "  sleep 0.25\n"
        "  i=$((i + 1))\n"
        "done\n"
    )


def build_uninstall_script() -> str:
    """生成卸载脚本（由 root 执行）：停服务、删 plist、删安装目录、删 socket。"""
    plist_path = shlex.quote(LAUNCHD_PLIST)
    helper_dir = shlex.quote(HELPER_DIR)
    socket_path = shlex.quote(SOCKET_PATH)
    return (
        "#!/bin/sh\n"
        f"launchctl bootout system {plist_path} 2>/dev/null || true\n"
        f"rm -f {plist_path}\n"
        f"rm -rf {helper_dir}\n"
        f"rm -f {socket_path} 2>/dev/null || true\n"
        "exit 0\n"
    )


def _run_script_async(script: str, on_done):
    """把脚本写到临时文件并以管理员权限异步执行；完成后删除脚本。"""
    fd, path = tempfile.mkstemp(prefix="bitzh-helper-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(script)
    os.chmod(path, 0o700)

    def _done(ok: bool):
        try:
            os.unlink(path)
        except OSError:
            pass
        if on_done:
            on_done(bool(ok))

    return spawn_elevated_async(path, _done)


def install_async(on_done):
    """异步安装（弹一次管理员授权）。on_done(ok: bool) 在主线程回调。"""
    return _run_script_async(build_install_script(os.getuid()), on_done)


def uninstall_async(on_done):
    """异步卸载（弹一次管理员授权）。"""
    return _run_script_async(build_uninstall_script(), on_done)
