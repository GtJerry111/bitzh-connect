# BITZH Connect 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 hitsz-connect-verge 二次开发 BITZH 版 EasyConnect 客户端（BITZH Connect），修复上游已知 bug，新增自动重连与状态仪表盘，三平台（Windows/macOS/Linux）小范围分发。

**Architecture:** PySide6 GUI 壳 + zju-connect Go 内核（CI 时下载 v1.3.1，GUI 不含协议逻辑）。默认代理模式（SOCKS5:1080 / HTTP:1081，无权限要求），TUN 模式不在本期范围。GUI 通过解析内核输出获取虚拟 IP / 认证失败等状态，重连逻辑在 GUI 层以状态机实现。

**Tech Stack:** Python 3.11 + PySide6 + uv；keyring（凭据存储）；pytest + pytest-qt（无头测试，QT_QPA_PLATFORM=offscreen）；Nuitka 打包；GitHub Actions CI。

**已锁定的需求决策（grilling 结论）：**

| # | 决策 | 结论 |
|---|---|---|
| 1 | 受众 | 自己 + 小范围同学，三平台，不做代码签名 |
| 2 | 网络模式 | 默认代理模式，TUN 可选（本期不做，见文末"后续阶段"） |
| 3 | 自动重连 | 默认开启；认证失败/手动断开不重连；退避 5s→10s→30s；连续失败 3 次暂停；连接稳定 60s 后重置计数 |
| 4 | UI | 重设计为状态仪表盘（状态/时长/虚拟IP/速率），日志折叠；代理模式速率显示 `—` |
| 5 | 仓库 | 公开 fork，命名 **BITZH Connect**，更新检查指向自己 fork，保留上游致谢 |
| 6 | 凭据 | keyring 库存系统钥匙串；Linux 无后端时回退 QSettings 明文并告警 |
| 7 | 服务器 | 默认 `112.91.150.228:443`（已验证为标准 EasyConnect 服务器） |
| 8 | 登录方式 | 仅账号密码，无需验证码 UI |
| 9 | UI/动效 | 遵循 Apple 流体界面原则：语义色深浅色自适应；非手势状态切换用 250ms OutCubic 过渡（无动量场景不用弹性）；动画可打断（从当前展示值重启）；尊重系统"减少动态效果"；内联校验（凭据不全禁用连接按钮）；时长/速率数字表格化防抖动 |

**设计取舍（Simplicity 原则，明确不做）：** 不做毛玻璃背景（小窗口收益低、Qt Widgets 与 NSVisualEffectView 混排风险高）、不加音效、连接成功无弹跳动效（无动量输入，弹跳是错误的）。质感靠色彩、字距、留白、对齐实现。

**本期明确不做（避免范围蔓延）：**
- TUN 模式（提权方案 + wintun.dll 打包 + 网卡流量统计，另立计划）
- 图形验证码 / 短信 / TOTP 界面
- 代码签名与公证
- fork zju-connect Go 内核（代理模式速率统计依赖它，已确认接受降级）

---

## 背景：上游 bug 清单（本计划修复对象）

| # | Bug | 位置 | 修复任务 |
|---|---|---|---|
| B1 | `shlex.quote` 导致含 `!`、空格、`$` 等特殊字符的密码被裹上字面单引号传给内核 → 认证失败 | `connection_utils.py` | Task 2 |
| B2 | 密码明文存 QSettings | `credential_utils.py` | Task 6 |
| B3 | 无自动重连 | `connection_utils.py` | Task 4+5 |
| B4 | 强杀 app 后系统代理残留 → 全网断连 | `set_proxy.py` | Task 5 |
| B5 | `stop_connection` 在 GUI 线程 `worker.wait()`，断开时卡 UI | `connection_utils.py` | Task 5 |
| B6 | macOS `get_launch_at_login` 用二进制名匹配登录项名，打包后检测失效 | `startup_utils.py` | Task 9 |
| B7 | 更新检查先 start 后连信号，存在竞态丢信号；worker 无引用可能被 GC | `update_service.py` | Task 9 |
| B8 | `-zju-dns-server` 参数名已弃用（新名 `-remote-dns-server`） | `connection_utils.py` | Task 2 |
| B9 | 日志框无上限增长 | `main_window.py` | Task 8 |
| B10 | 托盘菜单"系统代理"文案名不副实（实为连接开关） | `tray_utils.py` | Task 9 |
| B11 | `connect_startup` 不校验已存凭据，空密码也去连 | `main_window.py` | Task 8 |
| B12 | `version.py` 读资源失败时返回 None | `common/version.py` | Task 9 |

## 文件结构

**新增：**
- `app/common/constants.py` — 品牌/仓库/默认服务器常量（单一事实源）
- `app/common/theme.py` — 语义化设计 tokens（BIT 品牌色、深浅色自适应、字体层级）
- `app/utils/motion_utils.py` — 动效工具（减少动态效果检测、可打断的颜色/展开动画）
- `app/utils/log_parser.py` — 解析 zju-connect 输出的纯函数（虚拟 IP、认证失败、服务器踢人）
- `app/services/reconnect_manager.py` — 自动重连状态机（QObject）
- `app/utils/credential_store.py` — keyring 凭据存取（可注入后端）
- `app/views/status_panel.py` — 状态仪表盘组件
- `app/views/busy_spinner.py` — 连接中旋转弧指示器
- `tests/conftest.py`、`tests/test_log_parser.py`、`tests/test_reconnect_manager.py`、`tests/test_credential_store.py`、`tests/test_connection_args.py`、`tests/test_theme.py`、`tests/test_status_panel.py`、`tests/test_main_window.py`

**修改：**
- `app/utils/connection_utils.py` — 删 shlex.quote、换参数名、接重连、异步停止
- `app/utils/set_proxy.py` — worker finished 带退出码、非阻塞 stop、代理残留清理
- `app/utils/config_utils.py` — QSettings 换名、默认值、新增 `auto_reconnect` 键
- `app/utils/credential_utils.py` — 改走 credential_store
- `app/views/main_window.py` — 仪表盘集成、折叠日志、凭据校验
- `app/views/advanced_panel.py` — 默认值、自动重连开关
- `app/views/menu_utils.py` — 关于页、更新 URL 走 constants
- `app/services/update_service.py` — 竞态修复
- `app/utils/startup_utils.py` — macOS 登录项检测修复
- `app/utils/tray_utils.py` — 托盘文案
- `app/common/version.py` — 兜底返回 "0.0.0"
- `pyproject.toml` — 改名、加 keyring、dev 依赖
- `.app-version` → `1.0.0`
- `.github/workflows/release.yml` — 内核 v1.3.1、产物改名
- `setup.iss` — 改名、新 AppId GUID
- `README.md` / `README.zh-CN.md` — BITZH 化

---

### Task 1: 品牌换皮与测试基建

**Files:**
- Create: `app/common/constants.py`
- Modify: `pyproject.toml`
- Modify: `.app-version`
- Modify: `app/utils/config_utils.py`
- Modify: `app/views/main_window.py`（仅标题）
- Create: `tests/conftest.py`
- Modify: `app/views/menu_utils.py`、`app/services/update_service.py`（URL 走 constants）

- [ ] **Step 1: fork 仓库准备**

在本机把 origin 指向自己的 fork（grilling 已确认：GitHub 账号 `GtJerry111`，gh CLI 已登录且 token 有 repo/workflow 权限，可直接建 fork）：

```bash
gh repo fork kowyo/hitsz-connect-verge --fork-name bitzh-connect --clone=false
git remote rename origin upstream
git remote add origin https://github.com/GtJerry111/bitzh-connect.git
```

- [ ] **Step 2: 创建 constants.py**

```python
# app/common/constants.py
"""BITZH Connect 全局常量（单一事实源）：品牌、仓库、默认服务器。"""

APP_NAME = "BITZH Connect"
ORG_NAME = "BITZH Connect"

# GitHub fork 信息：更新检查与"关于"页链接都从这里取（grilling 已确认账号）
REPO_OWNER = "GtJerry111"
REPO_NAME = "bitzh-connect"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
UPDATE_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
RELEASES_URL = f"{REPO_URL}/releases/latest"

# BITZH VPN 默认服务器（已验证为标准深信服 EasyConnect）
DEFAULT_SERVER = "112.91.150.228"
DEFAULT_PORT = "443"
DEFAULT_DNS = ""  # 留空即可：默认开启 auto_dns 从服务端获取
```

**执行前置：** 无（`REPO_OWNER` 已锁定为 `GtJerry111`）。

- [ ] **Step 3: config_utils.py 换 QSettings 名与默认值**

`app/utils/config_utils.py` 中：

```python
from PySide6.QtCore import QSettings
from common.constants import APP_NAME, ORG_NAME, DEFAULT_SERVER, DEFAULT_PORT, DEFAULT_DNS
from .startup_utils import get_launch_at_login


def save_config(config):
    """Save config using QSettings"""
    settings = QSettings(ORG_NAME, APP_NAME)
    for key, value in config.items():
        settings.setValue(key, value)
    settings.sync()


def load_config():
    """Load config from QSettings"""
    settings = QSettings(ORG_NAME, APP_NAME)
    default_config = {
        "username": "",
        "password": "",
        "remember": False,
        "server": DEFAULT_SERVER,
        "port": DEFAULT_PORT,
        "dns": DEFAULT_DNS,
        "auto_dns": True,
        "proxy": True,
        "launch_at_login": get_launch_at_login(),
        "connect_startup": False,
        "silent_mode": False,
        "check_update": True,
        "hide_dock_icon": False,
        "keep_alive": True,
        "debug_dump": False,
        "disable_multi_line": False,
        "auto_reconnect": True,
        "socks_bind": "1080",
        "http_bind": "1081",
        "cert_file": "",
        "cert_password": "",
    }

    for key in default_config.keys():
        value = settings.value(key, default_config[key])
        if isinstance(default_config[key], bool):
            value = str(value).lower() == "true"
        default_config[key] = value

    return default_config
```

`load_settings(self)` 末尾追加一行：

```python
    self.auto_reconnect = config["auto_reconnect"]
```

- [ ] **Step 4: main_window.py 标题换名**

```python
from common.constants import APP_NAME
...
        self.setWindowTitle(APP_NAME)
```

- [ ] **Step 5: menu_utils.py 关于页与更新 URL 走 constants**

`show_about` 中替换 about_text（保留对上游致谢）：

```python
from common.constants import APP_NAME, REPO_URL
...
    about_text = f"""<p style="font-size: 15pt;">{APP_NAME}</p>
    <p style="font-size: 10pt;">Version: {version}</p>
    <p style="font-size: 10pt;">Repository: <a href="{REPO_URL}">{REPO_URL.replace("https://", "")}</a></p>
    <p style="font-size: 10pt;">Based on <a href="https://github.com/kowyo/hitsz-connect-verge">HITSZ Connect Verge</a> by Kowyo,
    powered by <a href="https://github.com/Mythologyli/zju-connect">ZJU Connect</a></p> """
    QMessageBox.about(window, f"关于 {APP_NAME}", about_text)
```

`check_for_updates` 中把 `https://github.com/kowyo/hitsz-connect-verge/releases/latest` 替换为 `RELEASES_URL`（import 自 constants）。

- [ ] **Step 6: update_service.py URL 走 constants**

`get_latest_version` 中：

```python
from common.constants import UPDATE_API_URL
...
            url = UPDATE_API_URL
```

（竞态修复在 Task 8，这里只换 URL。）

- [ ] **Step 7: pyproject.toml 改名 + 加依赖**

```toml
[project]
name = "bitzh-connect"
version = "1.0.0"
description = "A GUI for connecting to the BITZH EasyConnect network."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "keyring>=25.5",
    "nuitka>=4.0.8",
    "packaging>=26.2",
    "pyobjc>=12.1 ; sys_platform == 'darwin'",
    "pyside6>=6.11.0",
    "requests>=2.33.1",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-qt>=4.4",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 8: `.app-version` 改为 `1.0.0`**

- [ ] **Step 9: tests/conftest.py**

```python
import os
import sys
from pathlib import Path

# 无头环境跑 Qt
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# app/ 目录加入 import 路径（项目内模块以 utils./views./common. 顶层包互相引用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
```

- [ ] **Step 10: 验证**

```bash
cd hitsz-connect-verge
uv sync
uv run pytest tests/ -v
```

预期：没有测试用例时输出 `no tests ran`（pytest 无收集用例时退出码为 5，属正常）；`uv run python -c "import sys; sys.path.insert(0,'app'); from common.constants import APP_NAME; print(APP_NAME)"` 输出 `BITZH Connect`。

GUI 冒烟（有屏环境）：`uv run app/main.py`，窗口标题应为 "BITZH Connect"，高级设置里服务器默认为 `112.91.150.228`。

- [ ] **Step 11: Commit**

```bash
git add -A && git commit -m "feat: rebrand to BITZH Connect, add constants module and test infra"
```

---

### Task 2: 修复 shlex.quote 密码 bug + 内核参数名更新（B1、B8）

**Files:**
- Modify: `app/utils/connection_utils.py`
- Create: `tests/test_connection_args.py`

**背景：** `subprocess.Popen(list)` 不经 shell，`shlex.quote` 给含特殊字符的值裹上的单引号会被**字面**传给 zju-connect。已实测 `'pass!word'` 这类值必现。修复 = 删除所有 `shlex.quote`。

- [ ] **Step 1: 把参数构建抽成纯函数以便测试**

在 `app/utils/connection_utils.py` 中新增（供 `start_connection` 调用）：

```python
def build_command_args(window, command):
    """根据窗口配置构建 zju-connect 命令行参数。

    注意：严禁对参数做 shell 引号处理——subprocess 传 list 不经 shell，
    任何引号都会被字面传给内核（上游 shlex.quote 的 bug）。
    """
    command_args = [
        command,
        "-server", window.server_address,
        "-port", str(window.port),
        "-username", window.username_input.text(),
        "-password", window.password_input.text(),
    ]

    # 远端 DNS：auto 或指定地址（参数新名为 -remote-dns-server）
    if window.auto_dns:
        command_args.extend(["-remote-dns-server", "auto"])
    else:
        command_args.extend(["-remote-dns-server", window.dns_server])

    if window.http_bind:
        command_args.extend(["-http-bind", "127.0.0.1:" + window.http_bind])

    if window.socks_bind:
        command_args.extend(["-socks-bind", "127.0.0.1:" + window.socks_bind])

    if not window.keep_alive:
        command_args.append("-disable-keep-alive")

    if window.debug_dump:
        command_args.append("-debug-dump")

    if window.disable_multi_line:
        command_args.append("-disable-multi-line")

    if window.cert_file:
        command_args.extend(["-cert-file", window.cert_file])
        if window.cert_password:
            command_args.extend(["-cert-password", window.cert_password])

    command_args.append("-disable-zju-config")
    command_args.append("-skip-domain-resource")

    return command_args


def mask_command_args(command_args):
    """生成脱敏后的命令行副本，用于日志展示。"""
    debug_command = command_args.copy()
    for flag in ("-username", "-password", "-cert-password"):
        if flag in debug_command:
            debug_command[debug_command.index(flag) + 1] = "********"
    return debug_command
```

- [ ] **Step 2: 写失败测试**

`tests/test_connection_args.py`：

```python
from types import SimpleNamespace

from utils.connection_utils import build_command_args, mask_command_args


def _fake_window(**overrides):
    w = SimpleNamespace(
        server_address="112.91.150.228",
        port="443",
        auto_dns=True,
        dns_server="",
        http_bind="1081",
        socks_bind="1080",
        keep_alive=True,
        debug_dump=False,
        disable_multi_line=False,
        cert_file="",
        cert_password="",
        username_input=SimpleNamespace(text=lambda: "2024000001"),
        password_input=SimpleNamespace(text=lambda: "p@ss!word with space"),
    )
    for k, v in overrides.items():
        setattr(w, k, v)
    return w


def test_special_char_password_passed_verbatim():
    """含特殊字符的密码必须原样传递，不能被加引号（上游 shlex.quote bug 的回归测试）"""
    args = build_command_args(_fake_window(), "zju-connect")
    idx = args.index("-password")
    assert args[idx + 1] == "p@ss!word with space"
    assert not args[idx + 1].startswith("'")


def test_auto_dns_uses_new_flag_name():
    args = build_command_args(_fake_window(), "zju-connect")
    assert "-remote-dns-server" in args
    assert "-zju-dns-server" not in args
    assert args[args.index("-remote-dns-server") + 1] == "auto"


def test_mask_hides_credentials():
    args = build_command_args(_fake_window(), "zju-connect")
    masked = mask_command_args(args)
    assert "p@ss!word with space" not in " ".join(masked)
    assert "2024000001" not in " ".join(masked)
```

- [ ] **Step 3: 跑测试确认通过**

```bash
uv run pytest tests/test_connection_args.py -v
```

预期：3 个用例全 PASS（此时函数已是新实现）。

- [ ] **Step 4: start_connection 改用新函数**

`start_connection` 中删除 `shlex` import 与原有 `command_args = [...]` 整段拼参逻辑，替换为：

```python
    command_args = build_command_args(window, command)
    window.output_text.append(f"Running command: {' '.join(mask_command_args(command_args))}\n")
```

文件顶部删除 `import shlex`。

- [ ] **Step 5: 回归验证**

```bash
uv run pytest tests/ -v && uv run app/main.py
```

预期：测试全过；GUI 点连接后日志框第一行 `Running command:` 中密码为 `********`。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "fix: pass args verbatim to zju-connect (shlex.quote broke special-char passwords), use -remote-dns-server"
```

---

### Task 3: zju-connect 输出解析器（纯函数）

**Files:**
- Create: `app/utils/log_parser.py`
- Create: `tests/test_log_parser.py`

**背景：** 重连与仪表盘都依赖对内核输出的解析。已确认的内核日志特征：
- 登录成功最后一步：`Client IP: 10.0.43.17`（`client/easyconnect/request.go` 的 `requestIP()`，`log.Printf`）
- 登录失败：`VPN client setup error: ...`（`main.go` 的 `log.Fatalf`），EasyConnect 服务端认证失败报文含 `Invalid username or password`（已用 curl 对 112.91.150.228 实测确认）
- 服务器踢人：`SHUTDOWN (cmd 0x08)` / `RECONNECT_LATER (cmd 0x...)`（`protocol.go`）

**注意：** 认证失败的确切日志行需要用错误密码对真实服务器跑一次来校准（见 Task 11 验证清单第 2 条，校准后把模式补进 `AUTH_FAILURE_PATTERNS`）。

- [ ] **Step 1: 写失败测试**

`tests/test_log_parser.py`：

```python
from utils.log_parser import is_auth_failure, is_server_kick, parse_client_ip


def test_parse_client_ip():
    assert parse_client_ip("2026/09/01 12:00:00 Client IP: 10.0.43.17") == "10.0.43.17"


def test_parse_client_ip_absent():
    assert parse_client_ip("TLS: connected to: 112.91.150.228:443") is None


def test_parse_client_ip_rejects_malformed():
    assert parse_client_ip("Client IP: 999.1.2.3") is None


def test_auth_failure_server_message():
    assert is_auth_failure("VPN client setup error: Invalid username or password!")


def test_auth_failure_chinese():
    assert is_auth_failure("VPN client setup error: 用户名或密码错误")


def test_auth_failure_not_triggered_by_normal_log():
    assert not is_auth_failure("Client IP: 10.0.43.17")
    assert not is_auth_failure("TLS: connected to: 112.91.150.228:443")


def test_server_kick():
    assert is_server_kick("SendConn: server returned SHUTDOWN (cmd 0x08); session terminated by server")
    assert is_server_kick("SendConn: server returned RECONNECTLATER (cmd 0x05); should re-login and retry")
    assert not is_server_kick("Client IP: 10.0.43.17")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_log_parser.py -v
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 实现 log_parser.py**

```python
# app/utils/log_parser.py
"""解析 zju-connect 内核输出的纯函数集合。

日志特征来源（上游 Go 源码，v1.3.1）：
- 登录成功最后一步输出 "Client IP: x.x.x.x"（request.go requestIP）
- 登录失败 log.Fatalf 输出 "VPN client setup error: ..."（main.go）
- 服务端踢人输出 "SHUTDOWN (cmd 0x08)" / "RECONNECTLATER (cmd 0x..)"（protocol.go）
"""
import re

_CLIENT_IP_RE = re.compile(r"Client IP:\s*((?:\d{1,3}\.){3}\d{1,3})")

# 认证失败模式。对真实服务器的校准见 Task 11 验证清单。
AUTH_FAILURE_PATTERNS = [
    re.compile(r"Invalid username or password", re.IGNORECASE),
    re.compile(r"用户名或密码", re.IGNORECASE),
    re.compile(r"auth\w*\s*(fail|error|invalid)", re.IGNORECASE),
    re.compile(r"setup error.*(password|credential|认证|密码)", re.IGNORECASE),
]

_SERVER_KICK_RE = re.compile(r"SHUTDOWN \(cmd|RECONNECTLATER \(cmd", re.IGNORECASE)


def _valid_ip(ip: str) -> bool:
    return all(0 <= int(part) <= 255 for part in ip.split("."))


def parse_client_ip(text: str) -> str | None:
    """从一行内核输出中提取虚拟 IP，没有则返回 None。"""
    match = _CLIENT_IP_RE.search(text)
    if match and _valid_ip(match.group(1)):
        return match.group(1)
    return None


def is_auth_failure(text: str) -> bool:
    """判断该行输出是否表示认证失败（此类失败不应触发自动重连）。"""
    return any(pattern.search(text) for pattern in AUTH_FAILURE_PATTERNS)


def is_server_kick(text: str) -> bool:
    """判断该行输出是否表示被服务器主动断开（用于日志提示）。"""
    return bool(_SERVER_KICK_RE.search(text))
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_log_parser.py -v
```

预期：7 个用例全 PASS。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: add zju-connect output parser (client IP / auth failure / server kick)"
```

---

### Task 4: 自动重连状态机

**Files:**
- Create: `app/services/reconnect_manager.py`
- Create: `tests/test_reconnect_manager.py`

**策略（grilling 结论 #3）：** 默认开启；手动断开与认证失败不重连；退避 5s→10s→30s；连续失败 3 次后暂停并通知；连接建立且稳定存活 60s 才重置计数（防"连上秒掉"抖动场景无限重试）。

- [ ] **Step 1: 写失败测试**

`tests/test_reconnect_manager.py`：

```python
import pytest
from pytestqt.qtbot import QtBot  # noqa: F401  (确保 pytest-qt 可用)

from services.reconnect_manager import ReconnectManager


@pytest.fixture
def manager(qapp):
    calls = []
    m = ReconnectManager(
        reconnect_action=lambda: calls.append("reconnect"),
        max_retries=3,
        backoff=[0.05, 0.1, 0.15],  # 测试用短退避（秒）
        stability_window=0.2,
    )
    yield m, calls
    m.cancel()


def test_manual_stop_does_not_reconnect(manager):
    m, calls = manager
    m.on_process_exited(manual=True, auth_failed=False)
    QtBot().wait(300)
    assert calls == []
    assert m.retry_count == 0


def test_auth_failure_does_not_reconnect(manager):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=True)
    QtBot().wait(300)
    assert calls == []


def test_crash_triggers_reconnect_after_backoff(manager, qtbot):
    m, calls = manager
    scheduled = []
    m.retry_scheduled.connect(lambda attempt, delay: scheduled.append((attempt, delay)))
    m.on_process_exited(manual=False, auth_failed=False)
    assert scheduled == [(1, 0.05)]
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)


def test_exhaustion_after_max_retries(manager, qtbot):
    m, calls = manager
    exhausted = []
    m.retries_exhausted.connect(lambda: exhausted.append(True))
    for _ in range(3):
        m.on_process_exited(manual=False, auth_failed=False)
        qtbot.waitUntil(lambda: len(calls) > len(exhausted) or True, timeout=10)  # 让事件循环转一下
        qtbot.wait(250)  # 等退避计时器触发
    # 已触发 3 次重连，第 4 次掉线应暂停
    assert calls == ["reconnect"] * 3
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.wait(300)
    assert exhausted == [True]
    assert calls == ["reconnect"] * 3


def test_stable_connection_resets_counter(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)
    assert m.retry_count == 1
    # 连接建立并稳定存活超过 stability_window → 计数重置
    m.on_connection_established()
    qtbot.wait(400)
    assert m.retry_count == 0


def test_unstable_connection_keeps_counter(manager, qtbot):
    m, calls = manager
    m.on_process_exited(manual=False, auth_failed=False)
    qtbot.waitUntil(lambda: calls == ["reconnect"], timeout=2000)
    m.on_connection_established()
    m.on_process_exited(manual=False, auth_failed=False)  # 60s(测试为0.2s)内又掉 → 不重置
    assert m.retry_count == 2
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_reconnect_manager.py -v
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 实现 reconnect_manager.py**

```python
# app/services/reconnect_manager.py
"""自动重连状态机。

策略：
- 手动断开 / 认证失败 / 功能被禁用 → 不重连
- 其余进程退出 → 按 backoff 退避重连，最多 max_retries 次
- 连接建立且稳定存活 stability_window 秒 → 重置重试计数
  （防止"连上秒掉"抖动场景下无限重试）
"""
from PySide6.QtCore import QObject, QTimer, Signal


class ReconnectManager(QObject):
    retry_scheduled = Signal(int, float)  # (第几次重试, 延迟秒数)
    retry_triggered = Signal(int)         # 即将发起第 n 次重连
    retries_exhausted = Signal()          # 达到上限，暂停自动重连
    counter_reset = Signal()              # 计数被重置

    def __init__(
        self,
        reconnect_action,
        max_retries: int = 3,
        backoff: list[float] | None = None,
        stability_window: float = 60,
        parent=None,
    ):
        super().__init__(parent)
        self._reconnect_action = reconnect_action
        self._max_retries = max_retries
        self._backoff = backoff or [5, 10, 30]
        self._stability_window = stability_window
        self._enabled = True
        self._retry_count = 0

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._fire_retry)

        self._stability_timer = QTimer(self)
        self._stability_timer.setSingleShot(True)
        self._stability_timer.timeout.connect(self._reset_counter)

    @property
    def retry_count(self) -> int:
        return self._retry_count

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        if not enabled:
            self.cancel()

    def on_connection_established(self):
        """连接建立（看到 Client IP）。启动稳定期计时，存活足够久才重置计数。"""
        self._retry_timer.stop()
        self._stability_timer.start(int(self._stability_window * 1000))

    def on_process_exited(self, manual: bool, auth_failed: bool):
        """连接进程退出。决定是否安排重连。"""
        self._stability_timer.stop()
        if manual or auth_failed or not self._enabled:
            return
        if self._retry_count >= self._max_retries:
            self._reset_counter()
            self.retries_exhausted.emit()
            return
        delay = self._backoff[min(self._retry_count, len(self._backoff) - 1)]
        self._retry_count += 1
        self._retry_timer.start(int(delay * 1000))
        self.retry_scheduled.emit(self._retry_count, delay)

    def cancel(self):
        """用户手动断开/退出应用时调用：停止一切待执行的重连并重置计数。"""
        self._retry_timer.stop()
        self._stability_timer.stop()
        self._reset_counter()

    def _fire_retry(self):
        self.retry_triggered.emit(self._retry_count)
        self._reconnect_action()

    def _reset_counter(self):
        if self._retry_count != 0:
            self._retry_count = 0
            self.counter_reset.emit()
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_reconnect_manager.py -v
```

预期：6 个用例全 PASS。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: add auto-reconnect state machine (backoff 5/10/30s, max 3 retries, 60s stability reset)"
```

---

### Task 5: 连接流程集成（重连接线、异步停止、代理残留清理；B3、B4、B5）

**Files:**
- Modify: `app/utils/set_proxy.py`
- Modify: `app/utils/connection_utils.py`
- Modify: `app/views/main_window.py`
- Modify: `app/utils/tray_utils.py`（退出路径）
- Create: `tests/test_connection_flow.py`

- [ ] **Step 1: CommandWorker 改造（finished 带退出码、stop 非阻塞）**

`app/utils/set_proxy.py` 中：

```python
class CommandWorker(QThread):
    output = Signal(str)
    finished = Signal(int)  # 携带进程退出码

    ...
    def run(self):
        exit_code = -1
        try:
            if self.proxy_enabled and self.window:
                proxy_handler = self._proxy_handlers.get(system())
                if proxy_handler:
                    proxy_handler(True, *get_proxy_settings(self.window))

            creation_flags = CREATE_NO_WINDOW if system() == "Windows" else 0
            self.process = subprocess.Popen(
                self.command_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                encoding="utf-8",
                creationflags=creation_flags,
            )

            for line in self.process.stdout:
                self.output.emit(line)
            self.process.wait()
            exit_code = self.process.returncode
        finally:
            if self.proxy_enabled:
                proxy_handler = self._proxy_handlers.get(system())
                if proxy_handler:
                    proxy_handler(False)
            self.finished.emit(exit_code)

    def stop(self):
        """非阻塞终止进程。进程退出与代理由 run() 的收尾逻辑在工作线程完成。"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
```

- [ ] **Step 2: set_proxy.py 新增残留清理函数**

文件末尾追加：

```python
def proxy_points_to_us(http_port):
    """检查当前系统代理是否指向我们的 HTTP 代理端口。"""
    try:
        if system() == "Windows":
            import winreg as reg

            with reg.OpenKey(
                reg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as s:
                enabled, _ = reg.QueryValueEx(s, "ProxyEnable")
                server, _ = reg.QueryValueEx(s, "ProxyServer")
                return bool(enabled) and str(server).endswith(f":{http_port}")
        elif system() == "Darwin":
            out = subprocess.check_output(
                ["networksetup", "-getwebproxy", "Wi-Fi"], text=True
            )
            return "Enabled: Yes" in out and f"Port: {http_port}" in out
        elif system() == "Linux":
            mode = subprocess.check_output(
                ["gsettings", "get", "org.gnome.system.proxy", "mode"], text=True
            )
            port = subprocess.check_output(
                ["gsettings", "get", "org.gnome.system.proxy.http", "port"], text=True
            )
            return "manual" in mode and str(http_port) in port
    except Exception:
        return False
    return False


def cleanup_residue_proxy(window):
    """启动时调用：若系统代理仍指向本应用的端口（上次被强杀残留），则关闭它。

    返回 True 表示执行了清理。
    """
    http_port = getattr(window, "http_bind", None) or "1081"
    if not proxy_points_to_us(http_port):
        return False
    handler = {
        "Windows": set_windows_proxy,
        "Darwin": set_macos_proxy,
        "Linux": set_linux_proxy,
    }.get(system())
    if handler:
        handler(False)
        return True
    return False
```

注意：macOS 分支只对 "Wi-Fi" 服务做检测（检测用），清理时 `set_macos_proxy(False)` 仍覆盖所有服务，够用且简单。

- [ ] **Step 3: connection_utils.py 接线重连与解析**

整个文件改为：

```python
import os
import sys
from platform import system
import gc
from PySide6.QtCore import QSignalBlocker
from .set_proxy import CommandWorker
from .log_parser import parse_client_ip, is_auth_failure, is_server_kick


def handle_output(window, text):
    """处理内核输出：上屏 + 解析状态"""
    window.output_text.append(text)

    ip = parse_client_ip(text)
    if ip:
        window.virtual_ip = ip
        window.reconnect_manager.on_connection_established()
        window.status_panel.set_connected(ip)

    if is_auth_failure(text):
        window._auth_failed = True

    if is_server_kick(text):
        window.output_text.append("[BITZH Connect] 检测到被服务器断开，将自动重连\n")


def handle_connection_finished(window, exit_code):
    """进程退出收尾（可能被自动重连重新拉起）"""
    if window.worker:
        window.worker.output.disconnect()
        window.worker.finished.disconnect()
        window.worker.deleteLater()
        window.worker = None
        gc.collect()

    manual = getattr(window, "_manual_stop", True)
    auth_failed = getattr(window, "_auth_failed", False)

    if auth_failed:
        window.status_panel.set_disconnected("认证失败，请检查用户名和密码")
    else:
        window.status_panel.set_disconnected()

    # 编程式复位按钮必须屏蔽信号（grilling 确认的 plan 漏洞修复）：
    # 直接 setChecked(False) 会触发 toggled → stop_connection() → reconnect_manager.cancel()，
    # 把重试计数清零——退避将永远停在第一档、retries_exhausted 永不触发。
    # 被屏蔽的 toggled 附带效果（按钮文案、输入框禁用态）需手动恢复。
    if hasattr(window, "connect_button"):
        blocker = QSignalBlocker(window.connect_button)
        window.connect_button.setChecked(False)
        window.connect_button.setText("连接")
        window.username_input.setEnabled(True)
        window.password_input.setEnabled(True)
        del blocker

    window.reconnect_manager.on_process_exited(manual=manual, auth_failed=auth_failed)


def start_connection(window):
    """启动 VPN 连接"""
    if window.worker and window.worker.isRunning():
        window.status_panel.set_connecting()
        return

    window._manual_stop = False
    window._auth_failed = False

    is_nuitka = "__compiled__" in globals()

    if is_nuitka:
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        base_path = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )

    if system() == "Windows":
        command = os.path.join(base_path, "app", "core", "zju-connect.exe")
    else:
        command = os.path.join(base_path, "app", "core", "zju-connect")
        if os.path.exists(command):
            os.chmod(command, 0o755)

    command_args = build_command_args(window, command)
    window.output_text.append(f"Running command: {' '.join(mask_command_args(command_args))}\n")

    window.worker = CommandWorker(
        command_args=command_args, proxy_enabled=window.proxy, window=window
    )
    window.worker.output.connect(lambda text: handle_output(window, text))
    window.worker.finished.connect(lambda code: handle_connection_finished(window, code))
    window.worker.start()

    window.status_panel.set_connecting()


def stop_connection(window, manual=True):
    """断开连接。非阻塞：只发 terminate，收尾在 finished 回调里做。"""
    window._manual_stop = manual
    window.reconnect_manager.cancel()
    if window.worker:
        window.worker.stop()
        if not window.worker.isRunning():
            handle_connection_finished(window, -1)
    else:
        window.status_panel.set_disconnected()
```

（`build_command_args` / `mask_command_args` 已在 Task 2 定义于本文件。）

- [ ] **Step 4: main_window.py 集成**

`MainWindow.__init__` 中 `self.tray_icon = ...` 之前插入：

```python
from services.reconnect_manager import ReconnectManager
from utils.set_proxy import cleanup_residue_proxy
...
        self.virtual_ip = None
        self._manual_stop = True
        self._auth_failed = False
        self.reconnect_manager = ReconnectManager(
            reconnect_action=lambda: self.connect_button.setChecked(True),
        )
        self.reconnect_manager.set_enabled(self.auto_reconnect)
        self.reconnect_manager.retry_scheduled.connect(
            lambda attempt, delay: self.status_panel.set_reconnecting(attempt, delay)
        )
        self.reconnect_manager.retries_exhausted.connect(
            lambda: self.status_panel.set_reconnect_paused()
        )
        if cleanup_residue_proxy(self):
            self.output_text.append("[BITZH Connect] 已清理上次异常退出残留的系统代理\n")
```

（`status_panel` 在 Task 8 创建；本任务内 `window.status_panel` 可先挂一个临时的 `SimpleNamespace` 桩对象让流程跑通，Task 8 替换为真组件。推荐：本任务先建最小 `StatusPanel` 骨架只含 5 个 set_ 方法空实现，Task 8 填充 UI。）

`status_label` 全部改由 `status_panel` 承担：删除 `self.status_label` 相关代码，`start_connection`/`stop_connection` 里对 `status_label` 的引用改为 `status_panel` 调用（见 Step 3 代码，已无 status_label）。

退出路径（`tray_utils.quit_app`）：`window.stop_connection()` 已非阻塞，给工作线程 1.5s 收尾再退出：

```python
def quit_app(window, tray_icon):
    """Quit the application"""
    window.stop_connection()
    tray_icon.deleteLater()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(1500, QApplication.quit)
```

（删除原来的 `window.deleteLater(); gc.collect()` 同步退出，交给事件循环。）

- [ ] **Step 5: 集成测试（无头验证状态流转）**

`tests/test_connection_flow.py`：

```python
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot  # noqa: F401


def _make_window(qtbot):
    from views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_auth_failure_blocks_reconnect(qtbot):
    win = _make_window(qtbot)
    fired = []
    win.reconnect_manager._reconnect_action = lambda: fired.append(True)
    win._manual_stop = False
    win._auth_failed = True
    win.reconnect_manager.on_process_exited(
        manual=win._manual_stop, auth_failed=win._auth_failed
    )
    QtBot().wait(300)
    assert fired == []


def test_output_parsing_sets_virtual_ip(qtbot):
    win = _make_window(qtbot)
    from utils.connection_utils import handle_output

    handle_output(win, "2026/09/01 12:00:00 Client IP: 10.0.43.17\n")
    assert win.virtual_ip == "10.0.43.17"


def test_cleanup_residue_proxy_noop_when_not_ours(qtbot):
    win = _make_window(qtbot)
    from utils.set_proxy import cleanup_residue_proxy

    with patch("utils.set_proxy.proxy_points_to_us", return_value=False):
        assert cleanup_residue_proxy(win) is False
```

注意：`MainWindow()` 构造里有 `QTimer.singleShot(5000, ...)`（connect_startup 默认 False 不触发）与更新检查（check_update 默认 True → 会发真实网络请求！）。测试需 patch 掉：

在 `tests/test_connection_flow.py` 顶部加：

```python
import pytest


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    # 注意必须 patch main_window 命名空间（main_window 用 from-import 绑定了该函数）
    monkeypatch.setattr("views.main_window.check_for_updates", lambda *a, **k: None)
```

（若 QSettings 里存有 connect_startup=True 也会干扰，测试前用 `QSettings(ORG_NAME, APP_NAME).clear()` 隔离——在 fixture 里做。）

- [ ] **Step 6: 跑全部测试**

```bash
uv run pytest tests/ -v
```

预期：全 PASS。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: wire auto-reconnect into connection flow; non-blocking stop; startup proxy residue cleanup"
```

---

### Task 6: keyring 凭据存储（B2）

**Files:**
- Create: `app/utils/credential_store.py`
- Modify: `app/utils/credential_utils.py`
- Create: `tests/test_credential_store.py`

**设计：** 用户名继续存 QSettings（非敏感）；密码存系统钥匙串（服务名 `BITZH Connect`，键为用户名）。keyring 后端不可用（如 Linux 无 Secret Service）时回退 QSettings 明文并打告警日志。含迁移：QSettings 里已有明文密码时自动搬迁到 keyring 并清除明文。

- [ ] **Step 1: 写失败测试**

`tests/test_credential_store.py`：

```python
from utils.credential_store import CredentialStore


class FakeBackend:
    """内存 keyring 后端，模拟 (service, username) -> password"""

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


class BrokenBackend(FakeBackend):
    def get_password(self, service, username):
        raise RuntimeError("no secret service")

    def set_password(self, service, username, password):
        raise RuntimeError("no secret service")


def test_roundtrip():
    store = CredentialStore(backend=FakeBackend())
    assert store.available
    store.set_password("user1", "secret")
    assert store.get_password("user1") == "secret"
    store.delete_password("user1")
    assert store.get_password("user1") is None


def test_unavailable_backend_reports_not_available():
    store = CredentialStore(backend=BrokenBackend())
    assert not store.available
    assert store.get_password("user1") is None  # 不抛异常
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_credential_store.py -v
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 实现 credential_store.py**

```python
# app/utils/credential_store.py
"""凭据存储：密码优先存系统钥匙串，后端不可用时调用方负责回退。

用户名不敏感，仍存 QSettings；这里只管密码。
"""
import keyring

SERVICE_NAME = "BITZH Connect"


class CredentialStore:
    def __init__(self, backend=None):
        self._backend = backend if backend is not None else keyring
        self._available = self._probe()

    def _probe(self) -> bool:
        try:
            self._backend.get_password(SERVICE_NAME, "__probe__")
            return True
        except Exception:
            return False

    @property
    def available(self) -> bool:
        return self._available

    def get_password(self, username: str) -> str | None:
        if not self._available or not username:
            return None
        try:
            return self._backend.get_password(SERVICE_NAME, username)
        except Exception:
            return None

    def set_password(self, username: str, password: str) -> bool:
        """成功返回 True；后端不可用/失败返回 False（调用方回退明文）。"""
        if not self._available or not username:
            return False
        try:
            self._backend.set_password(SERVICE_NAME, username, password)
            return True
        except Exception:
            return False

    def delete_password(self, username: str):
        if not self._available or not username:
            return
        try:
            self._backend.delete_password(SERVICE_NAME, username)
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试确认通过**

```bash
uv run pytest tests/test_credential_store.py -v
```

预期：2 个用例全 PASS。

- [ ] **Step 5: credential_utils.py 改用 store（含明文迁移）**

```python
# app/utils/credential_utils.py
from .config_utils import load_config, save_config
from .credential_store import CredentialStore

_store = CredentialStore()


def _log(window, msg):
    if hasattr(window, "output_text"):
        window.output_text.append(msg)


def save_credentials(window):
    config = load_config()
    remember = window.remember_cb.isChecked()
    config["remember"] = remember

    if remember:
        username = window.username_input.text()
        password = window.password_input.text()
        config["username"] = username
        if _store.set_password(username, password):
            config["password"] = ""  # 已入钥匙串，清掉明文
        else:
            config["password"] = password  # 回退明文
            _log(window, "[BITZH Connect] 警告：系统钥匙串不可用，密码将以明文保存\n")
    else:
        _store.delete_password(window.username_input.text())
        config["username"] = ""
        config["password"] = ""

    save_config(config)


def load_credentials():
    """返回 (username, password)。含一次性明文→钥匙串迁移。"""
    config = load_config()
    username = config.get("username", "")
    password = _store.get_password(username) or ""

    legacy_plaintext = config.get("password", "")
    if username and not password and legacy_plaintext:
        password = legacy_plaintext
        if _store.set_password(username, legacy_plaintext):
            config["password"] = ""
            save_config(config)

    return username, password
```

- [ ] **Step 6: main_window.py / config_utils.py 接线**

`main_window.py` 的 `setup_ui` 中，用户名密码回填从 `self.username/self.password` 改为：

```python
from utils.credential_utils import load_credentials
...
        saved_username, saved_password = load_credentials()
        self.username_input.setText(saved_username)
        self.password_input.setText(saved_password)
```

（`load_settings` 里 `self.username/self.password` 保留无妨，但 UI 以 `load_credentials()` 为准。）

- [ ] **Step 7: 真实环境验证（不 mock）**

在有屏环境跑 `uv run app/main.py`：勾选"记住密码"连接一次 → 退出重开 → 密码应自动回填。
macOS 验证钥匙串：打开"钥匙串访问"搜 `BITZH Connect` 应能看到条目。
回归：`uv run pytest tests/ -v` 全过。

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: store password in system keyring with plaintext fallback and migration"
```

---

### Task 7: 设计基建 — 语义主题 + 动效工具 + 旋转指示器

**Files:**
- Create: `app/common/theme.py`
- Create: `app/utils/motion_utils.py`
- Create: `app/views/busy_spinner.py`
- Create: `tests/test_theme.py`

**设计规范（Apple 流体界面原则 → Qt 落地）：**

| 原则 | 落地方式 |
|---|---|
| 语义反馈四分类 | 状态色：未连接灰 / 进行中琥珀 / 已连接绿（BIT 绿系）/ 失败红，全部深浅色双值 |
| 品牌一致性 | accent 用 BIT 品牌绿（浅色 `#005C31` 深绿、深色 `#16AE68` 标准绿），取自素材库 VI 色卡 |
| 即时反馈 | 按钮 `:pressed` 态 100ms 内变色；连接按钮禁用态有明确 tooltip |
| 无动量不用弹性 | 状态切换一律 250ms OutCubic 颜色过渡；禁止 bounce |
| 可打断 | 展开/颜色动画总是从**当前展示值**重启，绝不回跳到逻辑初值 |
| 减少动态效果 | 系统开启时所有动画退化为即时切换（spinner 不显示） |
| 字体工艺 | 状态大标题 20pt DemiBold 负字距；卡片标题 11pt 灰；数值 15pt Semibold + 表格数字（tnum，防每秒抖动） |

**品牌色来源（`/Users/jerry/Projects/素材/ai/COLOR_USAGE` 色卡 + 校徽实测采样）：** 深绿 `#005C31`（校徽中心）、标准绿 `#16AE68`（树）、赭石 `#A23F0D`（外环，仅图标素材自带，UI 不用）。

- [ ] **Step 1: 写失败测试**

`tests/test_theme.py`：

```python
import re

import pytest

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_semantic_colors_all_valid_hex():
    from common import theme

    for name in ("idle", "working", "connected", "error",
                 "accent", "accent_pressed", "accent_text", "secondary_text"):
        assert HEX_RE.match(theme.semantic_color(name)), name


def test_is_dark_returns_bool():
    from common import theme

    assert theme.is_dark() in (True, False)


def test_card_background_valid_hex():
    from common import theme

    assert HEX_RE.match(theme.card_background())


def test_font_hierarchy():
    from common import theme

    assert theme.status_title_font().pointSize() >= 18
    assert theme.status_title_font().letterSpacing() < 100  # 负字距
    assert theme.card_value_font().pointSize() >= 14
    assert theme.card_title_font().pointSize() < theme.card_value_font().pointSize()


def test_reduce_motion_returns_bool():
    from utils.motion_utils import reduce_motion

    assert reduce_motion() in (True, False)


def test_animate_label_color_immediate_when_reduce_motion(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: True)
    label = QLabel("●")
    qtbot.addWidget(label)
    motion_utils.animate_label_color(label, "#28C840")
    assert "#28c840" in label.styleSheet().lower()
    assert label._theme_color == "#28C840"


def test_animated_height_toggle_immediate_when_reduce_motion(qtbot, monkeypatch):
    from PySide6.QtWidgets import QTextEdit

    from utils import motion_utils

    monkeypatch.setattr(motion_utils, "reduce_motion", lambda: True)
    w = QTextEdit()
    qtbot.addWidget(w)
    motion_utils.animated_height_toggle(w, expanding=False)
    assert not w.isVisible()
    motion_utils.animated_height_toggle(w, expanding=True)
    assert w.isVisible()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
uv run pytest tests/test_theme.py -v
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 实现 theme.py**

```python
# app/common/theme.py
"""语义化设计 tokens：颜色随深浅色自适应，字体层级统一。

品牌色取自 BIT 视觉识别系统（素材/COLOR_USAGE 色卡）：
- 深绿 #005C31（校徽中心）→ 浅色模式 accent
- 标准绿 #16AE68（树）→ 深色模式 accent / 已连接状态
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QPalette

_COLORS = {
    #                 light       dark
    "idle":           ("#8E8E93", "#98989D"),  # 未连接灰
    "working":        ("#FF9500", "#FF9F0A"),  # 进行中琥珀
    "connected":      ("#0E9F5B", "#16AE68"),  # 已连接：BIT 绿系
    "error":          ("#FF3B30", "#FF453A"),  # 失败红
    "accent":         ("#005C31", "#16AE68"),  # 主按钮：BIT 品牌绿
    "accent_pressed": ("#004A26", "#0E9F5B"),  # 按下态加深
    "accent_text":    ("#FFFFFF", "#000000"),  # accent 上的文字
    "secondary_text": ("#6E6E73", "#98989D"),  # 次要信息灰
}


def is_dark() -> bool:
    """当前是否为深色模式。Linux 桌面可能不报告，退回 palette 亮度判断。"""
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Unknown:
        return QGuiApplication.palette().color(QPalette.Window).lightness() < 128
    return scheme == Qt.ColorScheme.Dark


def semantic_color(name: str) -> str:
    """取语义色（自动按深浅色）。"""
    light, dark = _COLORS[name]
    return dark if is_dark() else light


def card_background() -> str:
    """卡片底色：窗口色微调（浅色提亮 / 深色加亮），保证与窗口背景可区分。"""
    base = QGuiApplication.palette().color(QPalette.Window)
    return base.lighter(116 if is_dark() else 104).name()


def on_scheme_changed(callback):
    """系统深浅色切换时回调（用于刷新样式表）。"""
    QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _scheme: callback())


def status_title_font() -> QFont:
    """状态大标题：20pt DemiBold，负字距。"""
    f = QFont()
    f.setPointSize(20)
    f.setWeight(QFont.DemiBold)
    f.setLetterSpacing(QFont.PercentageSpacing, 98)
    return f


def card_title_font() -> QFont:
    f = QFont()
    f.setPointSize(11)
    return f


def card_value_font() -> QFont:
    """卡片数值：15pt Semibold，尝试开启表格数字（tnum）防抖动（Qt 6.7+，不支持则忽略）。"""
    f = QFont()
    f.setPointSize(15)
    f.setWeight(QFont.DemiBold)
    try:
        f.setFeature("tnum", 1)
    except (AttributeError, TypeError):
        pass
    return f
```

- [ ] **Step 4: 实现 motion_utils.py**

```python
# app/utils/motion_utils.py
"""动效工具：减少动态效果检测 + 可打断的过渡动画。

原则（Apple 流体界面指南）：
- 非手势状态切换一律 250ms OutCubic，不用弹性（无动量场景弹性是错误的）
- 所有动画可打断：从当前展示值（presentation value）重启，不回跳
- 系统开启"减少动态效果"时全部退化为即时切换
"""
from platform import system

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QVariantAnimation
from PySide6.QtGui import QColor

ANIMATION_DURATION_MS = 250


def reduce_motion() -> bool:
    """系统级"减少动态效果"开关。读不到的平台返回 False。"""
    try:
        if system() == "Darwin":
            import objc

            workspace = objc.lookUpClass("NSWorkspace").sharedWorkspace()
            return bool(workspace.accessibilityDisplayShouldReduceMotion())
        if system() == "Windows":
            import ctypes
            import ctypes.wintypes

            enabled = ctypes.wintypes.BOOL(False)
            # SPI_GETCLIENTAREAANIMATION = 0x1042
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
            return not enabled.value
    except Exception:
        return False
    return False


def animate_label_color(label, target: str, duration: int = ANIMATION_DURATION_MS):
    """标签颜色平滑过渡。可打断：从当前展示颜色出发（记录在 label._theme_color）。"""
    if reduce_motion():
        label.setStyleSheet(f"color: {target};")
        label._theme_color = target
        return None

    start = getattr(label, "_theme_color", None) or label.palette().color(
        label.foregroundRole()
    ).name()
    anim = QVariantAnimation(label)
    anim.setDuration(duration)
    anim.setStartValue(QColor(start))
    anim.setEndValue(QColor(target))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.valueChanged.connect(lambda c: label.setStyleSheet(f"color: {c.name()};"))

    def _store():
        label._theme_color = target

    anim.finished.connect(_store)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    label._color_anim = anim  # 持有引用防 GC
    return anim


def animated_height_toggle(widget, expanding: bool, max_height: int = 200,
                           duration: int = ANIMATION_DURATION_MS, on_frame=None):
    """展开/收起 widget 的高度动画。

    可打断：再次调用时从当前实际高度重启（QPropertyAnimation 会自动停掉同属性旧动画）。
    on_frame: 每帧回调（例如主窗口 adjustSize，让窗口高度随内容平滑变化）。
    """
    if reduce_motion():
        widget.setMaximumHeight(16777215)
        widget.setVisible(expanding)
        if on_frame:
            on_frame()
        return None

    start_h = widget.height() if widget.isVisible() else 0
    if expanding:
        widget.setVisible(True)

    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(duration)
    anim.setStartValue(start_h)
    anim.setEndValue(max_height if expanding else 0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    if on_frame:
        anim.valueChanged.connect(lambda _v: on_frame())

    def _finish():
        widget.setMaximumHeight(16777215)
        if not expanding:
            widget.setVisible(False)

    anim.finished.connect(_finish)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._height_anim = anim
    return anim
```

- [ ] **Step 5: 实现 busy_spinner.py**

```python
# app/views/busy_spinner.py
"""连接中旋转弧指示器。系统开启"减少动态效果"时 start() 为空操作（保持隐藏）。"""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from common import theme
from utils.motion_utils import reduce_motion


class BusySpinner(QWidget):
    def __init__(self, parent=None, diameter: int = 16):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self):
        if reduce_motion():
            return
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.semantic_color("working")))
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        painter.drawArc(rect, -self._angle * 16, 270 * 16)  # drawArc 单位为 1/16 度
        painter.end()
```

- [ ] **Step 6: 跑测试确认通过**

```bash
uv run pytest tests/test_theme.py -v
```

预期：7 个用例全 PASS。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: add design tokens (BIT brand colors, adaptive semantic colors), motion utils and busy spinner"
```

---

### Task 8: 状态仪表盘 UI 重设计（B9、B11）

**Files:**
- Create: `app/views/status_panel.py`
- Modify: `app/views/main_window.py`
- Modify: `tests/conftest.py`（全局隔离 fixture）
- Create: `tests/test_status_panel.py`
- Create: `tests/test_main_window.py`

**布局（信息层级对齐官方截图，视觉语言按 Task 7 规范）：**

```
┌──────────────────────────────┐
│ ◠ ● 已连接        112.91.…   │  ← spinner(仅连接中) + 圆点 + 20pt 大标题 + 服务器小灰字
│ ┌──────────┐ ┌──────────┐   │
│ │ 连接时长   │ │ 虚拟 IP   │   │  ← 圆角卡片（底色自适应深浅色）
│ │ 04:09:56  │ │ 10.0.43.17│   │
│ ├──────────┤ ├──────────┤   │
│ │ ↑ 上行速率 │ │ ↓ 下行速率 │   │  ← 代理模式显示 "—"
│ └──────────┘ └──────────┘   │
│ 用户名 [_______]              │
│ 密码   [_______]              │  ← 两整行（比挤一行更好读），连接中禁用
│ [x] 记住密码   [ ] 显示密码    │
│ ┌──────────────────────┐ ┌──┐│
│ │        连 接          │ │退出││  ← BIT 绿 accent 主按钮 + 小号次要退出按钮（grilling 确认保留）
│ └──────────────────────┘ └──┘│
│ ▶ 运行日志                    │  ← 折叠（250ms 高度动画展开，可中途反向）
└──────────────────────────────┘
```

**关键交互：**
- 用户名或密码为空 → 连接按钮禁用 + tooltip "请输入用户名和密码"（内联校验，不等到点击才报错）
- 连接中按钮文案为"断开"，可立即取消（动画/进程随时可打断）
- 重连等待期间状态行每秒倒计时（持续反馈，不是干等）

- [ ] **Step 1: 扩展 tests/conftest.py（全局隔离）**

在 Task 1 创建的 conftest.py 末尾追加：

```python
import pytest


@pytest.fixture(autouse=True)
def _isolate_app(monkeypatch):
    """每个测试：清空应用配置 + 屏蔽启动时的真实更新检查网络请求。"""
    from PySide6.QtCore import QSettings

    from common.constants import APP_NAME, ORG_NAME

    QSettings(ORG_NAME, APP_NAME).clear()
    # 注意必须 patch main_window 命名空间（from-import 绑定在这里）
    monkeypatch.setattr("views.main_window.check_for_updates", lambda *a, **k: None)
```

同时删除 `tests/test_connection_flow.py` 顶部的 `_no_update_check` 本地 fixture（已由全局覆盖；且它原来 patch 的 `views.menu_utils.check_for_updates` 因 from-import 绑定根本拦不住调用，是错的）。

- [ ] **Step 2: 写失败测试**

`tests/test_status_panel.py`：

```python
import pytest


@pytest.fixture(autouse=True)
def _instant(monkeypatch):
    """颜色动画退化为即时切换，便于断言样式。"""
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)


@pytest.fixture
def panel(qtbot):
    from views.status_panel import StatusPanel

    p = StatusPanel(server_text="112.91.150.228")
    qtbot.addWidget(p)
    return p


def test_initial_state(panel):
    assert "未连接" in panel.status_text.text()
    assert panel.ip_value.text() == "—"
    assert panel.duration_value.text() == "00:00:00"
    assert not panel.spinner.isVisible()


def test_connecting_shows_spinner(panel, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: False)
    panel.set_connecting()
    assert "连接中" in panel.status_text.text()
    assert panel.spinner.isVisible()


def test_connected_shows_ip_and_starts_timer(panel):
    from common import theme

    panel.set_connecting()
    panel.set_connected("10.0.43.17")
    assert "已连接" in panel.status_text.text()
    assert panel.ip_value.text() == "10.0.43.17"
    assert panel._duration_timer.isActive()
    assert not panel.spinner.isVisible()
    assert theme.semantic_color("connected").lower() in panel.status_dot.styleSheet().lower()


def test_disconnected_resets(panel):
    panel.set_connected("10.0.43.17")
    panel.set_disconnected()
    assert "未连接" in panel.status_text.text()
    assert panel.ip_value.text() == "—"
    assert not panel._duration_timer.isActive()


def test_reconnecting_countdown_decrements(panel, qtbot):
    panel.set_reconnecting(1, 3)
    assert "3" in panel.status_text.text()
    assert "第 1 次" in panel.status_text.text()
    qtbot.wait(1300)
    assert "2" in panel.status_text.text()  # 倒计时递减，持续反馈


def test_paused_message(panel):
    from common import theme

    panel.set_reconnect_paused()
    assert "暂停" in panel.status_text.text()
    assert theme.semantic_color("error").lower() in panel.status_dot.styleSheet().lower()


def test_proxy_mode_rates_placeholder(panel):
    panel.set_connected("10.0.43.17")
    assert panel.up_rate_value.text() == "—"
    assert panel.down_rate_value.text() == "—"
```

`tests/test_main_window.py`：

```python
import pytest


@pytest.fixture
def window(qtbot):
    from views.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    w.reconnect_manager.cancel()


def test_connect_button_disabled_without_credentials(window):
    window.username_input.setText("")
    window.password_input.setText("")
    assert not window.connect_button.isEnabled()
    assert window.connect_button.toolTip() != ""


def test_connect_button_enabled_after_filling_credentials(window):
    window.username_input.setText("2024000001")
    window.password_input.setText("secret")
    assert window.connect_button.isEnabled()


def test_log_toggle_reveals_output(window, monkeypatch):
    monkeypatch.setattr("utils.motion_utils.reduce_motion", lambda: True)
    assert not window.output_text.isVisible()
    window.log_toggle.setChecked(True)
    assert window.output_text.isVisible()
    window.log_toggle.setChecked(False)
    assert not window.output_text.isVisible()


def test_accent_button_uses_bit_green(window):
    from common import theme

    assert theme.semantic_color("accent").lower() in window.connect_button.styleSheet().lower()
```

- [ ] **Step 3: 跑测试确认失败**

```bash
uv run pytest tests/test_status_panel.py tests/test_main_window.py -v
```

预期：FAIL（status_panel 模块不存在）。

- [ ] **Step 4: 实现 status_panel.py**

```python
# app/views/status_panel.py
"""状态仪表盘：状态标题、时长、虚拟 IP、速率。

代理模式拿不到速率计数（内核不暴露），速率卡片恒显示 "—"；TUN 模式后续接入。
"""
from datetime import datetime

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from common import theme
from utils.motion_utils import animate_label_color
from views.busy_spinner import BusySpinner


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class StatusPanel(QWidget):
    def __init__(self, server_text: str = "", parent=None):
        super().__init__(parent)
        self._connected_since: datetime | None = None
        self._countdown_remaining = 0
        self._retry_attempt = 0

        layout = QVBoxLayout()
        layout.setSpacing(10)

        # ---- 状态行：spinner + 圆点 + 大标题 + 服务器 ----
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.spinner = BusySpinner(self)
        status_row.addWidget(self.spinner)
        self.status_dot = QLabel("●")
        status_row.addWidget(self.status_dot)
        self.status_text = QLabel("未连接")
        self.status_text.setFont(theme.status_title_font())
        status_row.addWidget(self.status_text)
        status_row.addStretch()
        self.server_label = QLabel(server_text)
        self.server_label.setFont(theme.card_title_font())
        status_row.addWidget(self.server_label)
        layout.addLayout(status_row)

        # ---- 2×2 圆角卡片 ----
        grid = QGridLayout()
        grid.setSpacing(8)
        self._card_frames = []
        self.duration_value = self._add_card(grid, 0, 0, "连接时长", "00:00:00")
        self.ip_value = self._add_card(grid, 0, 1, "虚拟 IP", "—")
        self.up_rate_value = self._add_card(grid, 1, 0, "↑ 上行速率", "—")
        self.down_rate_value = self._add_card(grid, 1, 1, "↓ 下行速率", "—")
        layout.addLayout(grid)

        self.setLayout(layout)

        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._tick)

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)

        self.refresh_theme()

    def _add_card(self, grid, row, col, title, initial):
        frame = QFrame()
        frame.setObjectName("statCard")
        card = QVBoxLayout(frame)
        card.setContentsMargins(12, 8, 12, 8)
        card.setSpacing(2)
        title_label = QLabel(title)
        title_label.setFont(theme.card_title_font())
        title_label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")
        value_label = QLabel(initial)
        value_label.setFont(theme.card_value_font())
        card.addWidget(title_label)
        card.addWidget(value_label)
        grid.addWidget(frame, row, col)
        self._card_frames.append(frame)
        return value_label

    def refresh_theme(self):
        """深浅色切换时刷新所有依赖主题色的样式。"""
        for frame in self._card_frames:
            frame.setStyleSheet(
                f"QFrame#statCard {{ background-color: {theme.card_background()};"
                f" border-radius: 10px; }}"
            )
        self.server_label.setStyleSheet(f"color: {theme.semantic_color('secondary_text')};")

    def _set_status(self, text: str, color_name: str):
        self.status_text.setText(text)
        animate_label_color(self.status_dot, theme.semantic_color(color_name))

    def _tick(self):
        if self._connected_since:
            self.duration_value.setText(
                _fmt_duration(int((datetime.now() - self._connected_since).total_seconds()))
            )

    def _countdown_tick(self):
        self._countdown_remaining = max(0, self._countdown_remaining - 1)
        self.status_text.setText(
            f"连接中断，{self._countdown_remaining}s 后第 {self._retry_attempt} 次重连…"
        )
        if self._countdown_remaining == 0:
            self._countdown_timer.stop()

    # ---- 对外状态接口 ----

    def set_connecting(self):
        self._countdown_timer.stop()
        self._set_status("连接中…", "working")
        self.spinner.start()

    def set_connected(self, virtual_ip: str):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._connected_since = datetime.now()
        self._set_status("已连接", "connected")
        self.ip_value.setText(virtual_ip)
        self._duration_timer.start()

    def set_reconnecting(self, attempt: int, delay: float):
        self.spinner.stop()
        self._retry_attempt = attempt
        self._countdown_remaining = int(delay)
        self._set_status(
            f"连接中断，{self._countdown_remaining}s 后第 {attempt} 次重连…", "working"
        )
        self._countdown_timer.start()

    def set_reconnect_paused(self):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._set_status("自动重连已暂停（连续失败 3 次），请手动连接", "error")

    def set_disconnected(self, reason: str = ""):
        self.spinner.stop()
        self._countdown_timer.stop()
        self._connected_since = None
        self._duration_timer.stop()
        self._set_status(reason or "未连接", "error" if reason else "idle")
        self.ip_value.setText("—")
        self.duration_value.setText("00:00:00")
        self.up_rate_value.setText("—")
        self.down_rate_value.setText("—")
```

- [ ] **Step 5: 跑面板测试确认通过**

```bash
uv run pytest tests/test_status_panel.py -v
```

预期：8 个用例全 PASS。

- [ ] **Step 6: main_window.py 重构**

`setup_ui` 整体替换（删除 Task 5 的 status_panel 桩与旧布局）：

```python
    def setup_ui(self):
        from common import theme
        from utils.credential_utils import load_credentials
        from utils.motion_utils import animated_height_toggle
        from views.status_panel import StatusPanel

        self.setMinimumSize(360, 480)
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # 状态仪表盘
        self.status_panel = StatusPanel(server_text=self.server_address)
        layout.addWidget(self.status_panel)

        # 凭据区（两整行，连接中禁用）
        saved_username, saved_password = load_credentials()

        user_row = QHBoxLayout()
        user_row.addWidget(QLabel("用户名"))
        self.username_input = QLineEdit()
        self.username_input.setText(saved_username)
        self.username_input.setPlaceholderText("学号/工号")
        user_row.addWidget(self.username_input)
        layout.addLayout(user_row)

        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel("密码"))
        self.password_input = QLineEdit()
        self.password_input.setText(saved_password)
        self.password_input.setEchoMode(QLineEdit.Password)
        pass_row.addWidget(self.password_input)
        layout.addLayout(pass_row)

        opt_row = QHBoxLayout()
        self.remember_cb = QCheckBox("记住密码")
        self.remember_cb.setChecked(self.remember)
        self.remember_cb.stateChanged.connect(self.save_credentials)
        opt_row.addWidget(self.remember_cb)
        self.show_password_cb = QCheckBox("显示密码")
        self.show_password_cb.stateChanged.connect(
            lambda checked: toggle_password_visibility(self.password_input, checked)
        )
        opt_row.addWidget(self.show_password_cb)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # 连接按钮（BIT 绿 accent，按下即时加深反馈）
        self.connect_button = QPushButton("连接")
        self.connect_button.setCheckable(True)
        self.connect_button.setMinimumHeight(38)
        self.connect_button.setCursor(Qt.PointingHandCursor)
        self.connect_button.setAttribute(Qt.WA_AlwaysShowToolTips)  # 禁用态也显示 tooltip
        # 小号次要退出按钮（grilling 确认保留旧 UI 元素；须在 _apply_button_style 前创建）
        self.exit_button = QPushButton("退出")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.clicked.connect(self.quit_app)
        self._apply_button_style()
        self.connect_button.toggled.connect(
            lambda: self.start_connection()
            if self.connect_button.isChecked()
            else self.stop_connection()
        )
        self.connect_button.toggled.connect(
            lambda: self.connect_button.setText("断开")
            if self.connect_button.isChecked()
            else self.connect_button.setText("连接")
        )
        self.connect_button.toggled.connect(self.save_credentials)
        self.connect_button.toggled.connect(
            lambda checked: self.username_input.setDisabled(checked)
        )
        self.connect_button.toggled.connect(
            lambda checked: self.password_input.setDisabled(checked)
        )
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.connect_button, 1)
        btn_row.addWidget(self.exit_button)
        layout.addLayout(btn_row)

        # 内联校验：凭据不全即禁用（连接中保持可点以便断开）
        self._animated_height_toggle = animated_height_toggle
        self.username_input.textChanged.connect(self._refresh_connect_button)
        self.password_input.textChanged.connect(self._refresh_connect_button)
        self._refresh_connect_button()

        # 折叠日志区（默认收起，高度动画可中途反向）
        self.log_toggle = QToolButton()
        self.log_toggle.setText("运行日志")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(False)
        self.log_toggle.setArrowType(Qt.RightArrow)
        self.log_toggle.setStyleSheet("QToolButton {border: none;}")
        self.log_toggle.toggled.connect(self._toggle_log)
        layout.addWidget(self.log_toggle)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setVisible(False)
        self.output_text.document().setMaximumBlockCount(5000)  # B9: 日志上限
        layout.addWidget(self.output_text)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # 深浅色切换时刷新样式
        theme.on_scheme_changed(self._apply_button_style)
        theme.on_scheme_changed(self.status_panel.refresh_theme)

    def _apply_button_style(self):
        from common import theme

        self.connect_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.semantic_color("accent")};
                color: {theme.semantic_color("accent_text")};
                border: none;
                border-radius: 6px;
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton:pressed {{
                background-color: {theme.semantic_color("accent_pressed")};
            }}
            QPushButton:disabled {{
                background-color: {theme.semantic_color("idle")};
                color: {theme.semantic_color("accent_text")};
            }}
        """)
        # 退出按钮：次要样式（无边框灰字），随深浅色刷新
        self.exit_button.setStyleSheet(
            f"QPushButton {{ color: {theme.semantic_color('secondary_text')};"
            f" border: none; padding: 8px 12px; }}"
        )

    def _refresh_connect_button(self):
        filled = bool(self.username_input.text() and self.password_input.text())
        self.connect_button.setEnabled(filled or self.connect_button.isChecked())
        self.connect_button.setToolTip("" if filled else "请输入用户名和密码")

    def _toggle_log(self, expanding):
        self.log_toggle.setArrowType(Qt.DownArrow if expanding else Qt.RightArrow)
        self._animated_height_toggle(
            self.output_text, expanding, max_height=200, on_frame=self.adjustSize
        )
```

文件顶部 import 补充：`from PySide6.QtCore import QTimer, Qt`、`from PySide6.QtWidgets import QToolButton`。

`__init__` 顺序保持：`load_settings → setup_menubar → setup_ui → 重连接线 → tray`。connect_startup 带凭据校验（B11）：

```python
        if self.connect_startup:
            if self.username_input.text() and self.password_input.text():
                QTimer.singleShot(5000, lambda: self.connect_button.setChecked(True))
            else:
                self.output_text.append(
                    "[BITZH Connect] 已开启启动时自动连接，但未保存凭据，跳过自动连接\n"
                )
```

`start_connection` 开头加防御性校验（与内联校验双保险）：

```python
    if not (window.username_input.text() and window.password_input.text()):
        window.status_panel.set_disconnected("请输入用户名和密码")
        return
```

- [ ] **Step 7: 全量回归 + 有屏目检**

```bash
uv run pytest tests/ -v
uv run app/main.py
```

预期：测试全过。有屏目检清单：
- 空凭据时连接按钮置灰、悬停有提示；填满后变 BIT 绿
- 深浅色切换（macOS 系统外观）后按钮/卡片/状态色正确跟随
- 展开/收起日志：高度动画平滑，动画中途反向点击能立即反向（无跳变）
- 系统设置开启"减少动态效果"后重开 app：日志直接切换、连接中无旋转弧

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: redesign main window as status dashboard with BIT brand theme, animated collapsible log and inline validation"
```

---

### Task 9: 杂项修复包（B6、B7、B10、B12）

**Files:**
- Modify: `app/utils/startup_utils.py`
- Modify: `app/services/update_service.py`
- Modify: `app/utils/tray_utils.py`
- Modify: `app/common/version.py`
- Modify: `app/views/advanced_panel.py`

- [ ] **Step 1: B6 — macOS 登录项检测修复**

`startup_utils.py` 的 `get_launch_at_login` Darwin 分支：

```python
    elif system() == "Darwin":
        try:
            app_path = sys.argv[0]
            if ".app/Contents/MacOS/" in app_path:
                app_path = app_path.split(".app/Contents/MacOS/")[0] + ".app"
            app_name = os.path.basename(app_path).replace(".app", "")
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get the name of every login item'],
                capture_output=True, text=True,
            )
            return app_name in result.stdout
        except subprocess.SubprocessError:
            return False
```

（与 `set_launch_at_login` 同款的路径推导，保证打包后名字对得上。）

同时修 plan 遗漏的品牌换皮点：Windows 分支注册表值名 `"HITSZ Connect Verge"` → `APP_NAME`（import 自 constants，`set_launch_at_login` 与 `get_launch_at_login` 两处都要改）。

- [ ] **Step 2: B7 — 更新检查竞态修复**

`update_service.py` 的 `UpdateService`：

```python
class UpdateService:
    """Service to handle update checking and notifications"""

    def __init__(self):
        self.thread_pool = QThreadPool()
        self._workers = []  # 持有引用，防止 QRunnable 自动删除后信号丢失

    def check_for_updates(self, current_version):
        worker = UpdateChecker(current_version)
        self._workers.append(worker)
        worker.signals.update_available.connect(
            lambda _v, w=worker: self._workers.remove(w)
        )
        # 延迟到事件循环下一轮再 start：调用方先连信号，消除竞态
        QTimer.singleShot(0, lambda: self.thread_pool.start(worker))
        return worker.signals
```

文件顶部 import 加 `QTimer`。

- [ ] **Step 3: B10 — 托盘文案**

`tray_utils.py`：`connect_action = QAction("系统代理", menu)` → `QAction("VPN 连接", menu)`。

- [ ] **Step 4: B12 — version.py 兜底**

```python
    except Exception as e:
        print(f"Error reading version from resource: {e}", file=sys.stderr)
        return "0.0.0"
```

- [ ] **Step 5: advanced_panel.py BITZH 默认值 + 自动重连开关**

- `self.server_input = QLineEdit("vpn.hitsz.edu.cn")` → `QLineEdit(DEFAULT_SERVER)`（import 自 constants）
- `self.dns_input = QLineEdit("10.248.98.30")` → `QLineEdit("")`，placeholder `留空则禁用远端 DNS`
- 通用 tab 追加开关：

```python
        self.auto_reconnect_switch = QCheckBox("断线自动重连")
        self.auto_reconnect_switch.setToolTip("非认证失败导致的掉线将自动重连，连续失败 3 次后暂停")
        general_layout.addWidget(self.auto_reconnect_switch)
```

- `get_settings` 返回 dict 加 `"auto_reconnect": self.auto_reconnect_switch.isChecked()`
- `set_settings` 签名加 `auto_reconnect=True` 并 `self.auto_reconnect_switch.setChecked(auto_reconnect)`
- `menu_utils.show_advanced_settings` 的 `dialog.set_settings(...)` 调用与 `if dialog.exec():` 后的取值同步加 `auto_reconnect`，并赋给 `window.auto_reconnect` + `window.reconnect_manager.set_enabled(...)`

- [ ] **Step 6: 回归 + 有屏目检**

```bash
uv run pytest tests/ -v && uv run app/main.py
```

预期：测试全过；高级设置通用页有"断线自动重连"开关且默认勾选；托盘菜单显示"VPN 连接"。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "fix: macOS login-item detection, update-check race, tray label, version fallback; add auto-reconnect toggle"
```

---

### Task 10: CI、打包与 README

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `setup.iss`
- Modify: `README.md`、`README.zh-CN.md`
- Modify: `app/resources/icons/`（新图标）
- Modify: `app/common/resources.py`（重新生成）

- [ ] **Step 1: workflow 全局替换与内核升级**

`release.yml`：
- zju-connect 下载 URL 中 `v0.9.0` → `v1.3.1`
- `HITSZ Connect Verge` → `BITZH Connect`（app 名、bundle 名、DMG 卷名、product-name、file-description）
- 产物文件名 `hitsz-connect-verge-*` → `bitzh-connect-*`
- Linux deb：`Package: bitzh-connect`、`/usr/lib/bitzh-connect`、`/usr/bin/bitzh-connect`、desktop 文件同步改名
- macOS app 改名后 `mv dist/main.app dist/BITZH\ Connect.app`

- [ ] **Step 2: setup.iss**

```iss
#define MyAppName "BITZH Connect"
#define MyAppPublisher "BITZH Connect"
#define MyAppURL "https://github.com/GtJerry111/bitzh-connect"
#define MyAppExeName "main.exe"
```

**AppId 必须换新 GUID**（与上游不同，避免共存冲突），例如：
`AppId={{B7E2A1C4-3F5D-4E8A-9C1B-2D6F8A0E5B3D}`
`OutputBaseFilename=bitzh-connect-windows-{#Architecture}-setup`
`[Registry]` 卸载清理键：`Software\{#MyAppPublisher}\{#MyAppName}`（与新 QSettings 名一致）。

- [ ] **Step 3: 用 BIT 校徽素材生成图标**

素材：`/Users/jerry/Projects/素材/BIT_emblem_from_example9_fixed_v2.png`（1198×1198 彩色校徽透明底）和 `BITemblem.png`（黑白校徽，用于 macOS 托盘 mask 图标）。

设计：深绿 `#005C31` 圆角底板 + 校徽居中缩放到 80%——校徽内圈与底板同绿融为一体，铜色外环自然成为图标边框。

```bash
uv add --group dev pillow
```

```python
# scripts/gen_icons.py（一次性脚本，uv run python scripts/gen_icons.py 执行）
from PIL import Image, ImageDraw

EMBLEM_SRC = "/Users/jerry/Projects/素材/BIT_emblem_from_example9_fixed_v2.png"
MONO_SRC = "/Users/jerry/Projects/素材/BITemblem.png"
BRAND_GREEN = "#005C31"
SIZE = 1024

# ---- 主图标：深绿圆角底板 + 校徽居中 ----
base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [0, 0, SIZE, SIZE], radius=int(SIZE * 0.225), fill=255  # macOS squircle 近似
)
plate = Image.new("RGBA", (SIZE, SIZE), BRAND_GREEN)
base.paste(plate, (0, 0), mask)

emblem = Image.open(EMBLEM_SRC).convert("RGBA")
inner = int(SIZE * 0.80)
emblem = emblem.resize((inner, inner), Image.LANCZOS)
base.paste(emblem, ((SIZE - inner) // 2, (SIZE - inner) // 2), emblem)

base.save("app/resources/icons/icon.png")
base.save(
    "app/resources/icons/icon.ico",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)

# ---- macOS 托盘 mask 图标：黑白校徽 44px（22pt @2x）----
mono = Image.open(MONO_SRC).convert("RGBA")
mono.resize((44, 44), Image.LANCZOS).save("app/resources/icons/menu-icon.png")
```

macOS icns（标准 iconutil 流程）：

```bash
mkdir -p /tmp/bitzh.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s app/resources/icons/icon.png --out /tmp/bitzh.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) app/resources/icons/icon.png --out /tmp/bitzh.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns /tmp/bitzh.iconset -o app/resources/icons/icon.icns
```

托盘引用改为 PNG（`tray_utils.py` macOS 分支：`:/icons/menu-icon.svg` → `:/icons/menu-icon.png`，`setIsMask(True)` 逻辑不变）；`app/resources/resources.qrc` 中 `menu-icon.svg` 行替换为 `<file>icons/menu-icon.png</file>`。

目检：缩小到 64px 看校徽可辨识度——若外圈文字糊成噪点属正常（官方校徽在小尺寸同样如此），只要铜环 + 绿心 + 白鸽轮廓清晰即可。

- [ ] **Step 4: 重新生成 Qt 资源并验证**

```bash
uv run pyside6-rcc app/resources/resources.qrc -o app/common/resources.py
uv run app/main.py   # 确认图标正常、窗口标题 BITZH Connect
```

- [ ] **Step 5: README 改写**

两个 README 改为 BITZH 版：服务器 `112.91.150.228`、SOCKS5 `1080`、HTTP `1081`；Clash 配置示例里 `hitsz.edu.cn` 规则改为 `bitzh.edu.cn`；明确致谢上游（kowyo/hitsz-connect-verge、Mythologyli/zju-connect）；注明"非官方、小范围使用"。

- [ ] **Step 6: 全量回归 + Commit**

```bash
uv run pytest tests/ -v
git add -A && git commit -m "build: bump zju-connect core to v1.3.1, rename artifacts to bitzh-connect, new icon and README"
```

- [ ] **Step 7: 打 tag 验证 CI（可选，需要已推送 fork）**

```bash
git tag v1.0.0 && git push origin main --tags
```

到 fork 的 Actions 页确认 6 个平台构建通过、release 产物名称为 `bitzh-connect-*`。

---

### Task 11: 真实环境验证清单（手动，不可 mock）

**前置：** 本地下载 zju-connect v1.3.1 macOS 二进制到 `app/core/`（CI 会下，本地开发手动放）：

```bash
mkdir -p app/core
curl -L "https://github.com/Mythologyli/zju-connect/releases/download/v1.3.1/zju-connect-darwin-arm64.zip" -o /tmp/zju-connect.zip
unzip -o /tmp/zju-connect.zip -d app/core && chmod +x app/core/zju-connect
sudo xattr -rd com.apple.quarantine app/core/zju-connect
```

逐项验证（用真实 BITZH 账号）：

- [ ] **1. 正常连接**：填账号密码 → 连接 → 仪表盘显示"已连接"、虚拟 IP、时长走动；浏览器设代理 127.0.0.1:1081 或开启"自动配置代理"后能访问校内资源
- [ ] **2. 认证失败校准**：故意填错密码 → 观察日志框中内核输出的**实际错误行** → 若为 `log_parser.py` 未覆盖的新表述，把模式补进 `AUTH_FAILURE_PATTERNS` 并加一条对应单测 → 仪表盘应显示"认证失败"且**不**触发自动重连
- [ ] **3. 自动重连**：连接成功后断开 WiFi 15 秒再恢复 → 应看到"连接中断，Xs 后第 n 次重连…"→ 自动恢复"已连接"
- [ ] **4. 重连暂停**：拔网线放着不管 → 3 次重连失败后显示"自动重连已暂停"；插回网线手动点连接 → 正常连上
- [ ] **5. 特殊字符密码（B1 回归）**：若可临时改密码为含 `!` 或空格的密码验证登录成功；否则以 `tests/test_connection_args.py` 单测为准
- [ ] **6. 代理残留清理（B4 回归）**：连接状态下 `kill -9` 强杀 app → 重新打开 → 日志应出现"已清理上次异常退出残留的系统代理"，且直连网络恢复正常
- [ ] **7. 断开不卡 UI（B5 回归）**：连接中点"断开"，界面应立即响应，无 1-2 秒冻结
- [ ] **8. 启动自动连接**：勾选"启动时自动连接"+ 记住密码 → 重启 app → 约 5 秒后自动连接；取消"记住密码"重启 → 应提示跳过自动连接（B11）
- [ ] **9. 托盘**：最小化到托盘 → 托盘菜单"VPN 连接"勾选状态与窗口按钮同步；退出后系统代理已关闭
- [ ] **10. 更新检查**：菜单"帮助 → 检查更新"→ 指向自己 fork 的 releases（发布 v1.0.0 前先预期提示"已是最新"或失败提示得体）

发现的问题修复后各自单独 commit。

---

## 后续阶段（本期不做，另立计划）

- **TUN 模式**：GUI 加开关 + 提权方案（macOS 用授权执行/osascript，Windows 捆绑 wintun.dll + 按需 UAC），TUN 下速率/流量用 `psutil.net_io_counters` 读虚拟网卡喂给仪表盘；注意与 Clash TUN 的冲突检测与提示（上游 issue #36）
- **连接记录/流量历史**：如需
- **正式图标设计**、代码签名（若转公开发布）
