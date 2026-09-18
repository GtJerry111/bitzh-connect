"""液态玻璃 Spike：验证 NSGlassEffectView 垫层在 Qt 面板窗口中的真实效果。

用法（项目根目录）：
    .venv/bin/python scripts/glass_spike.py [--style regular|clear] [--appearance system|light|dark]

真机验收清单（逐条确认后在 plan 回填结论）：
1. 玻璃垫层正常渲染：折射/边缘高光肉眼可见，且不盖住 Qt 控件（z-order 正确）
2. regular vs clear 两档各跑一次对比，选定默认档（记录选择：______）
3. 深浅色切换（点窗口内"切换深浅色"按钮，模拟 App 内强制切换）玻璃质感正确跟随
4. 校训水印（右侧竖排）叠在玻璃上：可读、不脏
5. 把窗口拖到花壁纸 / 纯深色 / 纯浅色背景上：次要灰字（"副标题样本"）可读
6. 反复点"收起/展开"按钮：透明度动画播放时玻璃不闪不破
7. 窗口失焦（点击桌面）时玻璃不变灰死（玻璃无 state 概念，预期恒活跃——确认实际表现）
8. 关闭脚本后无残留进程/崩溃
"""
import argparse
import signal
import sys

import objc
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

# Ctrl+C 直接终止：Cocoa runloop 不把 SIGINT 交回 Python（与 menu_bar_spike.py 同款）
signal.signal(signal.SIGINT, signal.SIG_DFL)

sys.path.insert(0, "app")
import common.resources  # noqa: F401 注册 qrc（水印素材）

_NS_WINDOW_BELOW = -1
_AUTORESIZE = 2 | 16  # WidthSizable | HeightSizable
_STYLE = {"regular": 0, "clear": 1}  # NSGlassEffectStyleRegular / Clear


def install_glass(window, style: int) -> bool:
    """垫 NSGlassEffectView 到 contentView 父视图、contentView 之下（z-order 关键）。"""
    try:
        import ctypes

        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(window.winId())))
        content = view.window().contentView()
        host = content.superview()
        if host is None:
            print("FAIL: contentView 无父视图")
            return False
        glass_cls = objc.lookUpClass("NSGlassEffectView")
        glass = glass_cls.alloc().initWithFrame_(content.frame())
        glass.setAutoresizingMask_(_AUTORESIZE)
        glass.setCornerRadius_(10.0)
        glass.setStyle_(style)
        host.addSubview_positioned_relativeTo_(glass, _NS_WINDOW_BELOW, content)
        window._glass = glass  # 防 GC
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        return False


def set_glass_appearance(window, dark: bool):
    glass = getattr(window, "_glass", None)
    if glass is None:
        return
    name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
    glass.setAppearance_(objc.lookUpClass("NSAppearance").appearanceNamed_(name))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", choices=["regular", "clear"], default="regular")
    parser.add_argument("--appearance", choices=["system", "light", "dark"],
                        default="system")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])  # 只传程序名：避免 Qt 把 --style 当自身选项吞掉并告警
    try:
        objc.lookUpClass("NSGlassEffectView")
    except Exception:
        print("本机无 NSGlassEffectView（macOS < 26）——spike 不适用")
        return 1

    win = QWidget(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
    win.setAttribute(Qt.WA_TranslucentBackground, True)
    win.setFixedWidth(360)
    layout = QVBoxLayout(win)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)

    title = QLabel("液态玻璃 Spike")
    title.setStyleSheet("font-size: 20pt; font-weight: 600; color: #1D1D1F;")
    layout.addWidget(title)
    sub = QLabel("副标题样本：次要灰字可读性验证")
    sub.setStyleSheet("font-size: 13pt; color: #606066;")
    layout.addWidget(sub)
    layout.addWidget(QLineEdit(placeholderText="输入框样本（含中文输入法测试）"))
    btn = QPushButton("连接")
    btn.setMinimumHeight(38)
    btn.setStyleSheet(
        "QPushButton { background: #005C31; color: white; border-radius: 6px;"
        " font-size: 13pt; font-weight: 600; }"
        "QPushButton:pressed { background: #004A26; padding-top: 1px; }"
    )
    layout.addWidget(btn)

    state = {"dark": False}
    toggle = QPushButton("切换深浅色（验证玻璃跟随）")
    def _toggle():
        state["dark"] = not state["dark"]
        set_glass_appearance(win, state["dark"])
    toggle.clicked.connect(_toggle)
    layout.addWidget(toggle)

    hide_btn = QPushButton("收起/展开（验证动画中玻璃表现）")
    def _hide_show():
        if win.isVisible():
            win.setWindowOpacity(0.0)
            win.hide()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(600, lambda: (win.setWindowOpacity(1.0), win.show()))
    hide_btn.clicked.connect(_hide_show)
    layout.addWidget(hide_btn)

    # 水印（右下小图，验证玻璃上的叠加效果）
    from PySide6.QtGui import QPixmap
    from PySide6.QtCore import Qt as _Qt
    wm = QLabel()
    pix = QPixmap(":/brand/motto.png")
    if not pix.isNull():
        wm.setPixmap(pix.scaledToHeight(120, _Qt.SmoothTransformation))
        wm.setStyleSheet("background: transparent;")
        wm.setAlignment(_Qt.AlignRight)
    layout.addWidget(wm)

    # 多屏时 Qt 可能把窗口默认放到副屏（用户看不到）：显式居中于主屏顶部
    win.adjustSize()
    _avail = QApplication.primaryScreen().availableGeometry()
    win.move(_avail.center().x() - win.width() // 2, _avail.top() + 60)

    win.show()
    win.raise_()
    win.activateWindow()
    ok = install_glass(win, _STYLE[args.style])
    print(f"glass installed: {ok}, style={args.style}", flush=True)
    if args.appearance != "system":
        set_glass_appearance(win, args.appearance == "dark")
    # Tool 窗口从终端启动时可能被放到不可见 Space：orderFrontRegardless 强制在
    # 当前空间前台显示（NSApp.activateIgnoringOtherApps_ 反而触发 Space 切换藏起窗口）
    try:
        import ctypes

        view = objc.objc_object(c_void_p=ctypes.c_void_p(int(win.winId())))
        view.window().orderFrontRegardless()
    except Exception as e:
        print(f"orderFrontRegardless failed: {e}", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
