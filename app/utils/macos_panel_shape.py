# app/utils/macos_panel_shape.py
"""面板窗口圆角：让系统窗口阴影跟随玻璃圆角，消除四角方形阴影残留。

现象：面板玻璃本身圆角正确（NSGlassEffectView.cornerRadius=22），但四角仍有
小直角。根因是 NSWindow 恒为矩形，macOS 按**矩形窗口边界**生成窗口阴影，
方形阴影从 22px 圆角玻璃外露出。invalidateShadow() 无效；把窗口 frame 视图
（contentView 的父视图）也设成同半径圆角 + masksToBounds 后，阴影随圆角走。

切回浮动形态必须还原（去掉 mask/radius），否则普通窗口四角会被裁掉。

仅真实 cocoa 平台生效；offscreen/非 macOS/桥接失败安静跳过。
"""
from platform import system

_CORNER_RADIUS = 22.0  # 与面板 QSS 圆角、玻璃 cornerRadius 一致


def _cocoa_window(window):
    """→ (ns_window, frame_view)；不可用时返回 (None, None)。"""
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None or QApplication.platformName() != "cocoa":
        return None, None
    if system() != "Darwin":
        return None, None
    from utils.macos_vibrancy import _nsview_of

    view = _nsview_of(window)
    ns_window = view.window()
    content = ns_window.contentView() if ns_window is not None else None
    return ns_window, (content.superview() if content is not None else None)


def round_panel_window(window, radius: float = _CORNER_RADIUS) -> bool:
    """给窗口 frame 视图套圆角，使窗口阴影跟随玻璃圆角。返回是否成功。"""
    try:
        ns_window, host = _cocoa_window(window)
        if ns_window is None or host is None:
            return False
        host.setWantsLayer_(True)
        layer = host.layer()
        layer.setCornerRadius_(float(radius))
        layer.setMasksToBounds_(True)
        ns_window.setOpaque_(False)
        ns_window.invalidateShadow()
        window._panel_frame_rounded = True
        window._panel_frame_radius = float(radius)
        return True
    except Exception:
        return False


def restore_window_shape(window) -> None:
    """还原窗口 frame（切回浮动形态时调用；未圆角过则安静返回）。"""
    if not getattr(window, "_panel_frame_rounded", False):
        return
    window._panel_frame_rounded = False
    try:
        ns_window, host = _cocoa_window(window)
        if host is None:
            return
        layer = host.layer()
        if layer is not None:
            layer.setMasksToBounds_(False)
            layer.setCornerRadius_(0.0)
        if ns_window is not None:
            ns_window.invalidateShadow()
    except Exception:
        pass
