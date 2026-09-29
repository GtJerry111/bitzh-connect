# 休眠/锁屏唤醒自动重连 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让合盖休眠唤醒、锁屏解锁、内核假死三种场景都能真正自动重连，且全程事件驱动、不新增任何轮询/心跳。

**Architecture:** 根因有两个——(1) `_bounce_connection` 用固定 1s 盲等重连，短于 TUN 内核 ~3s 的关闭耗时，重连撞上仍在运行的旧 worker 后被 `start_connection` 的 `isRunning` 守卫静默吞掉；(2) 只订阅了整机睡眠/唤醒通知，没订阅屏幕（锁屏）通知。修复方式：bounce 改为由 `handle_connection_finished` 事件驱动；新增屏幕休眠/唤醒通知；两个唤醒入口共用一个带防抖的 `_recover_connection`；休眠/锁屏统一 `_suppress_reconnect`。

**Tech Stack:** Python 3.11 / PySide6 (Qt) / pyobjc (NSWorkspace 通知桥) / pytest + pytest-qt

---

## 背景与根因（实证）

- 诊断日志 `~/Library/Logs/BITZH Connect/bitzh-connect.log` 显示：每次“疑似假死自动重连”后立即“连接结束 manual=True”，几十~上百分种后才出现“连接开始”（用户手动连的）——**自动重连一直是坏的**。
- `_bounce_connection`（`app/views/main_window.py:656`）固定 `QTimer.singleShot(1000, ...)`，而 TUN 内核关闭要 ~3s（日志：19:57:25 发起关闭 → 19:57:28 关闭完成）。
- 1s 后 `_bounce_reconnect` 触发 `setChecked(True)` → `start_connection`，此时旧 worker 仍在跑，命中 `app/utils/connection_utils.py:235-237` 的 `if window.worker and window.worker.isRunning(): return`，直接放弃且不重试。
- `app/utils/sleep_wake.py:47-52` 只注册 `NSWorkspaceWillSleepNotification` / `NSWorkspaceDidWakeNotification`；锁屏/显示器休眠走的是 `NSWorkspaceScreensDidSleepNotification` / `NSWorkspaceScreensDidWakeNotification`，未被监听。

## 文件结构

| 文件 | 职责 | 本次改动 |
| --- | --- | --- |
| `app/views/main_window.py` | 主窗口：连接按钮、重连协调、休眠/唤醒钩子入口 | bounce 事件驱动；新增 `_recover_connection`/`_suppress_reconnect`/屏幕休眠唤醒槽；删死变量 `_asleep` |
| `app/utils/connection_utils.py` | 进程输出解析、连接启动/收尾 | `handle_connection_finished` 尾部回调 `_maybe_finish_bounce` |
| `app/utils/sleep_wake.py` | macOS NSWorkspace 通知桥 | 新增屏幕休眠/唤醒两个观察者；安装失败落诊断日志 |
| `tests/test_main_window.py` | 主窗口单测 | 新增 bounce/recover/suppress 用例；更新受影响的既有用例 |

## 明确不做

- 不新增网络轮询/心跳/定时探测；不动看门狗周期（30s）与退避策略（5/10/30s）。
- 不引入新的连接状态模型（改完 bounce 后现有 `_manual_stop`/`_auth_failed` 语义自洽）。
- 非 macOS 平台不扩展屏幕通知（Windows/Linux 本期不做）。

---

## Task 1: bounce 改为事件驱动（核心修复）

**Files:**
- Modify: `app/views/main_window.py`（`__init__` 约 167-168 行；`_bounce_connection`/`_bounce_reconnect` 656-666 行）
- Modify: `app/utils/connection_utils.py:97-164`（`handle_connection_finished` 尾部）
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试——worker 存活时 bounce 不立即重连**

在 `tests/test_main_window.py` 的 `test_wake_noop_when_manually_disconnected` 之前插入：

```python
def test_bounce_defers_until_worker_finished(window, monkeypatch):
    """旧 worker 仍在运行时不立即重连（固定 1s 盲等的根因）。"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))

    window.connect_button.setChecked(True)  # toggled → start（已 mock）
    fired.clear()

    class _AliveWorker:
        def isRunning(self):
            return True

    window.worker = _AliveWorker()
    window._bounce_connection()
    assert fired == ["stop"]  # 只断了，没重连
    assert window._bounce_pending is True
    assert window.connect_button.isChecked() is False

    # 模拟旧 worker 收尾后 handle_connection_finished 的回调
    window.worker = None
    window._maybe_finish_bounce()
    assert window._bounce_pending is False
    assert window.connect_button.isChecked() is True
    assert fired == ["stop", "start"]
```

- [ ] **Step 2: 写失败测试——无 worker 时 bounce 立即重连**

紧接着插入：

```python
def test_bounce_reconnects_immediately_without_worker(window, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))

    window.connect_button.setChecked(True)
    fired.clear()
    window.worker = None

    window._bounce_connection()
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True
```

- [ ] **Step 3: 写失败测试——handle_connection_finished 收尾 pending bounce**

```python
def test_connection_finished_finishes_pending_bounce(window, monkeypatch):
    from utils.connection_utils import handle_connection_finished

    calls = []
    monkeypatch.setattr(window, "_maybe_finish_bounce", lambda: calls.append(True))
    window._bounce_pending = True
    window.worker = None
    handle_connection_finished(window, -1)
    assert calls == [True]
```

- [ ] **Step 4: 运行测试确认失败**

Run: `uv run pytest tests/test_main_window.py -k "bounce_defers or bounce_reconnects_immediately or connection_finished_finishes" -v`
Expected: FAIL（`_maybe_finish_bounce` 不存在；`_bounce_defers` 里 worker 存活却仍会重连）

- [ ] **Step 5: 实现——`__init__` 增初始化标志**

在 `app/views/main_window.py` 中，把：

```python
        self._manual_stop = True
        self._auth_failed = False
```

改为：

```python
        self._manual_stop = True
        self._auth_failed = False
        self._bounce_pending = False
        self._last_recover_ts = 0.0
```

- [ ] **Step 6: 实现——重写 bounce**

把 `_bounce_connection` 与 `_bounce_reconnect` 整段：

```python
    def _bounce_connection(self):
        """先断后连：worker 收尾（finished→复位）需要一拍，1s 后重连足够稳。"""
        self._bounce_pending = True
        self.connect_button.setChecked(False)
        QTimer.singleShot(1000, self._bounce_reconnect)

    def _bounce_reconnect(self):
        """bounce 第二拍（一次性守卫：这一拍内用户操作过则不强行重连）。"""
        if getattr(self, "_bounce_pending", False):
            self._bounce_pending = False
            self.connect_button.setChecked(True)
```

替换为：

```python
    def _bounce_connection(self):
        """先断后连：等旧 worker 真正收尾再重连（不再固定 1s 盲等）。

        TUN 内核关闭要 ~3s，固定 1s 会让重连撞上仍在运行的旧 worker，
        被 start_connection 的 isRunning 守卫静默吞掉。改为事件驱动：
        worker 存活 → 由 handle_connection_finished 回调 _maybe_finish_bounce；
        worker 已收尾（或从未有）→ 立即重连。
        """
        self._bounce_pending = True
        self.connect_button.setChecked(False)
        self._maybe_finish_bounce()

    def _maybe_finish_bounce(self):
        """bounce 第二拍：旧 worker 已收尾才真正重连（否则等 finished 回调）。"""
        if not self._bounce_pending:
            return
        worker = self.worker
        if worker is not None and worker.isRunning():
            return
        self._bounce_pending = False
        self.connect_button.setChecked(True)
```

- [ ] **Step 7: 实现——收尾回调挂钩**

在 `app/utils/connection_utils.py` 的 `handle_connection_finished` 末尾，把：

```python
    window.reconnect_manager.on_process_exited(manual=manual or never_started, auth_failed=auth_failed)
```

改为：

```python
    window.reconnect_manager.on_process_exited(manual=manual or never_started, auth_failed=auth_failed)
    # bounce 第二拍：旧 worker 已置 None，此时真正重连（事件驱动，无固定延时）
    finish_bounce = getattr(window, "_maybe_finish_bounce", None)
    if finish_bounce is not None:
        finish_bounce()
```

- [ ] **Step 8: 运行新测试确认通过**

Run: `uv run pytest tests/test_main_window.py -k "bounce_defers or bounce_reconnects_immediately or connection_finished_finishes" -v`
Expected: PASS

- [ ] **Step 9: 更新受影响的既有测试**

`test_mode_switch_bounces_when_connected`（约 105-124 行）：删除 `delayed` 与 `QTimer.singleShot` mock，改为断言立即重连。整段改为：

```python
def test_mode_switch_bounces_when_connected(window, monkeypatch):
    """已连接时切换模式：先断后连，新模式立即生效（不是禁用/下个周期再说）"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.connect_button.setChecked(True)  # 模拟已连接（start/stop 已 mock）
    fired.clear()

    window.mode_switch._set_current(0)  # 切到代理模式
    assert window.tun_mode is False
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True
```

`test_wake_bounces_active_connection`（约 138-159 行）整段改为：

```python
def test_wake_bounces_active_connection(window, monkeypatch):
    """唤醒且处于"应连接"态：先断后连（bounce），无固定延时"""
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window._manual_stop = False
    window._auth_failed = False
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))

    window.connect_button.setChecked(True)  # 模拟已连接（start 已 mock）
    fired.clear()
    window._on_system_wake()
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True
```

`test_on_helper_install_done_bounces_when_already_checked`（约 376-388 行）整段改为：

```python
def test_on_helper_install_done_bounces_when_already_checked(window, monkeypatch):
    """按钮已勾选时 setChecked(True) 是 no-op：须走 bounce 确保重连。"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))
    window.connect_button.setChecked(True)  # 模拟已连接（start/stop 已 mock）
    fired.clear()

    window._on_helper_install_done(True)
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True
    assert window._bounce_pending is False
```

- [ ] **Step 10: 跑全量主窗口测试**

Run: `uv run pytest tests/test_main_window.py -v`
Expected: 全部 PASS

- [ ] **Step 11: Commit**

```bash
git add app/views/main_window.py app/utils/connection_utils.py tests/test_main_window.py
git commit -m "fix(reconnect): bounce 改事件驱动，等旧 worker 收尾再重连"
```

---

## Task 2: 统一恢复入口 + 屏幕（锁屏）休眠/唤醒钩子

**Files:**
- Modify: `app/views/main_window.py`（`_on_system_sleep`/`_on_system_wake` 668-689 行）
- Modify: `app/utils/sleep_wake.py`
- Test: `tests/test_main_window.py`

- [ ] **Step 1: 写失败测试——断开态下恢复连接**

在 `tests/test_main_window.py` 的 `test_wake_bounces_active_connection` 之后插入：

```python
def test_recover_connection_reconnects_when_disconnected(window, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.auto_reconnect = True
    window._manual_stop = False
    window._auth_failed = False
    window.worker = None
    window.connect_button.setChecked(False)
    fired.clear()

    window._recover_connection("屏幕唤醒")
    assert window.connect_button.isChecked() is True
    assert fired == ["start"]


def test_recover_connection_debounced(window, monkeypatch):
    """系统唤醒 + 屏幕唤醒同拍只恢复一次（5s 防抖）"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.auto_reconnect = True
    window._manual_stop = False
    window._auth_failed = False
    window.worker = None
    window.connect_button.setChecked(False)
    fired.clear()

    window._recover_connection("系统唤醒")
    window._recover_connection("屏幕唤醒")
    assert fired == ["start"]


def test_recover_connection_respects_auto_reconnect_off(window, monkeypatch):
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.auto_reconnect = False
    window._manual_stop = False
    window._auth_failed = False
    window.worker = None
    window.connect_button.setChecked(False)
    fired.clear()

    window._recover_connection("系统唤醒")
    assert window.connect_button.isChecked() is False
    assert fired == []


def test_recover_connection_skips_manual_stop(window):
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window._manual_stop = True
    window._auth_failed = False
    window.connect_button.setChecked(False)
    window._recover_connection("屏幕唤醒")
    assert window.connect_button.isChecked() is False


def test_recover_connection_bounces_when_checked(window, monkeypatch):
    """内核仍勾选（可能假死）：唤醒走先断后连"""
    fired = []
    monkeypatch.setattr(window, "start_connection", lambda: fired.append("start"))
    monkeypatch.setattr(window, "stop_connection", lambda: fired.append("stop"))
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    window.auto_reconnect = True
    window._manual_stop = False
    window._auth_failed = False
    window.connect_button.setChecked(True)
    window.worker = None
    fired.clear()

    window._recover_connection("屏幕唤醒")
    assert fired == ["stop", "start"]
    assert window.connect_button.isChecked() is True
```

- [ ] **Step 2: 写失败测试——休眠/锁屏抑制在途重连**

```python
def test_screen_sleep_suppresses_inflight(window):
    """锁屏：取消退避重连 + 清 bounce + 停看门狗"""
    window.reconnect_manager.on_process_exited(manual=False, auth_failed=False)
    window._bounce_pending = True
    window._watchdog.start()

    window._on_screen_sleep()
    assert not window.reconnect_manager._retry_timer.isActive()
    assert window.reconnect_manager.retry_count == 0
    assert window._bounce_pending is False
    assert window._watchdog._running is False
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_main_window.py -k "recover_connection or screen_sleep_suppresses" -v`
Expected: FAIL（`_recover_connection` / `_on_screen_sleep` 不存在）

- [ ] **Step 4: 实现——替换休眠/唤醒逻辑**

在 `app/views/main_window.py` 中，把整段：

```python
    def _on_system_sleep(self):
        """系统休眠：取消在途重连退避——盒盖期间触发重连只会在无人理会时弹授权框。"""
        self._asleep = True
        self.reconnect_manager.cancel()

    def _on_system_wake(self):
        """唤醒：处于"应连接"态（非手动断开、非认证失败）则立即重连。

        两种情形：内核假死（按钮仍勾选）→ 先走后连 bounce；内核已在休眠期死亡
        （按钮被收尾复位）→ 直接重连。TUN 断开走停止标记零弹窗，重连弹一次授权框
        （用户刚开盖在场，时机合理）。
        """
        self._asleep = False
        if self._manual_stop or self._auth_failed:
            return
        if not (self.username_input.text() and self.password_input.text()):
            return
        self.output_text.append("[BITZH Connect] 检测到系统从休眠唤醒，正在重新连接…\n")
        if self.connect_button.isChecked():
            self._bounce_connection()
        else:
            self.connect_button.setChecked(True)
```

替换为：

```python
    def _suppress_reconnect(self):
        """休眠/锁屏统一抑制：取消退避重连、清在途 bounce、停看门狗。

        看门狗会在下次连接拿到 Client IP 时自动重启（handle_output）。
        """
        self.reconnect_manager.cancel()
        self._watchdog.stop()
        self._bounce_pending = False

    def _on_system_sleep(self):
        """系统休眠：抑制一切在途重连，避免盒盖期间无人应答的授权框。"""
        from utils import diagnostics

        self._suppress_reconnect()
        diagnostics.append("系统休眠：已取消在途重连并暂停看门狗")

    def _on_screen_sleep(self):
        """屏幕休眠（锁屏）：同系统休眠，抑制在途重连。"""
        from utils import diagnostics

        self._suppress_reconnect()
        diagnostics.append("屏幕休眠（锁屏）：已取消在途重连并暂停看门狗")

    def _on_system_wake(self):
        self._recover_connection("系统唤醒")

    def _on_screen_wake(self):
        self._recover_connection("屏幕唤醒")

    def _recover_connection(self, reason: str):
        """唤醒/解锁恢复：处于"应连接"态则立即重连（防重入 + 5s 防抖）。

        系统唤醒与屏幕唤醒在开盖时会先后触发，防抖确保只恢复一次；
        自动重连开关关闭、手动断开、认证失败、无凭据时一律跳过（落诊断日志）。
        """
        import time

        from utils import diagnostics

        now = time.monotonic()
        if self._bounce_pending:
            diagnostics.append(f"{reason}：已有在途重连，忽略")
            return
        if now - self._last_recover_ts < 5:
            diagnostics.append(f"{reason}：距上次恢复不足 5s，忽略")
            return
        if not self.auto_reconnect:
            diagnostics.append(f"{reason}：自动重连已关闭，跳过")
            return
        if self._manual_stop or self._auth_failed:
            diagnostics.append(f"{reason}：手动断开或认证失败，跳过")
            return
        if not (self.username_input.text() and self.password_input.text()):
            diagnostics.append(f"{reason}：无凭据，跳过")
            return
        self._last_recover_ts = now
        self.output_text.append(f"[BITZH Connect] 检测到{reason}，正在重新连接…\n")
        diagnostics.append(f"{reason}：恢复连接")
        if self.connect_button.isChecked():
            self._bounce_connection()
        else:
            self.connect_button.setChecked(True)
```

- [ ] **Step 5: 实现——sleep_wake.py 增加屏幕通知**

把 `app/utils/sleep_wake.py` 的 `_Observer` 类中，`onWake_` 定义之后：

```python
            def onWake_(self, notification):
                self._window._on_system_wake()

            onWake_ = objc.selector(onWake_, signature=b"v@:@")
```

后面追加：

```python
            def onScreenSleep_(self, notification):
                self._window._on_screen_sleep()

            onScreenSleep_ = objc.selector(onScreenSleep_, signature=b"v@:@")

            def onScreenWake_(self, notification):
                self._window._on_screen_wake()

            onScreenWake_ = objc.selector(onScreenWake_, signature=b"v@:@")
```

再把注册段：

```python
        center.addObserver_selector_name_object_(
            observer, "onWake:", "NSWorkspaceDidWakeNotification", None
        )
```

改为：

```python
        center.addObserver_selector_name_object_(
            observer, "onWake:", "NSWorkspaceDidWakeNotification", None
        )
        center.addObserver_selector_name_object_(
            observer, "onScreenSleep:", "NSWorkspaceScreensDidSleepNotification", None
        )
        center.addObserver_selector_name_object_(
            observer, "onScreenWake:", "NSWorkspaceScreensDidWakeNotification", None
        )
```

再把失败分支：

```python
    except Exception:
        return False
```

改为：

```python
    except Exception as exc:
        try:
            from . import diagnostics

            diagnostics.append(f"休眠/唤醒监听安装失败：{exc!r}")
        except Exception:
            pass
        return False
```

- [ ] **Step 6: 运行新测试确认通过**

Run: `uv run pytest tests/test_main_window.py -k "recover_connection or screen_sleep_suppresses" -v`
Expected: PASS

- [ ] **Step 7: 更新既有测试的消息断言**

`test_wake_noop_when_manually_disconnected`（约 162-167 行）中，把：

```python
    assert "休眠唤醒" not in window.output_text.toPlainText()
```

改为：

```python
    assert "正在重新连接" not in window.output_text.toPlainText()
```

- [ ] **Step 8: 跑全量测试**

Run: `uv run pytest -q`
Expected: 全部 PASS

- [ ] **Step 9: Commit**

```bash
git add app/views/main_window.py app/utils/sleep_wake.py tests/test_main_window.py
git commit -m "feat(sleep): 新增锁屏休眠/唤醒监听，统一带防抖的唤醒恢复入口"
```

---

## Task 3: 真机手测（macOS）

**Files:** 无代码改动

- [ ] **Step 1: 启动应用前置检查**

确认已关闭其它 TUN 客户端（FlClash 等），确认特权服务已安装（TUN 重连弹窗少）。
启动：`uv run python app/main.py`
诊断日志：`tail -f ~/Library/Logs/"BITZH Connect"/bitzh-connect.log`

- [ ] **Step 2: 合盖休眠 → 开盖**

连接成功后合盖约 30s 再开盖。预期：
- 日志出现 `系统休眠：已取消在途重连并暂停看门狗`
- 开盖后出现 `系统唤醒：恢复连接`（或 `系统唤醒：已有在途重连，忽略`），最终连接恢复为“已连接”
- 不应出现假的 `内核长时间无输出，判定疑似假死`（看门狗已在休眠时停掉）

- [ ] **Step 3: 锁屏 → 解锁**

连接成功后 `Ctrl+Cmd+Q` 锁屏约 1min 再解锁。预期：
- 日志出现 `屏幕休眠（锁屏）：已取消在途重连并暂停看门狗`
- 解锁后出现 `屏幕唤醒：恢复连接`，连接恢复

- [ ] **Step 4: 内核假死自愈（回归）**

连接成功后在另一终端 `kill -STOP <zju-connect pid>`（或断网 15s）。预期：
- 日志出现 `内核长时间无输出，判定疑似假死，自动重连`
- 随后应真正出现 `连接开始`（本次修复后不再缺失），连接恢复

- [ ] **Step 5: 锁屏/休眠期间无授权框**

未安装 helper 的情况下重复 Step 2/3，确认休眠/锁屏期间不会弹出“允许访问网络/授权”系统框（由 `_suppress_reconnect` 保证）。

- [ ] **Step 6: 手动断开不受影响**

手动断开后合盖/锁屏再开盖解锁，确认**不会**自作主张重连（`_manual_stop` 守卫）。

- [ ] **Step 7: 记录结果**

在手测全部通过后，回填本文件末尾的“手测记录”，并提交：

```bash
git add docs/superpowers/plans/2026-09-29-sleep-wake-reconnect.md
git commit -m "docs(plan): 记录休眠/锁屏重连真机手测结果"
```

---

## 手测记录

| 场景 | 结果 | 备注（日志时间戳） |
| --- | --- | --- |
| 合盖→开盖 | 待填 | |
| 锁屏→解锁 | 待填 | |
| 内核假死自愈 | 待填 | |
| 休眠期无授权框 | 待填 | |
| 手动断开不重连 | 待填 | |

---

## Self-Review

**Spec coverage（对照 Q1–Q12 决策）**
- Q1a bounce 事件驱动 → Task 1
- Q2a 屏幕唤醒=整机唤醒 → Task 2 `_recover_connection` 的 `if isChecked(): bounce else setChecked(True)`
- Q3a 锁屏取消在途重连 → Task 2 `_on_screen_sleep` → `_suppress_reconnect`
- Q4a/防抖 5s → Task 2 `_recover_connection` 的 `_last_recover_ts`
- Q5a 全事件落诊断日志 → Task 2 各钩子 `diagnostics.append`
- Q6a 睡/锁停看门狗 → Task 2 `_suppress_reconnect`
- Q7a/Q10a 安装失败落日志 → Task 2 Step 5 `except` 分支
- Q9a 受 auto_reconnect 约束 → Task 2 `_recover_connection`
- Q11a 删 `_asleep` → Task 2 Step 4 替换整段后 `_asleep` 不再出现
- Q12a 睡/锁清 `_bounce_pending` → Task 2 `_suppress_reconnect`
- Q8a 单测 + 真机清单 → Task 1/2 单测 + Task 3

**Placeholder scan**：无 TBD/TODO；所有代码步骤均给出完整替换内容。

**Type consistency**：`_maybe_finish_bounce()`（无参）、`_recover_connection(reason: str)`、`_suppress_reconnect()`、`_on_screen_sleep/_on_screen_wake` 命名在实现、sleep_wake 桥、测试中一致。
