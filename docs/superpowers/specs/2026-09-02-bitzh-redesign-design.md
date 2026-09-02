# BITZH Connect UI 重设计 + 修复包 设计文档

> 来源：2026-09-02 真实环境测试反馈 + grilling 结论。本文档是第二轮迭代的设计定稿，基于 `2026-09-01-bitzh-connect.md` 计划已完成的 v1.0.0 基础。

## 背景

第一轮实现（仪表盘卡片风）真实使用后反馈"一般、不优雅"，且暴露若干缺陷。经可视化方案对比（A 系统设置风 / B 极简大状态居中 / C 品牌头图风），**用户选定方案 B**。

## 已锁定决策（grilling + 可视化确认）

| # | 决策 | 结论 |
|---|---|---|
| 1 | 设计方向 | 方案 B：极简大状态居中（状态为唯一主角，统计无边框纯文字） |
| 2 | 资源页形态 | 连接成功后内嵌在仪表盘（不整页替换、不放托盘） |
| 3 | 资源区显隐 | 未连接时隐藏；连接成功瞬间与凭据区"一收一放"（250ms 展开/收起动画，可打断） |
| 4 | 凭据区（连接后） | 动画收起消失；断开后展开回来 |
| 5 | 外观 | app 内加"跟随系统/浅色/深色"三态开关（放高级设置-通用） |
| 6 | 资源内容 | 仅两个：电子图书馆 `http://elib.bitzh.edu.cn:8080/interlibSSO/main/main.jsp`、统一门户 `https://s.bitzh.edu.cn` |
| 7 | 域名补全 | 校内资源横跨 bitzh.edu.cn 与 zhbit.com，Clash 规则/README 补上 zhbit.com |

## 修复包（诊断已完成，随本轮一起修）

| # | 问题 | 根因与修法 |
|---|---|---|
| F1 | 退出时 macOS 弹"python3 quit unexpectedly"（SIGSEGV） | 退出 1.5s 后 macOS teardown 给窗口补发 closeEvent → 访问已 deleteLater 的托盘对象 → Python override 抛异常 → shiboken 在解释器收尾期打印异常时崩溃。修法：`quit_app` 可重入（`_quitting` 标志 + 早退）、`handle_close_event` 先查标志直接 accept、托盘访问加 isValid/RuntimeError 守卫 |
| F2 | Dock 栏显示"python3.11" | main.py 加 `setApplicationName/setApplicationDisplayName(APP_NAME)`；macOS 再试 `NSProcessInfo.setProcessName`（pyobjc）。裸 python 进程的 Dock 悬停标签在 macOS 上可能仍受限，打包成 .app 后必然正确 |
| F3 | "认证失败，请检查用户名和密码"被截断 | 重设计覆盖：hero 状态只放短词（"认证失败"），详细说明放副标题行（小字号、可完整显示） |
| F4 | 登录失败排查（已闭环，非代码问题） | 用户密码记忆有误；协议链路与加密经 Python 复刻验证完全正确，AUTH_FAILURE_PATTERNS 已实测覆盖真实服务器输出（ErrorCode 20004 "Invalid username or password!"） |

## UI 定稿（方案 B）

```
未连接态                          已连接态
┌────────────────────┐          ┌────────────────────┐
│                    │          │        ●(绿+柔光)   │
│        ●(灰)        │          │      已连接         │
│      未连接         │          │  10.0.43.17 · 112.… │
│   112.91.150.228   │          │  时长  上行  下行    │
│                    │          │ 00:12:34 —    —    │
│  时长  上行  下行   │          │ [📖电子图书馆][🏛门户]│ ← 展开动画
│ 00:00:00 —    —   │          │                    │
│                    │          │      [ 断 开 ]      │
│  用户名 ___________ │          │  ▸ 运行日志          │
│  密码  ___________ │          └────────────────────┘
│  ☐记住密码 ☐显示密码 │   ↑ 凭据区整个收起（动画）
│      [ 连 接 ]      │
│  ▸ 运行日志          │
└────────────────────┘
```

**布局规格：**
- 状态 hero 区：14px 圆点 + 26pt Bold 状态词（负字距）+ 12pt 副标题（已连接：`虚拟IP · 服务器`；认证失败：`认证失败` + 副标题完整原因；重连倒计时：`连接中断` + 副标题"Xs 后第 n 次重连…"）。连接中：圆点位置替换为 BusySpinner 旋转弧
- 统计行：时长/上行/下行，无边框纯文字居中，15pt Semibold + tnum，标题 10pt 灰
- 资源区：两个胶囊按钮（BIT 绿描边、文字+图标），点击 `QDesktopServices.openUrl` 打开
- 凭据区：下划线式输入（无边框 QLineEdit + 底部 1px 线），含记住密码/显示密码
- 主按钮：BIT 绿 accent（连接→断开文案切换不变）；小号次要"退出"按钮保留
- 底部：▸ 运行日志折叠区（现有，不动）

**动效（复用 motion_utils 基建）：**
- 连接成功：凭据区 250ms OutCubic 收起 + 资源区 250ms 展开，同时进行；可中途打断（断开立即反向）
- 状态切换：圆点颜色 250ms 过渡（现有 animate_label_color）
- 减少动态效果：全部退化为即时显隐

**状态文案映射（hero 词 + 副标题）：**
| 状态 | hero | 副标题 |
|---|---|---|
| 未连接 | 未连接 | 服务器地址 |
| 连接中 | 连接中… | 服务器地址（spinner 转动） |
| 已连接 | 已连接 | 虚拟IP · 服务器 |
| 认证失败 | 认证失败 | 请检查用户名和密码（完整显示，不截断） |
| 重连等待 | 连接中断 | Xs 后第 n 次重连…（每秒递减） |
| 重连暂停 | 自动重连已暂停 | 连续失败 3 次，请手动连接 |

## 外观三态开关实现

- 高级设置-通用加"外观"下拉：跟随系统（默认）/浅色/深色，存 QSettings `appearance` 键
- 实现：`QStyleHints.setColorScheme(Qt.ColorScheme.*)`（Qt 6.8+；本项 PySide6 6.11 满足），theme.is_dark() 读取处不变（colorScheme 被显式设置后直接反映），切换后触发 on_scheme_changed 刷新所有样式
- 若 setColorScheme 在 macOS 上不完全生效（实测验证），回退方案：pyobjc 设 NSAppearance + 手动 palette

## TUN 模式（本轮纳入，grilling 确认）

**动机**：代理模式下 SSH 等裸 TCP 不走 VPN（系统代理只对浏览器类应用生效），用户的开发服务器（10.8.18.32）日常刚需。官方客户端即 TUN 全局路由。

**内核能力已确认**：zju-connect v1.3.1 带 `--tun-mode`（userspace gVisor netstack）与 `--add-route`。

**设计：**
- 开关：高级设置-网络 tab 加"TUN 模式（全局路由）"，默认关；tooltip 说明需管理员授权 + 与 Clash TUN 互斥
- 提权（本期最简方案，后续可换特权助手）：
  - macOS：包装脚本读参数文件 exec 内核，`osascript do shell script ... with administrator privileges` 启动（连接时弹一次系统授权框）；内核输出重定向到临时日志文件，GUI 从文件 tail 解析状态（CommandWorker 增加"读日志文件"模式，对 handle_output 的输出契约不变）；pid 写 pidfile，断开时再提权 kill
  - Windows：捆绑 wintun.dll + ShellExecute runas（UAC 弹一次）
  - Linux：pkexec
- TUN 模式下跳过系统代理自动配置（全局路由已接管，避免自我回环）
- 速率统计（TUN 专属）：新增 psutil 依赖，`net_io_counters(pernic=True)` 每秒差值读新增 utun 网卡 → 仪表盘上行/下行速率从 "—" 变真数据；代理模式仍显示 "—"
- 冲突检测：连接前查默认路由网卡，若已是 utun/其他 VPN 网卡（如 Clash TUN），弹提示让用户先关闭
- 路由验证（Task 11 项）：TUN 连接后 `ssh czr@10.8.18.32` 不通代理直连必须通；若服务器下发的资源路由不含 10.0.0.0/8，补 OS 级路由

**已知体验折衷**：macOS 每次连接/断开可能各弹一次系统授权框（osascript 方案）。后续阶段换 SMAppServices 特权助手可免密。

## 测试策略

- 现有 62 个测试保持绿；状态面板 API 变化（hero/副标题分离）同步更新 test_status_panel.py / test_main_window.py
- 新增：资源区展开/收起状态联动测试；外观三态开关持久化测试；F1 退出路径回归测试（可重入、teardown closeEvent 不炸）
- 真实环境验证：Task 11 清单重跑（登录已验证可行）

## 明确不做

- 资源列表不做自定义编辑（用户明确"只需要这两个"）
- 不做毛玻璃/背景图；质感靠字距、留白、层级
- TUN 模式仍不在本期
