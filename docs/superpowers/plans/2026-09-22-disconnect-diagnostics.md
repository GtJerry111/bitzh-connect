# 断开诊断与自愈 Implementation Plan（阶段 3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"频繁断开"可观测、可自愈——持久化连接诊断日志；连接中被 FlClash 等他方 TUN 抢走服务器路由时自动重连并绑定物理网卡；内核假死（进程活着但隧道不通）时自动重连。

**Architecture:** 新增 `diagnostics`（带轮转的持久化日志）、扩展 `log_parser`（原因分类/接口名/keepalive 识别）、新增 `ConnectionWatchdog`（QTimer 周期探测服务器路由出口与内核输出活跃度，命中则发信号）。主窗口接信号做"带冷却的 bounce 重连"；连接生命周期各节点写诊断日志。

**Tech Stack:** Python 3.11 / PySide6 QTimer / pytest；复用 `tun_utils.capturing_tun_for`。

**Spec:** 本会话 grilling 结论（问题 2）。

---

## 背景（给零上下文的工程师）

- 用户现象：连接会"频繁断开"（内核进程真的退出，自动重连在跑）。
- 已实测：去服务器 IP 的路由被 FlClash 的 TUN 截走，而连接时 `-bind-interface` 共存绑定**没有生效**（检测只在连接那一刻做一次，挡不住"连接之后才被抢"）。
- 另有一个缺陷：`TunWorker` 只看内核进程存活，进程活着但隧道不通（假死）不会触发重连。
- 未安装/未使用 helper（阶段 2）时也要工作；本阶段全部为 GUI 侧逻辑，与 2a/2b 解耦。
- 测试环境无真实路由/网络需求——探测函数都通过注入/monkeypatch 测试。
- 运行测试：`.venv/bin/python -m pytest <path> -q`。

## File Structure

- `app/utils/diagnostics.py` — 新建：日志目录/路径、带轮转的 append
- `app/utils/log_parser.py` — 修改：接口名/keepalive 解析、断开原因分类
- `app/services/connection_watchdog.py` — 新建：路由被抢 + 假死探测
- `app/utils/connection_utils.py` — 修改：生命周期写诊断日志
- `app/views/main_window.py` — 修改：接入 watchdog、自愈 bounce、活跃度打点
- `app/views/advanced_panel.py` — 修改：打开日志目录/导出按钮
- `tests/test_diagnostics.py`、`tests/test_log_parser.py`（追加）、`tests/test_connection_watchdog.py`、`tests/test_connection_flow.py`（追加）、`tests/test_main_window.py`（追加）

---

## Task 1: 诊断日志持久化

**Files:**
- Create: `app/utils/diagnostics.py`
- Test: `tests/test_diagnostics.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_diagnostics.py`：

```python
import os

from utils import diagnostics


def test_log_path_under_app_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    assert diagnostics.log_path().endswith("bitzh-connect.log")
    assert str(tmp_path) in diagnostics.log_path()


def test_append_creates_file_and_timestamps(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    diagnostics.append("hello world")
    content = open(diagnostics.log_path(), encoding="utf-8").read()
    assert "hello world" in content
    # 行首应是时间戳
    assert content.split(" ", 1)[0].count("-") == 2


def test_append_rotates_when_too_large(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: str(tmp_path))
    monkeypatch.setattr(diagnostics, "_MAX_BYTES", 50)
    diagnostics.append("x" * 100)
    diagnostics.append("second")
    assert os.path.exists(diagnostics.log_path() + ".1")
    # 新文件里只有第二行
    current = open(diagnostics.log_path(), encoding="utf-8").read()
    assert "second" in current and "x" * 100 not in current


def test_append_never_raises_on_bad_dir(monkeypatch):
    monkeypatch.setattr(diagnostics, "_log_base_dir", lambda: "/proc/definitely/not/writable")
    diagnostics.append("boom")  # 不抛异常
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: collection error（模块不存在）。

- [ ] **Step 3: 实现 diagnostics.py**

创建 `app/utils/diagnostics.py`：

```python
"""连接诊断日志持久化：连接起止、断开原因、路由快照、内核输出（带轮转）。

日志文件不落任意敏感数据之外的额外内容；内核原始输出本身不含密码
（zju-connect 不打印密码）。目标：断线后可事后定位原因。
"""
import os
import time
from platform import system

_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3


def _log_base_dir() -> str:
    if system() == "Darwin":
        base = os.path.expanduser("~/Library/Logs")
    elif system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.local/state")
    return os.path.join(base, "BITZH Connect")


def log_dir() -> str:
    return _log_base_dir()


def log_path() -> str:
    return os.path.join(_log_base_dir(), "bitzh-connect.log")


def _rotate(path: str):
    try:
        if not os.path.exists(path) or os.path.getsize(path) < _MAX_BYTES:
            return
    except OSError:
        return
    for index in range(_BACKUPS - 1, 0, -1):
        src = f"{path}.{index}"
        if os.path.exists(src):
            try:
                os.replace(src, f"{path}.{index + 1}")
            except OSError:
                pass
    try:
        os.replace(path, path + ".1")
    except OSError:
        pass


def append(line: str):
    """追加一行（自动加时间戳并轮转）；任何失败都静默忽略，不影响主流程。"""
    try:
        os.makedirs(_log_base_dir(), exist_ok=True)
        path = log_path()
        _rotate(path)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{stamp} {str(line).rstrip()}\n")
    except OSError:
        pass
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/utils/diagnostics.py tests/test_diagnostics.py
git commit -m "feat(diagnostics): 持久化连接日志与轮转"
```

---

## Task 2: log_parser 扩展（接口名/keepalive/原因分类）

**Files:**
- Modify: `app/utils/log_parser.py`
- Test: `tests/test_log_parser.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_log_parser.py` 末尾追加：

```python
def test_parse_tun_interface():
    from utils.log_parser import parse_tun_interface

    assert parse_tun_interface("2026/09/22 14:32:17 Interface Name: utun11, index 32") == "utun11"
    assert parse_tun_interface("nothing") is None


def test_is_keepalive():
    from utils.log_parser import is_keepalive

    assert is_keepalive("2026/09/22 14:33:17 KeepAlive using UDP: OK")
    assert not is_keepalive("Client IP: 10.0.43.58")


def test_classify_disconnect():
    from utils.log_parser import classify_disconnect

    assert classify_disconnect("SHUTDOWN (cmd 0x08)") == "server_kick"
    assert classify_disconnect("RECONNECTLATER (cmd 0x01)") == "server_kick"
    assert classify_disconnect("Invalid username or password") == "auth"
    assert classify_disconnect("dial tcp: i/o timeout") == "network"
    assert classify_disconnect("connection reset by peer") == "network"
    assert classify_disconnect("ordinary line") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_log_parser.py -q -k "tun_interface or keepalive or classify"`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现扩展**

在 `app/utils/log_parser.py` 末尾追加：

```python
_TUN_IFACE_RE = re.compile(r"Interface Name:\s*(\S+)")
_KEEPALIVE_RE = re.compile(r"KeepAlive", re.IGNORECASE)

# 网络层断开特征（非服务器主动踢、非认证失败）
_NETWORK_ERROR_PATTERNS = [
    re.compile(r"i/o timeout", re.IGNORECASE),
    re.compile(r"connection reset", re.IGNORECASE),
    re.compile(r"broken pipe", re.IGNORECASE),
    re.compile(r"network is unreachable", re.IGNORECASE),
    re.compile(r"no route to host", re.IGNORECASE),
    re.compile(r"EOF", re.IGNORECASE),
]


def parse_tun_interface(text: str) -> str | None:
    """从内核输出解析本连接创建的 TUN 接口名（如 utun11）。"""
    match = _TUN_IFACE_RE.search(text)
    return match.group(1) if match else None


def is_keepalive(text: str) -> bool:
    """是否为本连接的 keepalive 输出行（用于假死活跃度打点）。"""
    return bool(_KEEPALIVE_RE.search(text))


def classify_disconnect(text: str) -> str | None:
    """把一行内核输出分类为断开原因：server_kick/auth/network/None。"""
    if is_server_kick(text):
        return "server_kick"
    if is_auth_failure(text):
        return "auth"
    if any(pattern.search(text) for pattern in _NETWORK_ERROR_PATTERNS):
        return "network"
    return None
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_log_parser.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/utils/log_parser.py tests/test_log_parser.py
git commit -m "feat(log-parser): TUN 接口名/keepalive/断开原因分类"
```

---

## Task 3: ConnectionWatchdog

**Files:**
- Create: `app/services/connection_watchdog.py`
- Test: `tests/test_connection_watchdog.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_connection_watchdog.py`：

```python
import time

from services.connection_watchdog import ConnectionWatchdog


def _watchdog(route_probe, **kw):
    return ConnectionWatchdog(
        route_probe=route_probe,
        route_interval_ms=10,
        idle_timeout_s=kw.pop("idle_timeout_s", 100),
        cooldown_s=kw.pop("cooldown_s", 0),
    )


def test_route_captured_emits_once_then_observes_cooldown(qtbot):
    events = []
    probe = lambda: "utun5"
    wd = _watchdog(probe, cooldown_s=100)
    wd.route_captured.connect(lambda iface: events.append(iface))
    wd.start()
    qtbot.waitUntil(lambda: len(events) >= 1, timeout=1000)
    qtbot.wait(80)  # 等几个周期
    assert events == ["utun5"]  # 冷却内只报一次
    wd.stop()


def test_no_route_signal_when_probe_none(qtbot):
    events = []
    wd = _watchdog(lambda: None)
    wd.route_captured.connect(events.append)
    wd.start()
    qtbot.wait(80)
    assert events == []
    wd.stop()


def test_suspected_dead_when_no_activity(qtbot):
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=0)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    qtbot.waitUntil(lambda: events, timeout=1000)
    wd.stop()


def test_activity_resets_idle_timer(qtbot):
    events = []
    wd = _watchdog(lambda: None, idle_timeout_s=100)
    wd.suspected_dead.connect(lambda: events.append(True))
    wd.start()
    for _ in range(5):
        wd.note_activity()
        qtbot.wait(10)
    assert events == []
    wd.stop()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_connection_watchdog.py -q`
Expected: collection error。

- [ ] **Step 3: 实现 watchdog**

创建 `app/services/connection_watchdog.py`：

```python
"""连接看门狗：服务器路由被抢 + 内核假死监测。

- 路由被抢：周期调用 route_probe()（返回占用服务器路由的他方 TUN 名或 None），
  非 None 即发 route_captured（带冷却，避免连续刷屏/反复重连）。
- 假死：连接建立后若超过 idle_timeout_s 没有任何内核输出（note_activity 打点），
  发 suspected_dead（同样带冷却）。
"""
import time

from PySide6.QtCore import QObject, QTimer, Signal


class ConnectionWatchdog(QObject):
    route_captured = Signal(str)
    suspected_dead = Signal()

    def __init__(self, route_probe, route_interval_ms: int = 30000,
                 idle_timeout_s: float = 180.0, cooldown_s: float = 60.0,
                 parent=None):
        super().__init__(parent)
        self._route_probe = route_probe
        self._idle_timeout_s = idle_timeout_s
        self._cooldown_s = cooldown_s
        self._timer = QTimer(self)
        self._timer.setInterval(route_interval_ms)
        self._timer.timeout.connect(self._tick)
        self._last_route_alert = 0.0
        self._last_dead_alert = 0.0
        self._last_activity = 0.0
        self._running = False

    def start(self):
        self._last_activity = time.time()
        self._running = True
        self._timer.start()

    def stop(self):
        self._running = False
        self._timer.stop()

    def note_activity(self):
        self._last_activity = time.time()

    def _tick(self):
        if not self._running:
            return
        now = time.time()
        try:
            captured = self._route_probe()
        except Exception:
            captured = None
        if captured and now - self._last_route_alert >= self._cooldown_s:
            self._last_route_alert = now
            self.route_captured.emit(captured)
        if now - self._last_activity >= self._idle_timeout_s:
            if now - self._last_dead_alert >= self._cooldown_s:
                self._last_dead_alert = now
                self._last_activity = now  # 避免每拍都报
                self.suspected_dead.emit()
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_connection_watchdog.py -q`
Expected: 4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/services/connection_watchdog.py tests/test_connection_watchdog.py
git commit -m "feat(services): 连接看门狗（路由被抢 + 假死）"
```

---

## Task 4: 主窗口接入看门狗与自愈

**Files:**
- Modify: `app/views/main_window.py`
- Test: `tests/test_main_window.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_main_window.py` 末尾追加：

```python
def test_watchdog_starts_on_connect_and_stops_on_disconnect(window, monkeypatch):
    from utils.connection_utils import handle_output, handle_connection_finished

    started = []
    monkeypatch.setattr(window._watchdog, "start", lambda: started.append("start"))
    monkeypatch.setattr(window._watchdog, "stop", lambda: started.append("stop"))

    handle_output(window, "2026/09/22 14:32:17 Client IP: 10.0.43.58\n")
    assert "start" in started

    window._manual_stop = True
    handle_connection_finished(window, -1)
    assert "stop" in started


def test_route_captured_triggers_bounce(window, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "_bounce_connection", lambda: fired.append(True))
    window._on_route_captured("utun5")
    assert fired == [True]
    assert "被" in window.output_text.toPlainText() or "共存" in window.output_text.toPlainText()


def test_suspected_dead_triggers_bounce(window, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "_bounce_connection", lambda: fired.append(True))
    window._on_suspected_dead()
    assert fired == [True]


def test_activity_noted_on_output(window):
    window._watchdog.note_activity = lambda: setattr(window, "_noted", True)
    from utils.connection_utils import handle_output

    handle_output(window, "2026/09/22 14:32:18 KeepAlive using UDP: OK\n")
    assert getattr(window, "_noted", False) is True
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_main_window.py -q -k "watchdog or route or dead or activity"`
Expected: FAIL。

- [ ] **Step 3: 实现 main_window 改动**

3a. 顶部导入加入：

```python
from services.connection_watchdog import ConnectionWatchdog
from utils.tun_utils import capturing_tun_for
```

3b. 在 `__init__` 创建 watchdog（放在 `install_sleep_wake_hooks(self)` 之前）：

```python
        # 连接看门狗：路由被抢 / 内核假死时自愈重连（探测函数每次现取当前 server）
        self._watchdog = ConnectionWatchdog(
            route_probe=lambda: capturing_tun_for(self.server_address),
        )
        self._watchdog.route_captured.connect(self._on_route_captured)
        self._watchdog.suspected_dead.connect(self._on_suspected_dead)
```

3c. 新增方法（放在 `_bounce_connection` 附近）：

```python
    def _on_route_captured(self, interface: str):
        """服务器路由被他方 TUN 截走：记日志并重连（重连会启用共存绑定）。"""
        from utils import diagnostics

        diagnostics.append(f"检测到服务器路由被 {interface} 截走，自动重连并启用共存绑定")
        self.output_text.append(
            f"[BITZH Connect] 检测到服务器路由被 {interface} 占用，正在自动重连（共存模式）…\n"
        )
        self._bounce_connection()

    def _on_suspected_dead(self):
        """内核疑似假死（长时间无输出）：记日志并重连。"""
        from utils import diagnostics

        diagnostics.append("内核长时间无输出，判定疑似假死，自动重连")
        self.output_text.append("[BITZH Connect] 连接长时间无响应，正在自动重连…\n")
        self._bounce_connection()
```

- [ ] **Step 4a（前置）: 隔离测试环境的诊断日志目录**

在 `tests/conftest.py` 的 `_isolate_app` fixture 中隔离诊断日志目录（避免测试写入真实 `~/Library/Logs`）：把签名改为接收 `tmp_path`，并在末尾追加一行。修改后为：

```python
@pytest.fixture(autouse=True)
def _isolate_app(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    monkeypatch.setattr("utils.config_utils.APP_NAME", "BITZH Connect Test")
    monkeypatch.setattr("utils.config_utils.ORG_NAME", "BITZH Connect Test")
    QSettings("BITZH Connect Test", "BITZH Connect Test").clear()
    monkeypatch.setattr("views.main_window.check_for_updates", lambda *a, **k: None)
    # 诊断日志不写入真实用户目录
    monkeypatch.setattr("utils.diagnostics._log_base_dir", lambda: str(tmp_path))
```

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: 4 passed（隔离生效，未写入真实目录）。

- [ ] **Step 4: 连接生命周期接线（connection_utils.py）**

修改 `app/utils/connection_utils.py`：

4a. 顶部加入：

```python
from . import diagnostics
```

4b. `handle_output` 中，**每次调用先给看门狗打活跃度并落诊断日志**。在函数开头（`if is_rsa_material(text):` 之前）插入：

```python
    watchdog = getattr(window, "_watchdog", None)
    if watchdog is not None:
        watchdog.note_activity()
    diagnostics.append(text)
```

4c. 在 `parse_client_ip` 命中后（`window.status_panel.set_connected(ip)` 之后）启动看门狗：

```python
        if getattr(window, "_watchdog", None) is not None:
            window._watchdog.start()
```

4d. `handle_connection_finished` 中停止看门狗。在 `manual = ...`/`auth_failed = ...` 附近加入：

```python
    if getattr(window, "_watchdog", None) is not None:
        window._watchdog.stop()
```

4e. `handle_connection_finished` 收尾时落一条"连接结束"诊断（含退出码与路由快照）。在 `window.reconnect_manager.on_process_exited(...)` **之前**插入：

```python
    from .tun_utils import capturing_tun_for

    route = capturing_tun_for(getattr(window, "server_address", "")) or "物理网卡"
    diagnostics.append(
        f"连接结束 exit={exit_code} manual={manual} auth_failed={auth_failed} "
        f"服务器路由出口={route}"
    )
```

4f. `start_connection` 中记录连接开始。在 `window._rsa_noted = False` 之后插入：

```python
    diagnostics.append(
        f"连接开始 server={window.server_address} tun={getattr(window, 'tun_mode', False)}"
    )
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_main_window.py tests/test_connection_flow.py -q`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add app/views/main_window.py app/utils/connection_utils.py tests/test_main_window.py
git commit -m "feat(connection): 看门狗接入连接生命周期与自愈重连"
```

---

## Task 5: 设置面板日志入口

**Files:**
- Modify: `app/views/advanced_panel.py`
- Test: `tests/test_advanced_panel.py`（追加）

- [ ] **Step 1: 写失败测试**

在 `tests/test_advanced_panel.py` 末尾追加：

```python
def test_open_log_dir_button_exists(qtbot, monkeypatch):
    from views import advanced_panel as mod
    from views.advanced_panel import AdvancedSettingsDialog

    opened = []
    monkeypatch.setattr(mod, "_open_path", lambda p: opened.append(p))
    dlg = AdvancedSettingsDialog()
    qtbot.addWidget(dlg)
    dlg.open_log_button.click()
    assert opened and opened[0].endswith("BITZH Connect")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q -k log`
Expected: FAIL。

- [ ] **Step 3: 实现**

3a. 顶部加入：

```python
import subprocess
from utils import diagnostics
```

3b. 加一个模块级函数（文件顶部导入之后）：

```python
def _open_path(path: str):
    """用系统默认方式打开目录/文件（失败静默）。"""
    try:
        if system() == "Darwin":
            subprocess.Popen(["open", path])
        elif system() == "Windows":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass
```

3c. 在 network tab 的"运行日志"按钮行 `log_btn_row` 中，"复制日志"按钮旁增加"打开日志目录"按钮：

```python
        copy_log_btn = QPushButton("复制日志")
        copy_log_btn.clicked.connect(self._copy_log)
        log_btn_row.addWidget(copy_log_btn)
        self.open_log_button = QPushButton("打开日志目录")
        self.open_log_button.clicked.connect(
            lambda: _open_path(diagnostics.log_dir())
        )
        log_btn_row.addWidget(self.open_log_button)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_advanced_panel.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add app/views/advanced_panel.py tests/test_advanced_panel.py
git commit -m "feat(settings): 打开日志目录入口"
```

---

## Task 6: 全量回归 + 真机验证

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部 PASS。

- [ ] **Step 2: 真机验证**

1. 启动软件并连接（TUN 模式保持 FlClash 的 TUN 打开）。
2. 确认文件 `~/Library/Logs/BITZH Connect/bitzh-connect.log` 生成，内容含"连接开始/连接结束"、内核输出。
3. 手动触发路由被抢场景：连接成功后，在 FlClash 里开启/切换 TUN，观察日志与界面出现"检测到服务器路由被 … 占用，正在自动重连（共存模式）"，并确认重连后命令行带 `-bind-interface`（可 `ps aux | grep zju-connect` 查看）。
4. 假死自愈：连接后，人为中断一段时间（如让 FlClash 走全局代理导致隧道无响应），观察超过阈值后自动重连并写日志。
5. 设置 → 网络 → "打开日志目录" 能在 Finder 打开日志文件夹。

- [ ] **Step 3: 无提交（验证任务）**

---

## 完成标准（阶段 3）

- 每次连接在 `~/Library/Logs/BITZH Connect/bitzh-connect.log` 留下可追溯记录（起止/退出码/原因/路由快照）。
- 服务器路由被他方 TUN 抢走时自动重连并启用 `-bind-interface`（有日志、有用户提示）。
- 内核假死（长时间无输出）自动重连。
- 设置面板可一键打开日志目录。
