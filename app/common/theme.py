"""语义化设计 tokens：颜色随深浅色自适应，字体层级统一。

品牌色严格取自 BIT 视觉识别系统（素材/ai/COLOR_USAGE A4-03 色卡实测采样）：
- 深绿 #005C31（校徽中心）→ 浅色模式 accent / 已连接状态
- 标准绿 #009944（树）→ 深色模式 accent / 已连接状态
- 赭石 #A23F0D（校园建筑）→ 进行中状态（连接中/重连）
交互态用官方明度色阶取色（90%=微亮 hover、30%=disabled 衰减），
不引入色卡之外的临时色（仅 error 保留系统红、idle 保留系统灰）。
"""
import sys
from platform import system

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

# BIT VI 官方明度色阶（A4-03，100%→10% 实测采样值）
DEEP_GREEN = ["#005C31", "#00663B", "#227248", "#497F58", "#658E6A",
              "#809E7F", "#9AB096", "#CDD8CB", "#E7ECE6"]
STD_GREEN = ["#009944", "#00A151", "#00A960", "#3FB370", "#69BD83",
             "#88C897", "#A5D4AD", "#D5EAD8", "#ECF5ED"]
OCHRE = ["#A23F0D", "#AA501E", "#B26230", "#BB7444", "#C4865A",
         "#CE9A72", "#D8AD8C", "#ECD7C5", "#F6ECE3"]

_COLORS = {
    #                 light            dark
    "idle":           ("#8E8E93",      "#98989D"),      # 未连接灰
    "working":        (OCHRE[0],       OCHRE[3]),       # 进行中：赭石（深色用 70% 提亮）
    "connected":      (DEEP_GREEN[0],  STD_GREEN[0]),   # 已连接：与 accent 同绿（同屏不单二绿）
    "error":          ("#FF3B30",      "#FF453A"),      # 失败红（色卡无红，沿用系统语义色）
    "accent":         (DEEP_GREEN[0],  STD_GREEN[0]),   # 主按钮：深绿 / 标准绿
    "accent_hover":   (DEEP_GREEN[1],  STD_GREEN[1]),   # 悬停微亮：90% 明度
    "accent_pressed": ("#004A26",      DEEP_GREEN[0]),  # 按下加深（浅色）/ 换深绿族（深色）
    "accent_text":    ("#FFFFFF",      "#000000"),      # accent 上的文字
    "accent_disabled": (DEEP_GREEN[7], DEEP_GREEN[2]),  # 禁用：30% 明度衰减 / 深色 80%
    "secondary_text": ("#606066",      "#98989D"),      # 次要信息灰（浅色 5.3:1 对比）
    "ink":            ("#1D1D1F",      "#F5F5F7"),      # 主文字（hero 词未连接态）
    "separator":      ("#D1D1D6",      "#3A3A3C"),      # 分隔线 / 输入框下划线
    "track":          ("#E4E4E8",      "#38383C"),      # 分段控件轨道底
    "pill":           ("#FFFFFF",      "#636366"),      # 分段控件选中药丸
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


def with_alpha(name: str, alpha: float) -> str:
    """语义色 + 透明度 → rgba() 字符串（仅 QSS 上下文——QColor 不认 rgba() 语法）。"""
    light, dark = _COLORS[name]
    hex_color = dark if is_dark() else light
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def qcolor(name: str, alpha: float | None = None) -> QColor:
    """语义色 → QColor（QPainter 上下文；可选透明度）。"""
    color = QColor(semantic_color(name))
    if alpha is not None:
        color.setAlphaF(alpha)
    return color


def card_title_font() -> QFont:
    """统计行标题 / 说明行：12pt（真机反馈整体字体偏小的上调）。"""
    f = QFont()
    f.setPointSize(12)
    return f


def subtitle_font() -> QFont:
    """hero 副标题：13pt（与 macOS 系统正文字号一致）。"""
    f = QFont()
    f.setPointSize(13)
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
