"""NSGlassEffectView 液态玻璃背景（macOS 26+ 菜单栏面板形态专属）。

与 macos_vibrancy.py 同构：垫层置于 contentView 父视图（NSThemeFrame）、
contentView 之下——z-order 是关键，加成 contentView 的 subview 会盖住全部
Qt 内容（vibrancy 真机实测结论，直接复用）。

版本路由由 glass_available() 特性检测承担：类存在即 macOS 26+；
macOS 15 及以下 lookUpClass 抛错 → 调用方回退 vibrancy（现状不动）。

与 vibrancy 的差异：玻璃无 material/state 概念（恒活跃，折射由系统管理），
圆角走 cornerRadius 属性（不需 wantsLayer + layer mask）。
深浅色跟随 App 主题设置（set_appearance 三态），与 vibrancy 行为一致。

平台守卫必需：offscreen（测试环境）下 winId() 返回 1，桥接会 SIGSEGV。
"""
from platform import system

from PySide6.QtWidgets import QApplication

from utils.macos_vibrancy import _nsview_of

_NS_WINDOW_BELOW = -1    # NSWindowOrderingMode
_NS_WINDOW_ABOVE = 1
_AUTORESIZE = 2 | 16     # WidthSizable | HeightSizable
# NSGlassEffectView.Style：0=Regular（乳白标准玻璃）1=Clear（清透强折射，壁纸渗色多）
GLASS_STYLE_REGULAR = 0
GLASS_STYLE_CLEAR = 1


def _cocoa() -> bool:
    """真实 cocoa 平台且 QApplication 已实例化（无实例时 platformName 谎报 cocoa）。"""
    if QApplication.instance() is None:
        return False
    return system() == "Darwin" and QApplication.platformName() == "cocoa"


def glass_available() -> bool:
    """NSGlassEffectView 是否可用（macOS 26+ 且真实 cocoa 平台）。"""
    if not _cocoa():
        return False
    try:
        import objc

        objc.lookUpClass("NSGlassEffectView")
        return True
    except Exception:
        return False


def install_glass(
    window, corner_radius: float = 10.0,
    style: int = GLASS_STYLE_REGULAR, interactive: bool = False,
) -> bool:
    """为窗口安装液态玻璃背景（幂等）。

    corner_radius 与面板 QSS 圆角一致（HIG：圆角连续）；默认 10.0 兼容既有调用。
    style：Regular（默认，乳白）/ Clear（清透强折射，菜单栏面板定稿 Clear——
    真机 A/B 对比 BetterDisplay 参考图后选定）。
    interactive：官方 effectIsInteractive，玻璃对悬停/按压有光学响应。
    返回是否成功；失败由调用方回退 vibrancy。
    """
    if not glass_available():
        return False
    if getattr(window, "_glass_view", None) is not None:
        return True  # 已安装：避免重复 addSubview 叠层
    try:
        import objc

        view = _nsview_of(window)
        content = view.window().contentView()  # 即 QNSView，Qt 内容画在它自己的图层
        host = content.superview()
        if host is None:
            return False  # 无法垫在内容之下时宁可不安（绝不盖内容）
        glass_cls = objc.lookUpClass("NSGlassEffectView")
        # frame 与 content 完全重合；autoresize 跟随窗口尺寸
        glass = glass_cls.alloc().initWithFrame_(content.frame())
        glass.setAutoresizingMask_(_AUTORESIZE)
        glass.setCornerRadius_(corner_radius)
        glass.setStyle_(style)
        if interactive:
            glass.setEffectIsInteractive_(True)
        # 关键：置于 host 中、contentView 之下（不能加到 contentView 里）
        host.addSubview_positioned_relativeTo_(glass, _NS_WINDOW_BELOW, content)
        window._glass_view = glass  # 防 GC + 供移除/更新时查找
        update_glass_appearance(window)
        return True
    except Exception:
        return False


def remove_glass(window) -> None:
    """移除玻璃（未安装时安静返回）。"""
    glass = getattr(window, "_glass_view", None)
    if glass is None:
        return
    window._glass_view = None
    try:
        glass.removeFromSuperview()
    except Exception:
        pass


# ---- 玻璃件（clear 玻璃元素：卡片/按钮，置于底板之上、Qt 内容之下） ----


def install_glass_piece(window, widget, corner_radius: float = 14.0,
                        interactive: bool = True) -> bool:
    """为窗口内 widget 区域安装 clear 玻璃件（液态玻璃元素，对标参考图卡片/按钮）。

    z-order：底板（regular）在下，玻璃件在其上，Qt 内容（contentView）最上——
    因此 widget 自身须保持透明（QSS 填充只作回退）。frame 跟随 widget 几何，
    由调用方在布局变化时驱动 sync_glass_piece（面板在 LayoutRequest 统一同步）。
    深浅色跟随底板（同窗口 NSAppearance 由 update_glass_appearance 统一管理）。

    返回是否成功；失败（无底板/非 cocoa/桥接异常）安静回退——widget 的
    QSS 填充继续承担材质。
    """
    if not glass_available():
        return False
    base = getattr(window, "_glass_view", None)
    if base is None:
        return False  # 无底板不装玻璃件（材质层级不成立）
    try:
        import objc

        view = _nsview_of(window)
        content = view.window().contentView()
        host = content.superview()
        if host is None:
            return False
        piece = objc.lookUpClass("NSGlassEffectView").alloc().init()
        piece.setStyle_(GLASS_STYLE_CLEAR)
        piece.setCornerRadius_(corner_radius)
        piece.setEffectIsInteractive_(interactive)
        # 底板之上、contentView 之下
        host.addSubview_positioned_relativeTo_(piece, _NS_WINDOW_ABOVE, base)
        widget._glass_piece = piece  # 防 GC + 供同步/移除
        sync_glass_piece(window, widget)
        return True
    except Exception:
        return False


def sync_glass_piece(window, widget) -> None:
    """Qt 几何 → Cocoa frame（y 向上翻转）+ 显隐跟随。

    widget.geometry() 是相对其父级（页面/容器）的坐标，必须 mapTo 窗口坐标系——
    页面/Stack/根布局的偏移漏算会让玻璃件与内容错位。
    """
    piece = getattr(widget, "_glass_piece", None)
    if piece is None:
        return
    try:
        from PySide6.QtCore import QPoint

        view = _nsview_of(window)
        content = view.window().contentView()
        host = content.superview()
        host_h = host.frame().size.height
        pos = widget.mapTo(window, QPoint(0, 0))
        piece.setHidden_(not widget.isVisibleTo(window))
        piece.setFrame_(((pos.x(), host_h - pos.y() - widget.height()),
                         (widget.width(), widget.height())))
    except Exception:
        pass


def remove_glass_piece(widget) -> None:
    """移除玻璃件（未安装时安静返回）。"""
    piece = getattr(widget, "_glass_piece", None)
    if piece is None:
        return
    widget._glass_piece = None
    try:
        piece.removeFromSuperview()
    except Exception:
        pass


def update_glass_appearance(window) -> None:
    """深浅色跟随 App 主题（theme.is_dark 已含 system/light/dark 三态解析）。"""
    glass = getattr(window, "_glass_view", None)
    if glass is None or system() != "Darwin":
        return
    try:
        import objc

        from common import theme

        name = "NSAppearanceNameDarkAqua" if theme.is_dark() else "NSAppearanceNameAqua"
        glass.setAppearance_(
            objc.lookUpClass("NSAppearance").appearanceNamed_(name)
        )
    except Exception:
        pass
