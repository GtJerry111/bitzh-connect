# app/utils/macos_vibrancy.py
"""NSVisualEffectView 毛玻璃背景（菜单栏面板形态专属）。

原理：面板窗口 WA_TranslucentBackground 透明化后，在其 NSWindow contentView
最底层垫一块 NSVisualEffectView（popover 材质），Qt 内容直接"浮"在毛玻璃上。
深浅色跟随 App 主题设置（set_appearance 三态），而非只跟系统——用户 App 内
强制浅色/深色时质感与文字颜色不打架。

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
_CORNER_RADIUS = 10.0


def _nsview_of(window):
    """QWidget 顶层窗口 → NSView（PySide6 winId 即 NSView 指针）。"""
    import objc

    return objc.objc_object(c_void_p=__import__("ctypes").c_void_p(int(window.winId())))


def install_vibrancy(window) -> bool:
    """为窗口安装毛玻璃背景（幂等）。返回是否成功。"""
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
        content = ns_window.contentView()
        effect_cls = objc.lookUpClass("NSVisualEffectView")
        effect = effect_cls.alloc().initWithFrame_(content.bounds())
        effect.setAutoresizingMask_(_AUTORESIZE)
        effect.setMaterial_(_NS_VISUAL_EFFECT_MATERIAL_POPOVER)
        effect.setBlendingMode_(_NS_VISUAL_EFFECT_BLENDING_BEHIND_WINDOW)
        effect.setState_(_NS_VISUAL_EFFECT_STATE_ACTIVE)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(_CORNER_RADIUS)
        effect.layer().setMasksToBounds_(True)
        content.addSubview_positioned_relativeTo_(effect, _NS_WINDOW_BELOW, None)
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
