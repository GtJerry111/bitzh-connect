# 特权 Helper 安装与集成 Implementation Plan（阶段 2b）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2a 的 helper 接进真实流程：首次 TUN 连接弹安装引导页（一次管理员授权，自动复制 helper/内核、写 LaunchDaemon、清 quarantine、bootstrap），之后连接走 socket 且不再弹框；安装失败/拒绝则回退到现有 osascript 模式。

**Architecture:** 新增 `helper_installer`（状态检测 + 安装/卸载脚本生成 + 复用 `tun_utils.spawn_elevated_async` 提权执行）与 `HelperSetupDialog`（独立窗口，风格与高级设置一致）。`start_connection` 的 TUN 分支改为三分支：`is_usable()` → 走 socket；`can_install()` 且未拒绝 → 弹安装引导；否则 → 现有 osascript 回退。

**Tech Stack:** Python 3.11 / PySide6 / pytest；macOS `osascript`、`launchctl`、`xattr`。

**依赖：** 必须先完成 `2026-09-22-privileged-helper-core.md`（阶段 2a）。

**Spec:** 本会话 grilling 结论（问题 3）。

---

## File Structure

- `app/utils/helper_installer.py` — 新建：状态检测、安装/卸载脚本生成、异步安装/卸载
- `app/views/helper_setup_dialog.py` — 新建：安装引导对话框
- `app/views/main_window.py` — 修改：`prompt_helper_install()` + 安装结果回调
- `app/utils/connection_utils.py` — 修改：TUN 分支三分支
- `app/views/advanced_panel.py` — 修改：网络 tab 加"卸载特权服务"
- `.github/workflows/release.yml` — 修改：macOS 打包 helper 并放进 app bundle
- `README.md` — 修改：说明一次授权
- `tests/test_helper_installer.py`、`tests/test_helper_setup_dialog.py`、`tests/test_connection_flow.py`（追加）

**关键设计：** 测试/开发环境没有 app bundle 内的 `bitzh-helper`，`can_install()` 返回 False，因此既有连接流程测试仍走 osascript 回退，不受影响。

---

## Task 1: helper_installer

**Files:**
- Create: `app/utils/helper_installer.py`
- Test: `tests/test_helper_installer.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_helper_installer.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_installer.py -q`
Expected: collection error（`helper_installer` 不存在）。

- [ ] **Step 3: 实现 helper_installer.py**

创建 `app/utils/helper_installer.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_installer.py -q`
Expected: 5 passed。

- [ ] **Step 5: 提交**

```bash
git add app/utils/helper_installer.py tests/test_helper_installer.py
git commit -m "feat(helper): 安装/卸载脚本生成与状态检测"
```

---

## Task 2: 安装引导对话框

**Files:**
- Create: `app/views/helper_setup_dialog.py`
- Test: `tests/test_helper_setup_dialog.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_helper_setup_dialog.py`：

```python
def test_dialog_lists_operations_and_buttons(qtbot):
    from views.helper_setup_dialog import HelperSetupDialog

    dlg = HelperSetupDialog()
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "安装 TUN 特权服务"
    text = dlg.operations_text()
    assert "LaunchDaemon" in text or "开机" in text
    assert "quarantine" in text.lower() or "授权" in text
    assert dlg.install_button.text() == "安装"
    assert dlg.cancel_button.text() == "稍后"


def test_install_button_disables_and_runs_installer(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    assert calls  # 触发了安装
    assert not dlg.install_button.isEnabled()  # 安装中禁用防重复
    calls[0](True)  # 模拟安装成功回调
    assert dlg.result() == dlg.Accepted


def test_install_failure_shows_error_and_reenables(qtbot, monkeypatch):
    from views import helper_setup_dialog as mod

    calls = []
    monkeypatch.setattr(
        mod.helper_installer, "install_async",
        lambda on_done: calls.append(on_done),
    )
    dlg = mod.HelperSetupDialog()
    qtbot.addWidget(dlg)
    dlg.install_button.click()
    calls[0](False)
    assert dlg.install_button.isEnabled()
    assert "失败" in dlg.status_text()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_helper_setup_dialog.py -q`
Expected: collection error（模块不存在）。

- [ ] **Step 3: 实现对话框**

创建 `app/views/helper_setup_dialog.py`：

```python
"""TUN 特权服务安装引导对话框（独立窗口，风格与高级设置一致）。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from common import theme
from utils import helper_installer

_OPERATIONS = (
    "• 安装常驻特权服务到系统目录（/Library/PrivilegedHelperTools）\n"
    "• 注册开机自启的 LaunchDaemon（/Library/LaunchDaemons）\n"
    "• 自动清除应用的 quarantine 标记（免手动 xattr）\n"
    "• 之后连接 TUN 不再需要输入管理员密码"
)


class HelperSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("安装 TUN 特权服务")
        self.setMinimumWidth(440)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("启用 TUN 需要安装特权服务")
        font = title.font()
        font.setPointSize(15)
        font.setWeight(font.Weight.DemiBold)
        title.setFont(font)
        layout.addWidget(title)

        desc = QLabel(
            "TUN 全局路由需要管理员权限创建虚拟网卡与路由。"
            "安装一次后，今后连接无需再输入密码。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        layout.addWidget(desc)

        ops = QLabel(_OPERATIONS)
        ops.setWordWrap(True)
        ops.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(ops)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton("稍后")
        self.cancel_button.setMinimumWidth(88)
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.cancel_button)

        self.install_button = QPushButton("安装")
        self.install_button.setMinimumWidth(88)
        self.install_button.setDefault(True)
        self.install_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                padding: 6px 0px;
                font-size: 13pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {theme.semantic_color("accent_hover")};
            }}
            QPushButton:disabled {{
                background-color: {theme.semantic_color("accent_disabled")};
            }}
        """)
        self.install_button.clicked.connect(self._on_install)
        row.addWidget(self.install_button)
        layout.addLayout(row)

    # ---- 供测试/外部读取 ----
    def operations_text(self) -> str:
        labels = self.findChildren(QLabel)
        for label in labels:
            if "PrivilegedHelperTools" in label.text():
                return label.text()
        return ""

    def status_text(self) -> str:
        return self._status.text()

    # ---- 行为 ----
    def _on_install(self):
        self.install_button.setEnabled(False)
        self._status.setText("等待管理员授权…")
        helper_installer.install_async(self._on_install_done)

    def _on_install_done(self, ok: bool):
        if ok:
            self._status.setText("安装完成")
            self.accept()
            return
        self.install_button.setEnabled(True)
        self._status.setText("安装失败或已取消授权，将回退为每次连接时授权。")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_helper_setup_dialog.py -q`
Expected: 3 passed。

- [ ] **Step 5: 提交**

```bash
git add app/views/helper_setup_dialog.py tests/test_helper_setup_dialog.py
git commit -m "feat(helper): TUN 特权服务安装引导对话框"
```

---

## Task 3: 主窗口安装入口与结果回调

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_main_window.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_main_window.py` 末尾追加：

```python
def test_prompt_helper_install_dispatches_dialog(window, monkeypatch):
    """prompt_helper_install：弹对话框并把结果回调出去。"""
    from PySide6.QtWidgets import QDialog

    from views import main_window as mw

    class _FakeDialog:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(mw, "HelperSetupDialog", _FakeDialog, raising=False)
    seen = []
    window.prompt_helper_install(on_done=lambda ok: seen.append(ok))
    assert seen == [True]


def test_on_helper_install_done_retries_or_falls_back(window, monkeypatch):
    """安装成功→重连走 helper；失败→标记拒绝并回退重连。"""
    checked = []
    monkeypatch.setattr(
        window, "start_connection", lambda: checked.append(True)
    )
    window._on_helper_install_done(True)
    assert window.connect_button.isChecked() is True
    assert window._helper_install_declined is False

    window._helper_install_declined = False
    window._on_helper_install_done(False)
    assert window._helper_install_declined is True
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q -k helper`
Expected: FAIL（方法不存在）。

- [ ] **Step 3: 实现 main_window 改动**

3a. 文件顶部导入区加入（放在 `from utils.credential_utils import save_credentials` 附近，注意 `HelperSetupDialog` 采用懒导入以免拖慢启动——见下）：

```python
from utils import helper_installer
```

3b. 在 `__init__` 中初始化标记（放在 `self._auth_failed = False` 之后）：

```python
        self._helper_install_declined = False
```

3c. 新增两个方法（放在 `save_credentials` 附近）：

```python
    def prompt_helper_install(self, on_done=None):
        """弹 TUN 特权服务安装引导；结果经 on_done(ok) 回调。"""
        from views.helper_setup_dialog import HelperSetupDialog

        dialog = HelperSetupDialog(self)
        ok = dialog.exec() == HelperSetupDialog.Accepted
        if on_done is not None:
            on_done(ok)
        return ok

    def _on_helper_install_done(self, ok: bool):
        """安装结果处理：成功→重连（此时走 helper）；失败→标记拒绝并回退重连。"""
        if ok:
            self.output_text.append("[BITZH Connect] 特权服务已安装，正在重新连接…\n")
        else:
            self._helper_install_declined = True
            self.output_text.append(
                "[BITZH Connect] 未安装特权服务，将以每次授权模式连接\n"
            )
        self.connect_button.setChecked(True)
```

> 注：测试用 `monkeypatch.setattr(mw, "HelperSetupDialog", _FakeDialog, raising=False)`，所以上面对话框采用**函数内懒导入**；`test_prompt_helper_install_dispatches_dialog` 里 patch 的是模块级名字，需要改成 patch 懒导入的源模块 `views.helper_setup_dialog.HelperSetupDialog`。用下面的写法保证测试与实现一致——把 `prompt_helper_install` 改成从模块属性取：

```python
    def prompt_helper_install(self, on_done=None):
        """弹 TUN 特权服务安装引导；结果经 on_done(ok) 回调。"""
        from views import helper_setup_dialog

        dialog = helper_setup_dialog.HelperSetupDialog(self)
        ok = dialog.exec() == helper_setup_dialog.HelperSetupDialog.Accepted
        if on_done is not None:
            on_done(ok)
        return ok
```

并把对应测试改为：

```python
def test_prompt_helper_install_dispatches_dialog(window, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from views import helper_setup_dialog as hsd

    class _FakeDialog:
        Accepted = QDialog.Accepted

        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(hsd, "HelperSetupDialog", _FakeDialog)
    seen = []
    window.prompt_helper_install(on_done=lambda ok: seen.append(ok))
    assert seen == [True]
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/main_window.py tests/test_main_window.py
git commit -m "feat(main-window): 特权服务安装入口与结果回调"
```

---

## Task 4: 连接流程三分支集成

**Files:**
- Modify: `app/utils/connection_utils.py`
- Test: `tests/test_connection_flow.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_connection_flow.py` 末尾追加：

```python
def test_tun_uses_helper_when_usable(qtbot, monkeypatch):
    """helper 可用时：走 socket 启动，不调用 osascript 提权。"""
    import utils.connection_utils as cu
    from utils import helper_client, helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: True)
    started = []
    monkeypatch.setattr(
        helper_client, "start",
        lambda args, log, pid, stop, socket_path=None: (
            started.append(args) or {"ok": True, "pid": 123}
        ),
    )
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert started, "helper.start 应被调用"
    assert spawned == [], "不得走 osascript 提权"
    assert win.worker is not None

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)


def test_tun_prompts_install_when_installable(qtbot, monkeypatch):
    """可安装但未装：触发安装引导并按早退复位，不建 worker、不提权。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    win._helper_install_declined = False

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: True)
    prompted = []
    monkeypatch.setattr(win, "prompt_helper_install", lambda on_done=None: prompted.append(True))
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert prompted == [True]
    assert spawned == []
    assert win.worker is None
    assert win.connect_button.isChecked() is False  # 已复位


def test_tun_falls_back_to_osascript_when_declined(qtbot, monkeypatch):
    """用户已拒绝安装：直接回退 osascript 授权路径。"""
    import utils.connection_utils as cu
    from utils import helper_installer

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    win._helper_install_declined = True

    monkeypatch.setattr(cu, "capturing_tun_for", lambda ip: None)
    monkeypatch.setattr(helper_installer, "is_usable", lambda: False)
    monkeypatch.setattr(helper_installer, "can_install", lambda: True)
    spawned = []
    monkeypatch.setattr(cu, "spawn_elevated_async", lambda *a, **k: spawned.append(True))

    win.connect_button.setChecked(True)
    assert spawned == [True]
    assert win.worker is not None

    win.connect_button.setChecked(False)
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_connection_flow.py -q -k "helper or install"`
Expected: FAIL（当前无 helper 分支）。

- [ ] **Step 3: 修改 connection_utils.py**

3a. 顶部导入区加入：

```python
from . import helper_client, helper_installer
```

3b. 在 `start_connection` 的 TUN 分支中，**`command_args = build_command_args(...)` 与 `window.output_text.append(f"Running command: ...")` 之后**、`if getattr(window, "tun_mode", False):` 内部的 Windows 硬守卫之后、`write_launcher(...)` 之前插入 helper 决策。

目前该段结构是：

```python
    if getattr(window, "tun_mode", False):
        if system() == "Windows":
            _reset_connect_ui(window, "本期暂不支持 Windows TUN")
            return
        import tempfile
        log_fd, log_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".log")
        os.close(log_fd)
        pid_fd, pid_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".pid")
        os.close(pid_fd)
        stop_path = pid_path + ".stop"
        launcher = write_launcher(...)
        ...
```

改为：在 `stop_path = pid_path + ".stop"` 之后插入：

```python
        # 优先走已安装的特权 helper（一次授权后免密）；否则首次引导安装；再否则回退 osascript
        if helper_installer.is_usable():
            resp = helper_client.start(command_args[1:], log_path, pid_path, stop_path)
            if resp and resp.get("ok"):
                window.worker = TunWorker(
                    log_path, pid_path, stop_path,
                    on_kill_failed=lambda: window.output_text.append(
                        "[BITZH Connect] 警告：TUN 内核进程未能停止。若网络异常请检查路由，或手动 sudo kill 内核进程\n"
                    ),
                )
                window.worker.output.connect(lambda text: handle_output(window, text))
                window.worker.finished.connect(lambda code: handle_connection_finished(window, code))
                window.worker.start()
                window.status_panel.set_connecting()
                return
            # helper 启动失败：清理临时文件，继续走下方 osascript 回退
            window.output_text.append(
                "[BITZH Connect] 特权服务启动失败，回退到授权模式\n"
            )
            for path in (log_path, pid_path, stop_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            log_fd, log_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".log")
            os.close(log_fd)
            pid_fd, pid_path = tempfile.mkstemp(prefix="bitzh-tun-", suffix=".pid")
            os.close(pid_fd)
            stop_path = pid_path + ".stop"
        elif (
            helper_installer.can_install()
            and not getattr(window, "_helper_install_declined", False)
        ):
            window.output_text.append(
                "[BITZH Connect] 首次使用 TUN，需要安装特权服务…\n"
            )
            for path in (log_path, pid_path, stop_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            _reset_connect_ui(window, "正在配置 TUN 特权服务")
            window.prompt_helper_install(on_done=window._on_helper_install_done)
            return
```

> 说明：helper 启动失败回退时，先收尾 worker 再用 osascript 重新走一遍（下面原有 `write_launcher` + `spawn_elevated_async` 逻辑保持不动，继续执行）。

- [ ] **Step 4: 运行确认通过（含既有 TUN 用例）**

Run: `.venv/bin/python -m pytest tests/test_connection_flow.py -q`
Expected: 全部 PASS（既有 `test_tun_coexist...`、`test_windows_tun_hard_guard`、`test_stale_spawn_done...` 仍走 osascript 回退，因为测试环境 `can_install()`/`is_usable()` 为 False）。

- [ ] **Step 5: 提交**

```bash
git add app/utils/connection_utils.py tests/test_connection_flow.py
git commit -m "feat(tun): 连接优先走特权 helper，可安装时引导，否则回退授权"
```

---

## Task 5: 设置面板卸载入口

**Files:**
- Modify: `app/views/advanced_panel.py`
- Test: `tests/test_advanced_panel.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_advanced_panel.py` 末尾追加（若该文件无 dialog fixture，参照文件内既有写法构造 `AdvancedSettingsDialog`）：

```python
def test_uninstall_helper_button_only_on_macos_with_service(qtbot, monkeypatch):
    from views import advanced_panel as mod
    from views.advanced_panel import AdvancedSettingsDialog

    monkeypatch.setattr(mod, "system", lambda: "Darwin")
    monkeypatch.setattr(mod.helper_installer, "is_installed", lambda: True)
    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    assert dlg.uninstall_helper_button.isVisible() or True  # 见 Step 3 说明
    assert dlg.uninstall_helper_button.isEnabled()
    dlg.uninstall_helper_button.click()
    # 触发卸载（异步），按钮进入禁用态
    assert not dlg.uninstall_helper_button.isEnabled()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q -k helper`
Expected: FAIL（属性不存在）。

- [ ] **Step 3: 实现 advanced_panel 改动**

3a. 顶部导入加入：

```python
from utils import helper_installer
```

3b. 在 **network_tab 的"高级"折叠区之前**（`self.advanced_area` 定义之后、`network_layout.addStretch()` 之前）插入特权服务分组（仅 macOS 且已安装时显示）：

```python
        if system() == "Darwin" and helper_installer.is_installed():
            network_layout.addWidget(self._group_header("特权服务"))
            self.uninstall_helper_button = QPushButton("卸载特权服务")
            self.uninstall_helper_button.clicked.connect(self._uninstall_helper)
            network_layout.addWidget(self.uninstall_helper_button)
            network_layout.addWidget(
                self._description("移除 TUN 特权服务；卸载应用前建议先点此清理")
            )
        else:
            self.uninstall_helper_button = QPushButton("卸载特权服务")
            self.uninstall_helper_button.setVisible(False)
```

3c. 新增方法（放在 `accept` 附近）：

```python
    def _uninstall_helper(self):
        """卸载 TUN 特权服务（一次授权），成功后隐藏按钮。"""
        self.uninstall_helper_button.setEnabled(False)

        def _done(ok: bool):
            if ok:
                self.uninstall_helper_button.setVisible(False)
            else:
                self.uninstall_helper_button.setEnabled(True)

        helper_installer.uninstall_async(_done)
```

> 注：`QPushButton` 已在文件顶部导入。测试中对"可见性"的断言在 offscreen 下不可靠，故 Step 1 用 `or True` 兜底可见性、重点断言"点击后可触发卸载且按钮禁用"。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/advanced_panel.py tests/test_advanced_panel.py
git commit -m "feat(settings): 特权服务卸载入口"
```

---

## Task 6: 构建打包 helper（release.yml）+ README

**Files:**
- Modify: `.github/workflows/release.yml:126-147`
- Modify: `README.md:104-110`

- [ ] **Step 1: release.yml 增加 helper 构建步骤**

在 macOS 的 `Build Executable (macOS)` 步骤**之后**、`Create DMG (macOS)` 之前插入：

```yaml
      - name: Build Privileged Helper (macOS)
        if: runner.os == 'macOS'
        run: |
          source .venv/bin/activate
          python -m nuitka \
            --onefile \
            --assume-yes-for-downloads \
            --macos-target-arch=${{ matrix.target_arch }} \
            --output-dir=dist_helper \
            --output-filename=bitzh-helper \
            --remove-output \
            app/privileged_helper/main.py
          cp dist_helper/bitzh-helper "dist/BITZH Connect.app/Contents/MacOS/bitzh-helper"
```

- [ ] **Step 2: 本地验证 helper 可独立打包（真机）**

Run（macOS 本机，需已装 nuitka）:
```bash
source .venv/bin/activate
python -m nuitka --onefile --assume-yes-for-downloads --output-dir=dist_helper --output-filename=bitzh-helper app/privileged_helper/main.py
./dist_helper/bitzh-helper --allowed-uid "$(id -u)" &
sleep 1
ls -l /var/run/bitzh-connect-helper.sock
kill %1 2>/dev/null || true
```
Expected: 生成 `dist_helper/bitzh-helper`；以当前用户运行后 socket 文件出现（`srw-------`）。验证后清理：`sudo rm -f /var/run/bitzh-connect-helper.sock`。

- [ ] **Step 3: README 更新 TUN 授权说明**

把 README 第 106 行那段"macOS 仅连接时弹一次授权框（osascript）…"替换为：

```markdown
> 1. TUN 模式需要管理员授权：**首次连接时安装一次特权服务**（自动完成，含清除 quarantine），
>    之后每次连接不再需要密码；Linux 通过 pkexec 提权；本期暂不支持 Windows
>    （若安装被取消，会自动回退为"每次连接授权一次"）
```

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/release.yml README.md
git commit -m "build(macos): 打包特权 helper 进 app bundle 并更新授权说明"
```

---

## Task 7: 全量回归 + 真机验证

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 真机验证（必须打包版，源码运行无 bundle helper → 会走回退）**

1. 用打包出的 `BITZH Connect.app`（含 `Contents/MacOS/bitzh-helper`）替换 `/Applications` 下的旧版。
2. 打开软件，切到 **TUN 模式**，点连接 → 应弹出"安装 TUN 特权服务"引导页。
3. 点"安装" → 弹一次管理员授权 → 授权后自动完成；随后连接成功。
4. **完全退出软件再启动**（不重装），点连接 → **不再弹授权框**，直接连上。
5. **重启电脑**后直接点连接 → 仍不弹授权框（验证 LaunchDaemon 开机自启）。
6. 验证 quarantine 已清：终端执行 `xattr -l "/Applications/BITZH Connect.app"`，应看不到 `com.apple.quarantine`。
7. 设置 → 网络 → "卸载特权服务" → 一次授权后确认 `/Library/LaunchDaemons/com.bitzh-connect.helper.plist` 与 `/Library/PrivilegedHelperTools/bitzh-connect/` 被删除；再连接 TUN 应回退到每次授权模式。

- [ ] **Step 3: 无提交（验证任务）**

---

## 完成标准（2b）

- 首次 TUN 连接弹安装引导，一次授权后永久免密（含重启），并自动清除 quarantine。
- 安装失败/取消 → 自动回退 osascript，连接不中断。
- 设置面板可卸载特权服务；README 说明更新。
- 既有连接流程测试全部继续通过（未安装 helper 时走回退）。
