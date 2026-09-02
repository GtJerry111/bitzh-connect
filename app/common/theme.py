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
