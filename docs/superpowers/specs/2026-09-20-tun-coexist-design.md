# TUN 与其他 TUN（Clash/FlClash）共存

日期：2026-09-20
状态：已评审（方案 A）
参考：Mythologyli/zju-connect 源码（`stack/tun/stack_darwin.go`、`underlay/dialer.go`）、
真机路由表（macOS，FlClash/mihomo 内核）

## 1. 背景与目标

现状：本软件 TUN 与其他代理工具的 TUN 被文档与代码双双定义为「互斥」——
`app/utils/tun_utils.py:28` `check_tun_conflict()` 检测到默认路由落在 `utun*`/`tun*`
即中止连接（`connection_utils.py:227-238`），README 亦写明互斥。

真实诉求（已确认）：用户**按 IP 直连校园服务器**（SSH / 远程桌面等）必须用本软件的
TUN；同时希望保留 FlClash（mihomo 内核）的 TUN 上外网。两者要能同时开。

### 关键事实（源码 + 真机）

1. **zju-connect 的 TUN 不抢默认路由**：`stack_darwin.go` 里 `tun.Options{AutoRoute: false}`，
   只按服务端下发 IP 段调 `route -n add -net <prefix> -interface utunN` 加**明细路由**；
   本软件还没传 `-dns-hijack`，连系统 DNS 都不劫持。→ 天然适合「各管各的路由」。
2. **FlClash/mihomo 抢流量但不占默认路由**：真机路由表里 `default` 仍在物理网卡 `en0`，
   mihomo 用 `1/8 + 2/7 + 4/6 + 8/5 + 16/4 + 32/3 + 64/2 + 128/1` 这一串明细路由覆盖
   `1.0.0.0 ~ 255.255.255.255`（唯独放过 `0.0.0.0/8`），把流量拐进 `utun5`。
3. **VPN 服务器 IP 会被截走**：服务器 `112.91.150.228` 落在 `64.0.0.0/2` 内，会被
   FlClash 的 utun5 截走。本软件底层连接（打到服务器）若走系统路由就会进 FlClash 的 TUN
   → 隧道起不来。**这是真正要解决的问题**。
4. **旧检测抓不到 FlClash**：`check_tun_conflict()` 只看 `default` 是否在 utun，而 FlClash
   把 default 留在 en0，所以该检测对 FlClash 无效——结论：旧检测的判据本身就错了。
5. **内核支持底层绑定物理网卡**：`underlay/dialer.go` 的 `Options.InterfaceName` 会把
   underlay socket 绑到指定网卡（`IP_BOUND_IF`），**绕过路由表**，正是为此场景设计。

### 目标

- 检测到「去 VPN 服务器的流量会被他方 TUN 截走」时，把内核底层连接显式绑定到物理网卡
  （`-bind-interface <iface>`），实现两 TUN 并存。
- 保证「IP 直连校园服务器」在本软件 TUN + 他方 TUN 同时运行时可达。

### 非目标

- 不保证域名类校园资源（对方 fake-ip / DNS 劫持下的域名分流）——本场景按 IP 直连。
- 不动 FlClash/mihomo 配置，不改 `zju-connect` 内核二进制，不支持 Windows。
- 不引入「本软件 TUN 抢默认路由」（内核未暴露该开关）。

## 2. 方案（A · 共存模式）

```
[应用/系统流量]
   ├─ 校园网段明细路由 ──► 本软件 utun（zju-connect，只加这类路由）
   └─ 其余（他方 TUN 明细 / 默认） ──► FlClash utun5 / en0
[本软件 → VPN 服务器 112.91.150.228] ──► -bind-interface en0（绕过 FlClash 路由）
```

1. 用更准确的判据替换旧检测：查**服务器 IP 的路由出口**是否为 `utun*`。
2. 命中时探测主物理网卡，给内核追加 `-bind-interface <iface>`。
3. 不再硬拦；改日志提示「共存模式」。

## 3. 组件与接口

### `app/utils/tun_utils.py`

- `capturing_tun_for(server_ip: str) -> str | None`
  - 返回会把该 IP 的流量截进 TUN 的网卡名；无则 `None`。
  - macOS：`route -n get <ip>` → 解析 `interface: utunX`；仅 `utun*` 算命中。
  - Linux：`ip route get <ip>` → 解析 `dev utunX`/`tunX`；`wg*` 不误伤。
  - 命令失败/解析失败 → `None`（安静降级）。
- `physical_interface() -> str | None`
  - macOS：`scutil --nwi` → 解析 `Network interfaces: en0` 首个；
    失败回退 `route -n get default` 的 `interface:`（排除 utun）。
  - Linux：回退 `ip route show default` 的 `dev`（排除 tun/utun）；拿不到返回 `None`。
- 纯解析函数（供单测，输入样例文本）：
  - `_parse_route_get_interface(text) -> str | None`
  - `_parse_scutil_nwi(text) -> str | None`
- 删除 `check_tun_conflict()`（判据错误，且唯一调用点在 `connection_utils`）。

### `app/utils/connection_utils.py`

- `build_command_args(window, command, tun_bind_interface: str | None = None)`
  - `tun_mode` 时追加 `-bind-interface <iface>`（`tun_bind_interface` 非空才加）。
- `start_connection(window)`
  - TUN 分支前先算共存信息：
    ```
    bind_iface = None
    if tun_mode:
        captured = capturing_tun_for(window.server_address)
        if captured:
            bind_iface = physical_interface()
            <日志：检测到 captured，已启用共存模式（底层绑定 bind_iface 或告警）>
    ```
  - 删除硬拦截（`conflict → _reset_connect_ui` 早退）与 `"与 X 的 TUN 冲突"` 文案。
  - Windows 硬守卫不变。
  - 探测失败（拿不到物理网卡）→ 日志告警但继续（不绑定，可能连不上，由用户判断）。
- import 从 `check_tun_conflict` 换成 `capturing_tun_for` / `physical_interface`。

### `app/views/advanced_panel.py`

- TUN 说明文案：「与 Clash TUN 模式互斥」→「可与 Clash/FlClash 的 TUN 共存（按 IP
  直连校园网；需对方未开启严格路由）」。

### `README.md`

- §TUN 模式 NOTE 第 2 条由「互斥」改为共存说明。

## 4. 行为矩阵

| 场景 | 行为 |
|---|---|
| 无他方 TUN | 与现状一致：不传 `-bind-interface` |
| 他方 TUN 截走服务器流量 + 探测到物理网卡 | 传 `-bind-interface`，日志提示共存模式 |
| 他方 TUN 截走 + 探测不到物理网卡 | 日志告警，继续（可能失败） |
| 他方 TUN 开启「严格路由」(pf) | `-bind-interface` 也绕不过；文档注明需关闭 |
| Windows | 硬守卫不变（TUN 不可用） |

## 5. 测试

- 解析器单测：`_parse_route_get_interface`（macOS 样例）、`_parse_scutil_nwi`（样例）、
  Linux `ip route get` 样例。
- `capturing_tun_for`：mock 命令输出 → 命中 utun / 不命中物理网卡 / 异常返回 None。
- `physical_interface`：mock `scutil` 输出；回退分支。
- `build_command_args`：`tun_bind_interface` 非空 → 参数含 `-bind-interface <iface>`；
  为空 → 不含。
- `start_connection` 共存路径：monkeypatch 探测函数，断言传给 `build_command_args`
  的绑定参数非空、且**不再早退**（worker 被创建）。
- 既有两个用例改造：`test_tun_conflict_aborts_before_spawn`（不再早退）、
  `test_stale_spawn_done_stops_orphan_kernel`（探测桩改名）。

真机验证（人工）：
1. FlClash TUN 开启；
2. 本软件 TUN 连接；
3. `ssh czr@10.8.18.32` 可达；
4. 外层外网（如浏览器/`curl` 到公网）仍走 FlClash 正常。

## 6. 风险与对策

- **物理网卡漂移**（Wi-Fi 切换 / 热点）：绑定的网卡在连接期失效 → 需重连；文档注明。
- **对方路由更具体**：校园网段若是 `/8` 级明细，比对方 `/2` 更具体，本软件胜出；
  极端情况下对方显式加了校园网段路由则会打架（不自作聪明，交由用户）。
- **对方 fake-ip + 域名访问**：非目标；只保证 IP 直连。
- **Linux 平台**：探测与绑定 best-effort，拿不到物理网卡则不绑定。
- **权限**：`-bind-interface` 不增加权限需求，提权模型不变。

## 7. 修订记录

- 2026-09-20：初稿（方案 A 评审通过）。
- 2026-09-20：真机验证通过（FlClash utun5 + 本软件 utun11 共存；校园走 utun11、服务器仍 utun5、
  外网正常）。暴露「app 非正常终止 → root 内核与校园路由残留」问题，追加 §8。

## 8. 异常退出清理（真机反馈追加）

**现象**：app 被非正常终止（关终端 / Ctrl-C / 崩溃）时，root 内核与校园明细路由残留，
需手动 `sudo pkill`。正常点「断开」不受影响（停止标记机制工作正常）。

**根因**：正常断开时 app 写停止标记，root 守护脚本收掉内核并清理临时文件；非正常终止
时无人写标记，守护脚本一直等待，内核成孤儿。

**方案（两个都做）**：
1. **退出信号处理**（`app/utils/shutdown.py`）：接管 `SIGINT`/`SIGTERM`/`SIGHUP`，
   处理器只置标志，`QTimer`（200ms）在 Qt 事件循环里触发 `window.quit_app` → 写停止标记。
2. **启动自愈扫描**（`sweep_orphan_tun()`）：启动时扫 `TMPDIR/bitzh-tun-*.pid`——
   pid 存活则写 `.stop` 交给仍在等待的 root 守护脚本；pid 已死则删残留，
   并清理 launcher 脚本/日志（脚本内嵌命令行含密码，必须删）。

覆盖：Ctrl-C、关终端（SIGHUP）、kill（SIGTERM）、崩溃/断电（靠启动扫描）。
多实例并存不在目标内（单实例假设）。
