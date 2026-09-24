#!/usr/bin/env python3
"""README 截图 demo：mock 已连接态 + 假速率数据，截窗口（含壁纸背景）。

安全边界：
- QSettings 重定向到临时目录——不读、不写真实配置（凭据区始终为空，不会泄露学号）
- 不发起任何真实 VPN 连接（不调 start_connection，无内核进程、无网络流量）
- 屏蔽启动时的检查更新请求

截图方式：窗口移到主屏中央，调系统 screencapture 截「窗口 + 四周壁纸」区域
（Qt 逻辑坐标 × DPR = screencapture 物理像素坐标；双屏下坐标系以主屏左上角
为原点，窗口显式定位到主屏，不会跑到副屏）。

用法（项目根目录）：
    uv run scripts/demo_screenshot.py login            # 未连接态
    uv run scripts/demo_screenshot.py connected        # 已连接 · 浅色
    uv run scripts/demo_screenshot.py connected-dark   # 已连接 · 深色
    uv run scripts/demo_screenshot.py menubar          # 菜单栏液态玻璃面板（macOS）
    uv run scripts/demo_screenshot.py speed-image      # 菜单栏速率显示（macOS）

截图输出到 assets/。
"""

import argparse
import math
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# --- 隔离配置：monkeypatch 配置层为内存实现 ---
# 注意：macOS 上 QSettings.setDefaultFormat(IniFormat)/setPath 实测无效（仍读写
# 真实 plist，会泄露已保存的学号）——因此不碰 QSettings，直接替换 load/save。
# 必须在 import views.main_window 之前 patch：各调用方是 from-import 值绑定，
# patch 完成后再 import，绑定到的就是假实现。
import utils.config_utils as _cu  # noqa: E402

_MEM_STORE: dict = {}


def _fake_load_config() -> dict:
    """与 config_utils.load_config 默认结构保持一致（不落盘、不读盘）。"""
    return {
        "username": "",
        "password": "",
        "cred_salt": "",
        "remember": False,
        "server": _cu.DEFAULT_SERVER,
        "port": _cu.DEFAULT_PORT,
        "dns": _cu.DEFAULT_DNS,
        "auto_dns": True,
        "proxy": True,
        "launch_at_login": False,
        "connect_startup": False,
        "silent_mode": False,
        "check_update": False,
        "hide_dock_icon": False,
        "keep_alive": True,
        "debug_dump": False,
        "disable_multi_line": False,
        "auto_reconnect": True,
        "socks_bind": "1080",
        "http_bind": "1081",
        "cert_file": "",
        "cert_password": "",
        "appearance": _MEM_STORE.get("appearance", "system"),
        "tun_mode": True,
        "nav_expanded": False,
        "menu_bar_speed": False,
        **_MEM_STORE,
    }


def _fake_save_config(config: dict):
    _MEM_STORE.update(config)


_cu.load_config = _fake_load_config
_cu.save_config = _fake_save_config

from common.constants import APP_NAME  # noqa: E402
from views import main_window as _mw_mod  # noqa: E402
from views.main_window import MainWindow  # noqa: E402

# demo 不发更新请求
_mw_mod.MainWindow.check_updates_startup = lambda self: None

ASSETS = ROOT / "assets"
DEMO_IP = "10.254.36.12"          # 假内网 IP
DEMO_DURATION_S = 47 * 60 + 12    # 截图里的连接时长：00:47:12
PAD = 48                          # 窗口四周截入的壁纸宽度（逻辑像素）

random.seed(20260924)  # 可复现的波形


def _demo_rate(t: float) -> tuple[float, float]:
    """类真实流量曲线：基础浏览 2~5 MB/s + 周期性 ~20 MB/s 突发 + 抖动。"""
    base_down = 3.2e6 + 1.4e6 * math.sin(t / 9.0) + 0.6e6 * math.sin(t / 2.7)
    burst = 14e6 * max(0.0, math.sin(t / 22.0)) ** 6
    down = max(0.15e6, base_down + burst + random.uniform(-0.25e6, 0.25e6))
    up = max(0.05e6, down * 0.12 + random.uniform(0, 0.3e6))
    return up, down


def _fmt(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024**2:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / 1024**2:.1f} MB/s"


def _mock_connected(window: MainWindow):
    """进入"已连接"演示态：状态面板 + 60s 波形历史 + 按钮/输入框态 + 菜单栏速率。"""
    from PySide6.QtCore import QSignalBlocker

    sp = window.status_panel
    window.virtual_ip = DEMO_IP  # 菜单栏速率显示的前置条件（正常由连接流程赋值）
    sp.set_graph_supported(True)
    sp.set_connected(DEMO_IP)
    # 时长回填：截图显示一个像样的连接时长而非 00:00:00
    sp._connected_since = datetime.now() - timedelta(seconds=DEMO_DURATION_S)
    sp._tick()  # 立即刷新时长显示（不等 duration_timer 第一拍）

    # 灌满 60s 波形历史（真实连接是每秒一个样本滚出来的）
    for t in range(-59, 1):
        up, down = _demo_rate(float(t))
        sp.append_rate_sample(up, down)

    # 实时通道：每秒喂数，走与真实监控相同的 _on_rates 路径
    # （速率数字 + 波形滚动 + 菜单栏速率三处联动）
    def _tick():
        up, down = _demo_rate(datetime.now().timestamp())
        up_text, down_text = _fmt(up), _fmt(down)
        sp.set_rates(up_text, down_text)
        sp.append_rate_sample(up, down)
        window._last_rates = (up_text, down_text)
        window._update_menu_bar_speed(up_text, down_text)

    timer = QTimer(window)
    timer.setInterval(1000)
    timer.timeout.connect(_tick)
    timer.start()
    _tick()  # 立即补一帧，截图不等第一秒

    # 连接按钮/输入框态（屏蔽信号，绝不触发真实连接）
    blocker = QSignalBlocker(window.connect_button)
    window.connect_button.setChecked(True)
    window.connect_button.setText("断开")
    del blocker
    window.username_input.setEnabled(False)
    window.password_input.setEnabled(False)
    window._apply_connect_button_style(True)


def _move_to_primary_center(window: MainWindow):
    """窗口定位到主屏中央（双屏下确保不落在副屏）。"""
    screen = QApplication.primaryScreen()
    geo = screen.availableGeometry()
    window.move(geo.center() - window.rect().center())


def _grab_region(rect, dpr: float, path: Path):
    """screencapture 截全局区域。

    注意：screencapture -R 的坐标单位是逻辑坐标（points），与 Qt 全局坐标同系；
    输出 PNG 自动按屏幕 DPR 渲染为物理像素（Retina 下 @2x）。勿再乘 DPR。
    """
    x, y = int(rect.x()), int(rect.y())
    w, h = int(rect.width()), int(rect.height())
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["screencapture", "-x", f"-R{x},{y},{w},{h}", str(path)],
        check=True,
    )
    print(f"saved: {path}")


def _grab_widget_with_wallpaper(widget, path: Path, pad: int = PAD, top_zero: bool = False):
    """截控件 + 四周壁纸背景。top_zero=True 时上沿顶到屏幕顶部（含菜单栏）。"""
    rect = widget.frameGeometry()
    dpr = widget.windowHandle().screen().devicePixelRatio()
    x = rect.x() - pad
    y = 0 if top_zero else rect.y() - pad
    bottom = rect.bottom() + pad
    from PySide6.QtCore import QRect
    from PySide6.QtCore import QPoint

    region = QRect(QPoint(x, y), QPoint(rect.right() + pad, bottom))
    _grab_region(region, dpr, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["login", "connected", "connected-dark", "menubar", "speed-image"])
    args = parser.parse_args()

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    app = QApplication(sys.argv[:1])

    # 外观：写入内存配置，构造时自动应用（与真实路径一致）
    appearance = {"connected-dark": "dark"}.get(args.mode, "light")
    _MEM_STORE["appearance"] = appearance

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    _move_to_primary_center(window)

    def _take():
        if args.mode in ("connected", "connected-dark", "menubar", "speed-image"):
            _mock_connected(window)
            # 等校训淡入(250ms)与波形 scale 动画稳定
            QTimer.singleShot(1000, _finish)
        else:
            _finish()

    def _finish():
        dpr = window.windowHandle().screen().devicePixelRatio()
        if args.mode == "menubar":
            # 开启菜单栏速率（右键菜单同款开关），面板镜像更饱满
            window.set_menu_bar_speed(True)
            window.toggle_panel()  # 展开液态玻璃快捷面板

            def _shoot_panel():
                panel = window._menu_bar_panel
                panel.raise_()
                # 上沿顶到屏幕顶部：菜单栏（含本应用图标+速率）与面板同框
                _grab_widget_with_wallpaper(panel, ASSETS / "screenshot-menubar.png", top_zero=True)
                app.quit()

            QTimer.singleShot(500, _shoot_panel)  # 等慢开动画(300ms)落定
        elif args.mode == "speed-image":
            window.set_menu_bar_speed(True)

            def _shoot_icon():
                item = getattr(window, "_mac_status_item", None)
                rect = item.icon_global_rect() if item else None
                if rect is None:
                    print("状态栏图标定位失败，跳过")
                    app.quit()
                    return
                from PySide6.QtCore import QRect, QPoint

                region = QRect(
                    QPoint(rect.x() - 4, 0),
                    QPoint(rect.right() + 6, rect.bottom() + 4),
                )
                _grab_region(region, dpr, ASSETS / "screenshot-menubar-speed.png")
                app.quit()

            QTimer.singleShot(1200, _shoot_icon)  # 等速率刷上状态栏
        else:
            name = {"login": "screenshot-login",
                    "connected": "screenshot-connected",
                    "connected-dark": "screenshot-connected-dark"}[args.mode]
            _grab_widget_with_wallpaper(window, ASSETS / f"{name}.png")
            app.quit()

    QTimer.singleShot(800, _take)  # 等首帧布局/字体稳定
    app.exec()


if __name__ == "__main__":
    main()
