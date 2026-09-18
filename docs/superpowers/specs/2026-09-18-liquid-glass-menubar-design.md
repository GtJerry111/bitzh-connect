# Liquid Glass 菜单栏面板 + 主窗口重设计

日期：2026-09-18
状态：待评审
参考：BetterDisplay macOS 26 菜单栏面板（液态玻璃范式）

## 1. 背景与目标

现状（重构前）：

- macOS 上「浮动窗口 ↔ 菜单栏面板」是**二选一形态**（`menu_bar_mode` 配置）。
- 面板形态 = 同一个 `MainWindow` 换 flags（FramelessWindowHint|Tool|StaysOnTop）+
  NSGlassEffectView 垫层（macOS 26+），**内容与浮动窗口完全一致**——
  hero 大状态词、下划线输入框、240px 大按钮原样贴到菜单栏下。
- 问题：面板是「窗口范式」而非「菜单范式」——无卡片分区、无行式结构、
  圆角仅 10px，玻璃被 Qt 内容盖得只剩边缘一圈，液态玻璃质感出不来。

目标（用户已逐项确认）：

1. **取消形态二选一**：主窗口是唯一完整 UI，`menu_bar_mode` 退出历史。
   macOS 上 NSStatusItem 常驻；**左键永远弹出快捷面板**（无论主窗口是否可见），
   **右键保持现有三项原生菜单**（打开主窗口 / VPN 连接 / 退出）。
2. **快捷面板是独立新视图**（`MenuBarPanel`），按样例范式重新设计：
   整片液态玻璃 sheet + 卡片二级材质 + 裸行菜单 + 底部工具条。
3. **主窗口卡片化重排 + 整窗液态玻璃**（macOS 26+ NSGlassEffectView，
   旧系统回退 vibrancy 毛玻璃，Windows/Linux 自然降级为白卡纯色底）。
4. 不删减任何现有功能；现有动效、水印联动、校验逻辑全部保留。

非目标：

- Windows/Linux 不做快捷面板（无对应材质与菜单栏惯例），托盘行为保持现状。
- 主窗口布局结构不改（只卡片化分组 + 换材质）。
- 不引入新功能（无波形进面板、无凭据输入进面板）。

## 2. 总体架构变化

```
旧：[menu_bar_mode=False] 浮动窗口 + QSystemTrayIcon
    [menu_bar_mode=True ] MainWindow 变形为面板 + NSStatusItem

新：主窗口（唯一，带玻璃）+ NSStatusItem 常驻（macOS）
      ├─ 左键 → MenuBarPanel.toggle()（独立 QWidget，Tool 无边框）
      └─ 右键 → 原生 NSMenu（打开主窗口 / VPN 连接 / 退出）
```

- `menu_bar_mode` 配置项删除；高级设置中的形态开关一并移除。
  旧配置残留键读取时忽略（不报错、不迁移）。
- Dock 图标：不再因形态强制 Accessory；跟随用户既有 `hide_dock_icon` 设置。
- 主窗口 `closeEvent`：去掉面板模式特例。macOS 上 NSStatusItem 存在即
  「后台驻留」——关闭主窗口 = 隐藏（替代原 tray_visible 判断）；
  其他平台保持现有托盘逻辑。
- macOS 托盘路由简化：不再按形态二选一，**总是创建 NSStatusItem**；
  桥接失败回退 QSystemTrayIcon（现状兜底路径保留）。
- `MainWindow` 上所有「面板形态」代码（`_apply_panel_chrome`、show/hide_panel、
  `_anchor_panel`、WindowDeactivate 收起、`_panel_*` 动画）移除；
  展开/收起动画与失焦收起逻辑迁移到 `MenuBarPanel`。

## 3. 快捷面板 MenuBarPanel

### 3.1 结构（布局 A：裸行式，已定稿）

```
┌────────────────────────────────┐
│ ┌────────────────────────────┐ │  ← 连接卡（半透明白卡，二级材质）
│ │ ● 已连接            [toggle]│ │     状态点 + 状态词 + 副标题 + toggle
│ │   内网 IP 10.8.18.32        │ │
│ │ ─────────────────────────── │ │
│ │  时长      上行      下行    │ │  ← 速率三列（仅已连接态）
│ │  01:23:45 1.2MB/s  856KB/s │ │
│ └────────────────────────────┘ │
│  ⇄ 连接模式            TUN ›  │  ← 裸行（直接在玻璃上）
│  ⊞ 校内导航              ⌄   │  ← 裸行，点击内联展开 chips
│ ┌────────────────────────────┐ │
│ │ 🪟 打开主窗口    (⚙︎) (⏻)  │ │  ← 底部工具条：pill + 圆形按钮
│ └────────────────────────────┘ │
└────────────────────────────────┘
```

### 3.2 视觉规格

- 宽度 300px；圆角 22px（玻璃 cornerRadius 与窗口 frame 圆角同步加大，
  现有 `macos_panel_shape` 的 `_CORNER_RADIUS` 从 10 调整为 22）。
- 背景：复用 `install_glass()`（macOS 26+）；旧系统回退 vibrancy；
  深浅色跟随 App 三态（`update_glass_appearance` 已就绪）。
- 连接卡：浅色 `rgba(255,255,255,0.55)` / 深色 `rgba(64,64,68,0.5)`，
  圆角 14px，`inset 0 0 0 0.5px` 高光描边（QSS border 模拟）。
- 裸行：行高 33px，13pt 文字，图标 + 标签 + 右侧值/chevron；
  行间 0.5px hairline。行图标为单色线条图标（SF Symbols 风格，自绘 SVG/QPainter）。
- 底部工具条：「打开主窗口」pill（玻璃 chip）居左；
  设置 ⚙︎、退出 ⏻ 两个 28px 圆形按钮居右。
- toggle：自绘 macOS 风格开关（QAbstractButton 子类），38×23pt，
  轨道 BIT 绿（`accent`）/ 灰（off），白色圆形 knob 带阴影，切换动画 150ms。
  该控件为面板专用；主窗口保留 240px 按钮式主操作（见 §4.1），不引入 toggle。

### 3.3 状态与交互

- **状态镜像**：面板订阅 `MainWindow` 状态（连接状态、时长、上下行速率、
  模式、服务器地址），不独立持有连接逻辑。toggle 拨动 =
  `main_window.connect_button.setChecked(...)`。
- **未连接态**：灰点 +「未连接」+ toggle off；速率行整段收起；
  副标题显示服务器地址（`112.91.150.228:443`）。
- **连接中**：状态词「连接中」（赭石），toggle 保持 on 侧等待结果
  （失败由主窗口现有收尾复位 toggle，面板镜像跟随）。
- **速率三列**：时长 / ↑上行 / ↓下行，仅已连接显示；复用
  `StatusPanel.set_rates` 同源数据，1s 刷新。
- **无凭据拨 toggle**：toggle 弹回；连接卡副标题位置切换为错误红文案
  「请先在主窗口填写凭据」，3s 后恢复为服务器地址；同时自动打开主窗口
  并聚焦用户名输入框。
- **连接模式行**：点击 → 行右下方弹出**原生 NSMenu**（代理 / TUN 全局路由，
  ✓ 当前项），macOS 26+ 自动液态玻璃。已连接时切换复用现有 bounce 重连。
- **校内导航行**：任意连接状态可点。点击 → chevron 旋转，站点以
  「单字圆标 + 短名」chip 两列网格内联展开（珠海校区 4 / 校本部 6，
  分组小标题），面板顶边钉住、向下增高，250ms 高度动画；
  点击 chip 用系统浏览器打开对应 URL（复用 `NavSection` 的打开逻辑）。
- **展开/收起**：沿用「慢开快收」——展开 220ms 下滑 8px + 淡入，
  收起 160ms 淡出；失焦自动收起；Esc 收起；reduce-motion 直出。
- **定位**：状态栏图标下缘居中（复用 `panel_geometry`），图标失效退化右上角。

## 4. 主窗口改造

### 4.1 卡片化分组（元素零删减）

- **状态卡**：hero（圆点 + 20pt 状态词 + 副标题）居中保留；
  已连接时卡内展开统计三列 + 60s 波形图（现有 RateGraph 移入卡内）。
- **凭据卡**：用户名/密码下划线输入框 + 记住/显示复选，原样移入；
  连接成功收起动画、无凭据校验逻辑不变。
- **导航卡**：NavSection 外套卡片容器，折叠条/展开行为不变。
- **裸置区**：模式分段控件 + 连接按钮（240px 居中）保持裸置——
  主操作区不进卡，视觉焦点不散。
- **底部**：退出/设置文字按钮行不变。
- **断开按钮**：已连接态改为白底绿描边（inset 1.5px accent 边框），
  主操作降级、绿色留给状态；未连接态保持绿色实心「连接」。
- **水印联动不变**：凭据卡可见 → 水印退出；收起 → 水印在玻璃上淡入。

### 4.2 玻璃材质（macOS）

- 主窗口也调 `install_glass()`（macOS 26+），卡片 QSS 换半透明色
  （浅色 `rgba(255,255,255,0.55)` / 深色 `rgba(64,64,68,0.5)`）。
- 窗口圆角跟随系统（macOS 26 窗口默认大圆角），玻璃 cornerRadius 适配系统值；
  不套 `macos_panel_shape` 的自定义圆角（那是无边框面板的方案）。
- macOS 15 及以下：`install_glass` 返回 False → 回退 `install_vibrancy`（现有）。
- Windows/Linux：无玻璃调用，白卡纯色底（视觉即 §3 mockup 左版）。

## 5. 平台与版本矩阵

| 平台 | 主窗口 | 状态栏/托盘 | 快捷面板 |
|---|---|---|---|
| macOS 26+ | 液态玻璃 + 半透卡 | NSStatusItem 常驻 | 液态玻璃面板 |
| macOS ≤15 | 毛玻璃 + 半透卡 | NSStatusItem 常驻 | 毛玻璃面板 |
| Windows | 白卡纯色底 | QSystemTrayIcon（现状） | 无 |
| Linux | 白卡纯色底 | QSystemTrayIcon（现状） | 无 |

NSStatusItem 桥接失败（任意一步异常）→ 回退 QSystemTrayIcon，
此时 macOS 无快捷面板（左键双击唤主窗口，现状逻辑）。

## 6. 技术实现要点

- **复用**：`macos_glass` / `macos_vibrancy` / `macos_status_item` /
  `panel_geometry` / `macos_panel_shape`（仅面板用）全部保留复用。
- **新文件**：
  - `app/views/menu_bar_panel.py`——面板视图（结构、状态镜像、动画）
  - `app/views/toggle_switch.py`——自绘 macOS 风格开关（面板与主窗口共用）
- **改动**：`main_window.py`（移除面板形态代码、卡片化、装玻璃）、
  `tray_utils.py`（NSStatusItem 常驻路由、右键菜单文案「打开面板」→「打开主窗口」）、
  `config_utils.py` / 高级设置对话框（移除 menu_bar_mode 项）、
  `macos_panel_shape.py`（圆角 10→22）。
- **状态同步**：`MenuBarPanel` 持有 `MainWindow` 弱引用，
  面板控件只读主窗口状态 / 调用主窗口公开方法，不复制状态机。
- **测试**：offscreen 平台守卫照旧（玻璃/状态栏项在 offscreen 一律回退）；
  面板状态镜像、模式菜单勾选态、导航展开动画、无凭据弹回路径补单测；
  现有测试（托盘路由、形态切换相关）按新模型更新。

## 7. 风险与对策

- **玻璃上文字可读性**：内容全部承载于半透卡/行内，玻璃上只有图标与短文字；
  深色模式卡片色已含足够不透明度。
- **设置迁移**：`menu_bar_mode=True` 的老用户升级后 = 主窗口 + 状态栏图标，
  无形态开关；行为变化在 release notes 说明。
- **面板高度动画**：导航展开后面板增高，顶边钉住（复用现有
  `_on_content_resize` 思路：adjustSize 后重锚定）。
- **PySide6 自绘 toggle 与原生观感差距**：knob 阴影 + 150ms 缓动已足够接近；
  不追求像素级一致。
