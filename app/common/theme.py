"""语义化设计 tokens：颜色随深浅色自适应，字体层级统一。

品牌色取自 BIT 视觉识别系统（素材/COLOR_USAGE 色卡）：
- 深绿 #005C31（校徽中心）→ 浅色模式 accent
- 标准绿 #16AE68（树）→ 深色模式 accent / 已连接状态
"""
import sys
from platform import system

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


# 显式外观覆盖：None = 跟随系统；"light"/"dark" = app 内强制。
# offscreen 等平台上 setColorScheme 是 no-op，is_dark 须以此变量为准。
_APPEARANCE_OVERRIDE = None


def is_dark() -> bool:
    """当前是否为深色模式。显式外观覆盖优先；Linux 桌面可能不报告，退回 palette 亮度判断。"""
    if _APPEARANCE_OVERRIDE is not None:
        return _APPEARANCE_OVERRIDE == "dark"
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


_REFRESH_CALLBACKS = []
_scheme_signal_connected = False


def on_scheme_changed(callback):
    """深浅色切换（含 app 内外观切换）时回调。同一回调只注册一次。"""
    global _scheme_signal_connected
    if callback not in _REFRESH_CALLBACKS:  # 同一回调重复注册无意义且会重复触发
        _REFRESH_CALLBACKS.append(callback)
    if not _scheme_signal_connected:
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda _scheme: _run_refresh()
        )
        _scheme_signal_connected = True


def _run_refresh():
    alive = []
    for cb in list(_REFRESH_CALLBACKS):
        try:
            cb()
        except RuntimeError as e:
            if "Internal C++ object" in str(e):
                continue  # 回调绑定的 C++ 对象已销毁（如已关闭的窗口），剔除
            # 活回调自身抛的 RuntimeError 不得误剔：打印保留，下次仍触发
            print(f"[theme] 刷新回调执行异常（已保留注册）: {e}", file=sys.stderr)
        alive.append(cb)
    _REFRESH_CALLBACKS[:] = alive


def set_appearance(mode: str):
    """外观三态：system / light / dark。

    Qt 6.8+ setColorScheme 显式覆盖（Unknown = 跟随系统，macOS cocoa 实测可正确复位），
    同时维护 _APPEARANCE_OVERRIDE 供 is_dark 兜底（offscreen 平台 setColorScheme 无效）。
    随后手动触发一次刷新（setColorScheme 不一定发 colorSchemeChanged）。
    macOS 窗口标题栏用 NSAppearance 跟随。
    """
    global _APPEARANCE_OVERRIDE
    if mode not in ("system", "light", "dark"):
        mode = "system"  # 配置被手改坏时回退跟随系统，不崩
    _APPEARANCE_OVERRIDE = None if mode == "system" else mode
    scheme = {
        "system": Qt.ColorScheme.Unknown,
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }[mode]
    QGuiApplication.styleHints().setColorScheme(scheme)
    if system() == "Darwin":
        try:
            import objc

            nsapp = objc.lookUpClass("NSApplication").sharedApplication()
            if mode == "system":
                nsapp.setAppearance_(None)
            else:
                name = "NSAppearanceNameDarkAqua" if mode == "dark" else "NSAppearanceNameAqua"
                nsapp.setAppearance_(objc.lookUpClass("NSAppearance").appearanceNamed_(name))
        except Exception:
            pass
    _run_refresh()


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
        # QFont.Tag / setFeature 为 Qt 6.7+ API；PySide6 6.11 下裸字符串 tag 会抛 ValueError
        f.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError, ValueError):
        pass
    return f


def hero_font() -> QFont:
    """方案 B 状态大词：26pt Bold，负字距。"""
    f = QFont()
    f.setPointSize(26)
    f.setWeight(QFont.Bold)
    f.setLetterSpacing(QFont.PercentageSpacing, 97)
    return f
