# app/utils/macos_sf_symbols.py
"""SF Symbols 官方图标库桥接（macOS 11+，菜单栏面板专属）。

为什么用官方库：自绘路径（QPainter 线条）图标间描边粗细只能凑近似，
被用户一眼看出"齿轮和电源粗细不一样"；SF Symbols 有官方字重体系
（统一 regular 档），且矢量渲染 Retina 天然清晰。

链路：NSImage.imageWithSystemSymbolName → 模板图（黑 + alpha）→ 离屏 2x 渲染
→ QImage → Qt 侧 SourceIn 按主题色着色（深浅色即换色参数，缓存自然分流）。

平台守卫：非 macOS / 非 cocoa（offscreen 测试）/ 符号缺失 → 返回 None，
调用方回退自绘路径（Linux CI 与旧系统即走回退）。
"""
from platform import system

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

# _draw_icon 的语义名 → SF Symbol 名（单一事实源，两侧共用）
SF_NAMES = {
    "gear": "gearshape",
    "power": "power",
    "swap": "arrow.left.arrow.right",
    "grid": "square.grid.2x2",
    "window": "macwindow",
    "chevron_right": "chevron.right",
    "chevron_down": "chevron.down",
    "chevron_left": "chevron.left",
}

_CACHE = {}


def _cocoa() -> bool:
    """真实 cocoa 平台且 QApplication 已实例化（offscreen 下不触碰 AppKit）。"""
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        return False
    return system() == "Darwin" and QApplication.platformName() == "cocoa"


def _render_template(name: str, canvas: int) -> QImage | None:
    """SF Symbol 自然尺寸居中画进 canvas×canvas pt 离屏画布 → QImage（黑+alpha）。

    lockFocus 跟随主屏 2x backing store，TIFF 即 2x 像素；SF Symbols 是矢量
    字形，该路径不产生位图缩放。
    """
    try:
        import objc

        ns_image = objc.lookUpClass("NSImage")
        config_cls = objc.lookUpClass("NSImageSymbolConfiguration")
    except Exception:
        return None
    try:
        sym = ns_image.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if sym is None:
            return None
        # 13pt + Regular（NSFontWeightRegular=0.0）。真机 A/B：Light(-0.4) 在小尺寸
        # 下偏虚、缺"可点"的形，磨砂底上尤其弱；Regular 与系统控件观感一致。
        config = config_cls.configurationWithPointSize_weight_(13.0, 0.0)
        sym = sym.imageWithSymbolConfiguration_(config)
        sym.setTemplate_(True)  # 模板图：黑色 + alpha，颜色留给 Qt 侧
        sw, sh = sym.size()  # pyobjc 返回 tuple
        canvas_img = ns_image.alloc().initWithSize_((canvas, canvas))
        canvas_img.lockFocus()
        sym.drawAtPoint_fromRect_operation_fraction_(
            ((canvas - sw) / 2, (canvas - sh) / 2),
            ((0, 0), (0, 0)),  # NSZeroRect = 全图
            2,  # NSCompositingOperationSourceOver
            1.0,
        )
        canvas_img.unlockFocus()
        qimg = QImage()
        if not qimg.loadFromData(bytes(canvas_img.TIFFRepresentation())):
            return None
        return qimg
    except Exception:
        return None


def sf_symbol_pixmap(kind: str, size: int, color: str) -> QPixmap | None:
    """语义名（gear/power/swap/grid/window/chevron_right）→ 着色 QPixmap。

    size 为逻辑 pt（输出为 2x 像素、dpr=2，Qt 按逻辑尺寸绘制）。
    按 (kind, size, color) 缓存；不可用返回 None（调用方回退自绘）。
    """
    name = SF_NAMES.get(kind)
    if name is None or not _cocoa():
        return None
    key = (kind, size, color)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    qimg = _render_template(name, size)
    if qimg is None:
        return None
    # 纯像素域着色，dpr 最后才标——避免绘制期的逻辑/物理像素换算
    base = QPixmap.fromImage(qimg)  # 1x，尺寸 = 实际像素（2*size）
    tinted = QPixmap(base.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    tinted.setDevicePixelRatio(2.0)  # 逻辑尺寸 = size pt（retina 清晰）
    _CACHE[key] = tinted
    return tinted
