"""动效工具：减少动态效果检测 + 可打断的过渡动画。

原则（Apple 流体界面指南）：
- 非手势状态切换一律 250ms OutCubic，不用弹性（无动量场景弹性是错误的）
- 所有动画可打断：从当前展示值（presentation value）重启，不回跳
- 系统开启"减少动态效果"时全部退化为即时切换
"""
from platform import system

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QVariantAnimation
from PySide6.QtGui import QColor

ANIMATION_DURATION_MS = 250


def reduce_motion() -> bool:
    """系统级"减少动态效果"开关。读不到的平台返回 False。"""
    try:
        if system() == "Darwin":
            import objc

            workspace = objc.lookUpClass("NSWorkspace").sharedWorkspace()
            return bool(workspace.accessibilityDisplayShouldReduceMotion())
        if system() == "Windows":
            import ctypes
            import ctypes.wintypes

            enabled = ctypes.wintypes.BOOL(False)
            # SPI_GETCLIENTAREAANIMATION = 0x1042
            ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
            return not enabled.value
    except Exception:
        return False
    return False


def animate_label_color(label, target: str, duration: int = ANIMATION_DURATION_MS):
    """标签颜色平滑过渡。可打断：从当前展示颜色出发（记录在 label._theme_color）。"""
    if reduce_motion():
        label.setStyleSheet(f"color: {target};")
        label._theme_color = target
        return None

    start = getattr(label, "_theme_color", None) or label.palette().color(
        label.foregroundRole()
    ).name()
    anim = QVariantAnimation(label)
    anim.setDuration(duration)
    anim.setStartValue(QColor(start))
    anim.setEndValue(QColor(target))
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.valueChanged.connect(lambda c: label.setStyleSheet(f"color: {c.name()};"))

    def _store():
        label._theme_color = target

    anim.finished.connect(_store)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    label._color_anim = anim  # 持有引用防 GC
    return anim


def animated_height_toggle(widget, expanding: bool, max_height: int = 200,
                           duration: int = ANIMATION_DURATION_MS, on_frame=None):
    """展开/收起 widget 的高度动画。

    可打断：再次调用时从当前实际高度重启（QPropertyAnimation 会自动停掉同属性旧动画）。
    on_frame: 每帧回调（例如主窗口 adjustSize，让窗口高度随内容平滑变化）。
    """
    if reduce_motion():
        widget.setMaximumHeight(16777215)
        widget.setVisible(expanding)
        if on_frame:
            on_frame()
        return None

    start_h = widget.height() if widget.isVisible() else 0
    if expanding:
        widget.setVisible(True)

    anim = QPropertyAnimation(widget, b"maximumHeight", widget)
    anim.setDuration(duration)
    anim.setStartValue(start_h)
    anim.setEndValue(max_height if expanding else 0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    if on_frame:
        anim.valueChanged.connect(lambda _v: on_frame())

    def _finish():
        widget.setMaximumHeight(16777215)
        if not expanding:
            widget.setVisible(False)

    anim.finished.connect(_finish)
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._height_anim = anim
    return anim
