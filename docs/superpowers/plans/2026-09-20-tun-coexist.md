# TUN 共存模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本软件 TUN 与 FlClash/Clash 的 TUN 同时运行：他方 TUN 管外网，本软件只加校园明细路由，并把内核底层连接绑到物理网卡以免被对方截走。

**Architecture:** 用「服务器 IP 的路由出口是否为 utun」取代旧的「默认路由是否为 utun」判据（后者对 FlClash 无效）；命中时探测主物理网卡，给 `zju-connect` 传 `-bind-interface`，硬件层绕过对方路由；删除硬拦截，改为日志提示。

**Tech Stack:** Python 3.11 / PySide6 / pytest；macOS `route`、`scutil --nwi`；Linux `ip route`。

**Spec:** `docs/superpowers/specs/2026-09-20-tun-coexist-design.md`

---

## File Structure

- `app/utils/tun_utils.py` — 新增纯解析器 + 探测函数；删除 `check_tun_conflict`
- `app/utils/connection_utils.py` — `build_command_args` 增加绑定参数；`start_connection` 共存路径
- `app/views/advanced_panel.py` — TUN 说明文案
- `README.md` — TUN 互斥说明改共存
- `tests/test_tun_utils.py` — 解析器/探测函数单测；删除旧检测用例
- `tests/test_connection_args.py` — `-bind-interface` 参数单测
- `tests/test_connection_flow.py` — 共存路径不早退；旧用例桩改名

---

## Task 1: tun_utils 探测函数

**Files:**
- Modify: `app/utils/tun_utils.py`
- Test: `tests/test_tun_utils.py`

- [ ] **Step 1: 写失败测试（解析器 + 探测函数）**

在 `tests/test_tun_utils.py` 末尾追加：

```python
def test_parse_route_get_interface():
    import utils.tun_utils as tu

    text = (
        "   route to: 112.91.150.228\n"
        "destination: 112.91.150.228\n"
        "       mask: 255.255.255.255\n"
        "  interface: utun5\n"
    )
    assert tu._parse_route_get_interface(text) == "utun5"
    assert tu._parse_route_get_interface("no interface line") is None


def test_parse_scutil_nwi():
    import utils.tun_utils as tu

    text = (
        "Network information\n\n"
        "IPv4 network interface information\n"
        "     en0 : flags      : 0x7 (IPv4,IPv6,DNS)\n"
        "Network interfaces: en0\n"
    )
    assert tu._parse_scutil_nwi(text) == "en0"
    assert tu._parse_scutil_nwi("nothing here") is None


def test_parse_ip_route_dev():
    import utils.tun_utils as tu

    assert (
        tu._parse_ip_route_dev("1.1.1.1 via 10.0.0.1 dev en0 src 10.0.0.2")
        == "en0"
    )
    assert tu._parse_ip_route_dev("no dev token") is None


def test_capturing_tun_for_darwin_hits_tun(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "   route to: 112.91.150.228\n  interface: utun5\n",
    )
    assert tu.capturing_tun_for("112.91.150.228") == "utun5"


def test_capturing_tun_for_physical_is_none(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "   route to: 1.1.1.1\n  interface: en0\n",
    )
    assert tu.capturing_tun_for("1.1.1.1") is None


def test_capturing_tun_for_linux(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Linux")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "112.91.150.228 via 10.0.0.1 dev tun0 src 10.0.0.2\n",
    )
    assert tu.capturing_tun_for("112.91.150.228") == "tun0"


def test_capturing_tun_for_error_is_none(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")

    def boom(*a, **k):
        raise FileNotFoundError("route")

    monkeypatch.setattr(tu.subprocess, "check_output", boom)
    assert tu.capturing_tun_for("112.91.150.228") is None


def test_physical_interface_darwin(monkeypatch):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")
    monkeypatch.setattr(
        tu.subprocess, "check_output",
        lambda *a, **k: "IPv4 network interface information\nNetwork interfaces: en0\n",
    )
    assert tu.physical_interface() == "en0"


def test_physical_interface_excludes_tun_and_falls_back(monkeypatch):
    """nwi 只报 tun（异常）→ 回退默认路由出口；且 utun 出口不被采纳"""
    import utils.tun_utils as tu

    monkeypatch.setattr(tu, "system", lambda: "Darwin")

    def fake(cmd, *a, **k):
        if cmd[0] == "scutil":
            return "Network interfaces: utun5\n"
        return "   route to: default\n  interface: en0\n"

    monkeypatch.setattr(tu.subprocess, "check_output", fake)
    assert tu.physical_interface() == "en0"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_tun_utils.py -q -k "parse or capturing or physical"`
Expected: FAIL（`AttributeError: module 'utils.tun_utils' has no attribute '_parse_route_get_interface'` 等）

- [ ] **Step 3: 写最小实现**

在 `app/utils/tun_utils.py` 的 `check_tun_conflict` **之前**插入以下内容（保留 `check_tun_conflict`，Task 2 再删）：

```python
def _parse_route_get_interface(text: str) -> str | None:
    """从 `route -n get <ip>` 输出里取 interface（macOS）。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("interface:"):
            return stripped.split(":", 1)[1].strip() or None
    return None


def _parse_scutil_nwi(text: str) -> str | None:
    """从 `scutil --nwi` 输出取主网卡（"Network interfaces: en0, en1"）。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Network interfaces:"):
            names = stripped.split(":", 1)[1].replace(",", " ").split()
            return names[0] if names else None
    return None


def _parse_ip_route_dev(text: str) -> str | None:
    """从 `ip route` 输出取 `dev <iface>`（Linux）。"""
    parts = text.split()
    if "dev" in parts:
        idx = parts.index("dev")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def _is_tun_name(name: str) -> bool:
    return name.startswith(("utun", "tun"))


def capturing_tun_for(server_ip: str) -> str | None:
    """返回会把去 server_ip 的流量截进 TUN 的网卡名；无则 None。

    比"默认路由是否在 utun"更准：FlClash/mihomo 不抢默认路由，而是用一串
    明细路由（如 64.0.0.0/2）把服务器 IP 拐进自己的 utun。
    命令失败/解析失败安静返回 None（探测失败不该阻断连接）。
    """
    try:
        if system() == "Darwin":
            out = subprocess.check_output(
                ["route", "-n", "get", server_ip],
                text=True, stderr=subprocess.DEVNULL,
            )
            dev = _parse_route_get_interface(out)
        elif system() == "Linux":
            out = subprocess.check_output(
                ["ip", "route", "get", server_ip],
                text=True, stderr=subprocess.DEVNULL,
            )
            dev = _parse_ip_route_dev(out)
        else:
            return None
        return dev if dev and _is_tun_name(dev) else None
    except Exception:
        return None


def physical_interface() -> str | None:
    """主物理网卡名；macOS 用 scutil --nwi，失败回退默认路由出口；排除 TUN。"""
    try:
        if system() == "Darwin":
            out = subprocess.check_output(
                ["scutil", "--nwi"], text=True, stderr=subprocess.DEVNULL
            )
            name = _parse_scutil_nwi(out)
            if name and not _is_tun_name(name):
                return name
            out = subprocess.check_output(
                ["route", "-n", "get", "default"],
                text=True, stderr=subprocess.DEVNULL,
            )
            name = _parse_route_get_interface(out)
        elif system() == "Linux":
            out = subprocess.check_output(
                ["ip", "route", "show", "default"],
                text=True, stderr=subprocess.DEVNULL,
            )
            name = _parse_ip_route_dev(out)
        else:
            return None
        return name if name and not _is_tun_name(name) else None
    except Exception:
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tun_utils.py -q`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add app/utils/tun_utils.py tests/test_tun_utils.py
git commit -m "feat(tun): 新增服务器路由出口/物理网卡探测（共存模式基础）"
```

---

## Task 2: connection_utils 共存路径

**Files:**
- Modify: `app/utils/tun_utils.py`（删 `check_tun_conflict`）
- Modify: `app/utils/connection_utils.py`
- Test: `tests/test_connection_args.py`、`tests/test_connection_flow.py`、`tests/test_tun_utils.py`

- [ ] **Step 1: 写失败测试 — build_command_args 参数**

在 `tests/test_connection_args.py` 末尾追加：

```python
def test_tun_bind_interface_appended_when_present():
    args = build_command_args(_fake_window(tun_mode=True), "zju-connect", "en0")
    assert "-bind-interface" in args
    assert args[args.index("-bind-interface") + 1] == "en0"


def test_tun_bind_interface_absent_by_default():
    args = build_command_args(_fake_window(tun_mode=True), "zju-connect")
    assert "-bind-interface" not in args
```

- [ ] **Step 2: 写失败测试 — start_connection 共存不早退**

在 `tests/test_connection_flow.py` 中，把 `test_tun_conflict_aborts_before_spawn`
整体替换为：

```python
def test_tun_coexist_binds_physical_interface_no_abort(qtbot, monkeypatch):
    """TUN 共存：他方 TUN 截走服务器路由时，底层绑定物理网卡并继续（不再早退）"""
    import utils.connection_utils as cu

    win = _make_window(qtbot)
    win.username_input.setText("u")
    win.password_input.setText("p")
    win.tun_mode = True
    monkeypatch.setattr("utils.connection_utils.capturing_tun_for", lambda ip: "utun9")
    monkeypatch.setattr("utils.connection_utils.physical_interface", lambda: "en0")
    monkeypatch.setattr(
        "utils.connection_utils.spawn_elevated_async", lambda *a, **k: None
    )
    seen = {}
    real = cu.build_command_args

    def spy(window, command, tun_bind_interface=None):
        seen["bind"] = tun_bind_interface
        return real(window, command, tun_bind_interface)

    monkeypatch.setattr("utils.connection_utils.build_command_args", spy)

    win.connect_button.setChecked(True)

    assert seen["bind"] == "en0"          # 绑定参数已传到参数构建
    assert win.worker is not None          # 未早退
    assert "共存模式" in win.output_text.toPlainText()

    win.connect_button.setChecked(False)   # 收尾，避免残留 worker
    qtbot.waitUntil(lambda: win.worker is None, timeout=3000)
```

并把 `test_stale_spawn_done_stops_orphan_kernel` 里的：
`monkeypatch.setattr("utils.connection_utils.check_tun_conflict", lambda: None)`
改为：
`monkeypatch.setattr("utils.connection_utils.capturing_tun_for", lambda ip: None)`

同时删除 `tests/test_tun_utils.py` 里的 `test_linux_tun_conflict_detects_tun_default_route`
（`check_tun_conflict` 即将删除）。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_connection_args.py tests/test_connection_flow.py -q -k "bind or coexist"`
Expected: FAIL（`-bind-interface` 未加 / `capturing_tun_for` 未定义 / 早退）

- [ ] **Step 4: 实现 — tun_utils 删除旧检测**

从 `app/utils/tun_utils.py` 删除整个 `check_tun_conflict` 函数（含其 docstring），
并删除文件顶部不再使用的 `netstat`/`Linux ip route 默认路由` 相关注释（函数整体删掉即可）。

- [ ] **Step 5: 实现 — connection_utils import 与参数**

把 `app/utils/connection_utils.py` 顶部：

```python
from .tun_utils import (
    check_tun_conflict,
    write_launcher,
    spawn_elevated_async,
    request_stop,
)
```

改为：

```python
from .tun_utils import (
    capturing_tun_for,
    physical_interface,
    write_launcher,
    spawn_elevated_async,
    request_stop,
)
```

把 `build_command_args` 签名与 TUN 分支：

```python
def build_command_args(window, command, tun_bind_interface=None):
```

```python
    if getattr(window, "tun_mode", False):
        command_args.append("-tun-mode")
        command_args.append("-add-route")
        if tun_bind_interface:
            command_args.extend(["-bind-interface", tun_bind_interface])
```

- [ ] **Step 6: 实现 — start_connection 共存探测**

把 `app/utils/connection_utils.py` 中：

```python
    command_args = build_command_args(window, command)
    window.output_text.append(f"Running command: {' '.join(mask_command_args(command_args))}\n")

    if getattr(window, "tun_mode", False):
        # 纵深防御：面板开关在 Windows 已置灰，此处硬守卫防编程绕过（.bat 链路本期未验证）
        if system() == "Windows":
            _reset_connect_ui(window, "本期暂不支持 Windows TUN")
            return
        conflict = check_tun_conflict()
        if conflict:
            window.output_text.append(
                f"[BITZH Connect] 检测到默认路由已在虚拟网卡 {conflict}（如 Clash TUN），请先关闭再连\n"
            )
            _reset_connect_ui(window, f"与 {conflict} 的 TUN 冲突")
            return
```

替换为：

```python
    # 共存模式：他方 TUN（Clash/FlClash）常不抢默认路由，而是用明细路由把 VPN
    # 服务器 IP 截进自己的 utun——此时把内核底层连接显式绑到物理网卡，硬件层绕过
    # 对方路由，两 TUN 各管各的。探测不到物理网卡则告警但仍继续（不阻断连接）。
    tun_bind_interface = None
    if getattr(window, "tun_mode", False) and system() != "Windows":
        captured = capturing_tun_for(window.server_address)
        if captured:
            tun_bind_interface = physical_interface()
            if tun_bind_interface:
                window.output_text.append(
                    f"[BITZH Connect] 检测到 {captured} 占用服务器路由，已启用共存模式"
                    f"（底层绑定 {tun_bind_interface}）\n"
                )
            else:
                window.output_text.append(
                    f"[BITZH Connect] 检测到 {captured} 占用服务器路由，但未识别到物理网卡；"
                    f"若连不上请先关闭 {captured}\n"
                )

    command_args = build_command_args(window, command, tun_bind_interface)
    window.output_text.append(f"Running command: {' '.join(mask_command_args(command_args))}\n")

    if getattr(window, "tun_mode", False):
        # 纵深防御：面板开关在 Windows 已置灰，此处硬守卫防编程绕过（.bat 链路本期未验证）
        if system() == "Windows":
            _reset_connect_ui(window, "本期暂不支持 Windows TUN")
            return
```

（其后的 `import tempfile` 等保持不变。）

- [ ] **Step 7: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_connection_args.py tests/test_connection_flow.py tests/test_tun_utils.py -q`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app/utils/connection_utils.py app/utils/tun_utils.py tests/test_connection_args.py tests/test_connection_flow.py tests/test_tun_utils.py
git commit -m "feat(tun): 共存模式——服务器路由被他方 TUN 截走时底层绑定物理网卡，放开硬拦"
```

---

## Task 3: 文案与文档

**Files:**
- Modify: `app/views/advanced_panel.py`
- Modify: `README.md`

- [ ] **Step 1: 改高级设置文案**

`app/views/advanced_panel.py` 中：

```python
        tun_note = "所有流量（含 SSH 等裸 TCP）都走 VPN，默认开启；需要管理员授权；与 Clash TUN 模式互斥"
```

改为：

```python
        tun_note = (
            "所有流量（含 SSH 等裸 TCP）都走 VPN，默认开启；需要管理员授权；"
            "可与 Clash/FlClash 的 TUN 共存（按 IP 直连校园网；对方需未开启严格路由）"
        )
```

- [ ] **Step 2: 改 README**

`README.md` §TUN 模式 NOTE 第 2 条：

```markdown
> 2. TUN 模式与 Clash 的 TUN 模式互斥，二者只能开启其一
```

改为：

```markdown
> 2. 可与 Clash/FlClash 的 TUN 模式共存：本软件只加校园网明细路由，外网交给对方；
>    检测到去 VPN 服务器的流量会被对方 TUN 截走时，会自动把内核底层连接绑定到物理网卡绕过
>    （按 IP 直连校园网；对方开启「严格路由/strict-route」时仍需先关闭）
```

- [ ] **Step 3: 提交**

```bash
git add app/views/advanced_panel.py README.md
git commit -m "docs: TUN 说明改为可与其他 TUN 共存"
```

---

## Task 4: 全量测试 + 真机验证

- [ ] **Step 1: 全量单测**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部通过（213 + 新增）

- [ ] **Step 2: 真机验证（人工，需 FlClash 已开 TUN）**

前置：确认 FlClash TUN 开启；确认 `route -n get 112.91.150.228` 落在 `utun*`。

```bash
# 1) 启动本软件并连接（TUN 模式默认开）
cd /Users/jerry/Projects/hitsz-connect-verge
source .venv/bin/activate && uv run app/main.py
# 输入凭据 → 连接（会弹一次管理员授权）
```

在弹出的日志里确认出现：`已启用共存模式（底层绑定 en0）`。

```bash
# 2) 校园内网可达（VPN 服务器所在校内主机）
ssh czr@10.8.18.32

# 3) 校园网段明细路由落在本软件 utun
route -n get 10.8.18.32        # 期望 interface: <本软件 utun>

# 4) 外网仍走 FlClash
curl -sS -o /dev/null -w '%{http_code}\n' https://www.google.com

# 5) 断开后校园路由回收
route -n get 10.8.18.32        # 期望不再指向本软件 utun
```

Expected：ssh 可达；google 返回 200；断开后路由回收干净。

- [ ] **Step 3: 记录真机结论**

把实测结论（物理网卡名、命中的他方 TUN、ssh 结果）回填到 spec 的修订记录。

- [ ] **Step 4: 提交文档修订**

```bash
git add docs/superpowers/specs/2026-09-20-tun-coexist-design.md
git commit -m "docs: 回填 TUN 共存真机验证结论"
```

---

## Self-Review

- **Spec coverage**：判据替换（Task 1/2）、物理网卡探测（Task 1）、`-bind-interface`（Task 2）、
  放开硬拦（Task 2）、文案/README（Task 3）、测试（Task 1/2/4）、IP 直连真机（Task 4）——全覆盖。
- **Placeholder scan**：无 TBD/TODO；所有代码步骤含完整代码。
- **Type consistency**：`capturing_tun_for(server_ip)`、`physical_interface()`、
  `build_command_args(window, command, tun_bind_interface=None)` 在测试与实现中签名一致；
  `_parse_route_get_interface` / `_parse_scutil_nwi` / `_parse_ip_route_dev` 前后一致。

---

## 追加任务（2026-09-20 真机反馈）

真机验证发现：app 被**非正常终止**（关终端 / Ctrl-C / 崩溃）时，root 内核与校园路由会残留
（要手动 `sudo pkill`）。正常点「断开」不受影响。追加两个任务自愈该问题。

### Task 5: 启动时清理孤儿内核

**Files:**
- Modify: `app/utils/tun_utils.py`
- Modify: `app/main.py`
- Test: `tests/test_tun_utils.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_tun_utils.py` 末尾追加：

```python
def test_sweep_orphan_tun_stops_live_kernel(monkeypatch, tmp_path):
    import os

    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    pid_file = tmp_path / "bitzh-tun-abcd1234.pid"
    pid_file.write_text(str(os.getpid()))
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: True)

    stopped = tu.sweep_orphan_tun()

    assert stopped == 1
    assert (tmp_path / "bitzh-tun-abcd1234.pid.stop").exists()


def test_sweep_orphan_tun_removes_dead(monkeypatch, tmp_path):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    pid_file = tmp_path / "bitzh-tun-deadbeef.pid"
    pid_file.write_text("99999999")
    stop_file = tmp_path / "bitzh-tun-deadbeef.pid.stop"
    stop_file.write_text("")
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: False)

    stopped = tu.sweep_orphan_tun()

    assert stopped == 0
    assert not pid_file.exists()
    assert not stop_file.exists()


def test_sweep_orphan_tun_removes_launcher_and_log(monkeypatch, tmp_path):
    import utils.tun_utils as tu

    monkeypatch.setattr(tu.tempfile, "gettempdir", lambda: str(tmp_path))
    sh = tmp_path / "bitzh-tun-launcher.sh"
    log = tmp_path / "bitzh-tun-session.log"
    sh.write_text("#!/bin/sh\n")
    log.write_text("log\n")
    monkeypatch.setattr(tu, "_pid_alive", lambda pid: False)

    tu.sweep_orphan_tun()

    assert not sh.exists()
    assert not log.exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tun_utils.py -q -k sweep`
Expected: FAIL（`AttributeError: module 'utils.tun_utils' has no attribute 'sweep_orphan_tun'`）

- [ ] **Step 3: 实现**

`app/utils/tun_utils.py` 顶部 `import os` 下方补 `import glob`；在 `request_stop` 之后插入：

```python
def sweep_orphan_tun() -> int:
    """清理异常退出残留的 TUN 内核与临时文件（启动时自愈）。

    正常断开时 app 会写停止标记、root 守护脚本收掉内核并清理临时文件；app 被强杀
    （关终端 / Ctrl-C / 崩溃）时内核与临时文件会残留。启动时：
    - pid 仍存活 → 写 .stop，交给仍在等待的 root 守护脚本收掉；
    - pid 已死 → 删掉残留的 pid/stop；
    - 删掉残留的 launcher 脚本与日志（脚本内嵌命令行含密码，必须清）。
    返回本次要求停止的内核数量。失败安静忽略（启动不应被清理问题阻断）。
    """
    stopped = 0
    tmp = tempfile.gettempdir()
    for pid_file in glob.glob(os.path.join(tmp, "bitzh-tun-*.pid")):
        pid = read_pid(pid_file)
        if pid is not None and _pid_alive(pid):
            request_stop(pid_file + ".stop")
            stopped += 1
        else:
            for suffix in ("", ".stop"):
                try:
                    os.remove(pid_file + suffix)
                except OSError:
                    pass
    for pattern in ("bitzh-tun-*.sh", "bitzh-tun-*.log"):
        for path in glob.glob(os.path.join(tmp, pattern)):
            try:
                os.remove(path)
            except OSError:
                pass
    return stopped
```

`app/main.py`：顶部 import 区加 `from utils.tun_utils import sweep_orphan_tun`；
`app = QApplication()` 之后、`window = MainWindow()` 之前插入：

```python
    # 启动自愈：清掉上次异常退出残留的 TUN 内核/临时文件（含内嵌密码的 launcher）
    sweep_orphan_tun()
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_tun_utils.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/utils/tun_utils.py app/main.py tests/test_tun_utils.py
git commit -m "feat(tun): 启动时清理异常退出残留的 TUN 内核与临时文件"
```

### Task 6: 退出信号处理

**Files:**
- Create: `app/utils/shutdown.py`
- Modify: `app/main.py`
- Test: `tests/test_shutdown.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_shutdown.py`：

```python
"""退出信号处理：SIGINT/SIGTERM/SIGHUP → 置标志，QTimer 轮询触发优雅退出。"""
import signal


def test_install_exit_signal_handlers_triggers_on_signal(qtbot):
    from utils.shutdown import install_exit_signal_handlers

    fired = []
    saved = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    timer = install_exit_signal_handlers(lambda: fired.append(True))
    try:
        signal.raise_signal(signal.SIGINT)
        qtbot.waitUntil(lambda: fired == [True], timeout=2000)
    finally:
        timer.stop()
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def test_install_exit_signal_handlers_survives_unsupported_signal(monkeypatch, qtbot):
    import utils.shutdown as sd

    def boom(sig, handler):
        raise ValueError("not main thread")

    monkeypatch.setattr(sd.signal, "signal", boom)
    timer = sd.install_exit_signal_handlers(lambda: None)
    timer.stop()  # 安装全失败也不崩、仍返回可用 timer
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_shutdown.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'utils.shutdown'`）

- [ ] **Step 3: 实现**

新建 `app/utils/shutdown.py`：

```python
# app/utils/shutdown.py
"""退出信号处理：把 SIGINT/SIGTERM/SIGHUP 转成一次优雅退出（走 window.quit_app）。

Qt 的 C++ 事件循环不会即时执行 Python 信号处理器——处理器只置标志，由 QTimer
轮询在事件循环里触发回调（200ms 延迟换实现简单，退出路径不敏感）。
"""
import signal

from PySide6.QtCore import QTimer

_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def install_exit_signal_handlers(on_signal, parent=None) -> QTimer:
    """安装退出信号处理器，返回需保活的 QTimer（挂 parent 上随其生命周期）。

    on_signal 在事件循环里触发（可重入性由调用方 quit_app 自身保证）。
    非主线程/平台不支持的信号安装失败时安静跳过。
    """
    state = {"fired": False}

    def _handler(_signum, _frame):
        state["fired"] = True

    for sig in _SIGNALS:
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass

    timer = QTimer(parent)
    timer.setInterval(200)

    def _poll():
        if state["fired"]:
            timer.stop()
            on_signal()

    timer.timeout.connect(_poll)
    timer.start()
    return timer
```

`app/main.py`：顶部加 `from utils.shutdown import install_exit_signal_handlers`；
`window = MainWindow()` 之后插入（`_exit_timer` 全局存活，parent=window 兜底）：

```python
    # 关闭终端/Ctrl-C/kill 时走一次优雅退出（写停止标记、收掉 root 内核）
    _exit_timer = install_exit_signal_handlers(window.quit_app, parent=window)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_shutdown.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/utils/shutdown.py app/main.py tests/test_shutdown.py
git commit -m "feat: 退出信号（SIGINT/SIGTERM/SIGHUP）走优雅退出，避免 TUN 内核孤儿"
```

### Task 7: 追加验证（全量 + 真机）

- [ ] **Step 1: 全量单测**：`.venv/bin/python -m pytest -q` → 全绿。
- [ ] **Step 2: 真机**：
  1. 先确保无残留：`pgrep -fl zju-connect`（无输出）；
  2. 启动 app、连接（FlClash TUN 开）；
  3. **直接 Ctrl-C / 关终端**（不走「断开」）；
  4. 重新启动 app → 应自动把上次残留的内核收掉（日志/进程验证），`route -n get 10.8.18.32` 先残留再由 sweep 清掉。
  5. 再测一次信号：连接后 `kill <app_pid>`（SIGTERM）→ 内核与路由应被回收。
- [ ] **Step 3: 回填 spec 结论（见 spec §8）。**
