# app/utils/macos_vibrancy.py
"""NSVisualEffectView 毛玻璃背景（菜单栏面板形态专属）。

原理：面板窗口 WA_TranslucentBackground 透明化后，垫一块 NSVisualEffectView
（popover 材质），Qt 内容直接"浮"在毛玻璃上。
深浅色跟随 App 主题设置（set_appearance 三态），而非只跟系统——用户 App 内
强制浅色/深色时质感与文字颜色不打架。

z-order 关键：Qt 顶层窗口的 NSWindow contentView **就是** QNSView 本身，Qt 内容
画在该视图自己的图层里。若把 effect 作为 contentView 的 subview 添加，subview 恒
画在父视图自身内容之上 → 毛玻璃会盖住全部 Qt 控件。正确做法是加到 contentView 的
父视图（NSNextStepFrame/NSThemeFrame）里、用 NSWindowBelow 定位在 contentView 之下。

桥接模式与 utils/sleep_wake.py 一致；仅 macOS 真实 cocoa 平台；失败安静降级
（面板退化为透明底窗口，由 Qt 侧圆角样式兜底）。

平台守卫必需：offscreen（测试环境）下 winId() 返回 1，拿它构造 NSView 再取
window() 会 SIGSEGV，必须挡在桥接之前。
"""
from platform import system

_NS_VISUAL_EFFECT_MATERIAL_POPOVER = 6
_NS_VISUAL_EFFECT_BLENDING_BEHIND_WINDOW = 0
_NS_VISUAL_EFFECT_STATE_ACTIVE = 1  # 不随窗口失焦变灰（面板本就是瞬时激活）
_NS_WINDOW_BELOW = -1               # NSWindowOrderingMode
# NSAutoresizingMaskOptions：WidthSizable | HeightSizable
_AUTORESIZE = 2 | 16


def _nsview_of(window):
    """QWidget 顶层窗口 → NSView（PySide6 winId 即 NSView 指针）。"""
    import objc

    return objc.objc_object(c_void_p=__import__("ctypes").c_void_p(int(window.winId())))


def install_vibrancy(window, corner_radius: float = 10.0) -> bool:
    """为窗口安装毛玻璃背景（幂等）。

    corner_radius 与面板 QSS 圆角一致；默认 10.0 兼容既有调用。返回是否成功。
    """
    from PySide6.QtWidgets import QApplication

    # 非 cocoa 平台 winId 不是 NSView 指针（offscreen 下为 1），桥接会段错误
    if system() != "Darwin" or QApplication.platformName() != "cocoa":
        return False
    if getattr(window, "_vibrancy_view", None) is not None:
        return True  # 已安装：避免重复 addSubview 造成叠层 + 旧 view 失控
    try:
        import objc

        view = _nsview_of(window)
        ns_window = view.window()
        content = ns_window.contentView()  # 即 QNSView，Qt 内容画在它自己的图层
        host = content.superview()  # NSNextStepFrame / NSThemeFrame
        if host is None:
            return False  # 拿不到 content 的父视图就无法垫在其下方（宁可不安也不盖内容）
        effect_cls = objc.lookUpClass("NSVisualEffectView")
        # frame 取 content 在其父视图坐标系中的位置，与 content 完全重合
        effect = effect_cls.alloc().initWithFrame_(content.frame())
        effect.setAutoresizingMask_(_AUTORESIZE)
        effect.setMaterial_(_NS_VISUAL_EFFECT_MATERIAL_POPOVER)
        effect.setBlendingMode_(_NS_VISUAL_EFFECT_BLENDING_BEHIND_WINDOW)
        effect.setState_(_NS_VISUAL_EFFECT_STATE_ACTIVE)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(corner_radius)
        effect.layer().setMasksToBounds_(True)
        # 关键：置于 host 中、contentView 之下（不能加到 contentView 里，否则盖住内容）
        host.addSubview_positioned_relativeTo_(effect, _NS_WINDOW_BELOW, content)
        # 防 GC + 供移除/更新时查找
        window._vibrancy_view = effect
        update_vibrancy_appearance(window)
        return True
    except Exception:
        return False


def remove_vibrancy(window) -> None:
    """移除毛玻璃（切回浮动模式时调用；未安装时安静返回）。"""
    effect = getattr(window, "_vibrancy_view", None)
    if effect is None:
        return
    window._vibrancy_view = None
    try:
        effect.removeFromSuperview()
    except Exception:
        pass


def update_vibrancy_appearance(window) -> None:
    """深浅色跟随 App 主题（theme.is_dark 已含 system/light/dark 三态解析）。"""
    effect = getattr(window, "_vibrancy_view", None)
    if effect is None or system() != "Darwin":
        return
    try:
        import objc

        from common import theme

        name = "NSAppearanceNameDarkAqua" if theme.is_dark() else "NSAppearanceNameAqua"
        effect.setAppearance_(
            objc.lookUpClass("NSAppearance").appearanceNamed_(name)
        )
    except Exception:
        pass
