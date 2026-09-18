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
_AUTORESIZE = 2 | 16     # WidthSizable | HeightSizable
_GLASS_STYLE = 0         # NSGlassEffectStyleRegular（spike 选定；clear=1）


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


def install_glass(window, corner_radius: float = 10.0) -> bool:
    """为窗口安装液态玻璃背景（幂等）。

    corner_radius 与面板 QSS 圆角一致（HIG：圆角连续）；默认 10.0 兼容既有调用。
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
        glass.setStyle_(_GLASS_STYLE)
        # 关键：置于 host 中、contentView 之下（不能加到 contentView 里）
        host.addSubview_positioned_relativeTo_(glass, _NS_WINDOW_BELOW, content)
        window._glass_view = glass  # 防 GC + 供移除/更新时查找
        update_glass_appearance(window)
        return True
    except Exception:
        return False


def remove_glass(window) -> None:
    """移除玻璃（切回浮动模式时调用；未安装时安静返回）。"""
    glass = getattr(window, "_glass_view", None)
    if glass is None:
        return
    window._glass_view = None
    try:
        glass.removeFromSuperview()
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
