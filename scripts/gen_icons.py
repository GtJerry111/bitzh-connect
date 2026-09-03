# scripts/gen_icons.py
"""一次性图标生成脚本：由 BIT 校徽素材生成应用图标。

设计（候选 C 定稿）：深绿 #005C31 → 标准绿 #009944 竖向渐变 squircle 底板
+ 白色校徽内圈树形（圆形蒙版裁掉外环文字带——小尺寸下文字环只有噪音）。
旧版问题：彩色校徽的赭石外环与深绿底板撞色，且 32px 下细节全糊。

托盘 mask 图标沿用黑白校徽 44px（22pt @2x，供 macOS 菜单栏 setIsMask 使用）。

执行：uv run python scripts/gen_icons.py
"""

import os
import subprocess
import tempfile

from PIL import Image, ImageDraw

EMBLEM_MONO_SRC = "/Users/jerry/Projects/素材/BITemblem.png"
DEEP_GREEN = "#005C31"  # VI 深绿（校徽中心）
STD_GREEN = "#009944"   # VI 标准绿（树）
SIZE = 1024


def squircle_mask(size=SIZE, radius_ratio=0.225):
    """macOS squircle 近似圆角"""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size, size], radius=int(size * radius_ratio), fill=255
    )
    return mask


def gradient_plate():
    """深绿(顶) → 标准绿(底) 竖向渐变 squircle 底板"""
    grad = Image.new("RGBA", (SIZE, SIZE))
    top = tuple(int(DEEP_GREEN[i:i + 2], 16) for i in (1, 3, 5))
    bot = tuple(int(STD_GREEN[i:i + 2], 16) for i in (1, 3, 5))
    px = grad.load()
    for y in range(SIZE):
        t = y / SIZE
        row = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(SIZE):
            px[x, y] = row
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(grad, (0, 0), squircle_mask())
    return out


def white_tree_mark():
    """单色校徽 → 圆形蒙版取内圈（树/鸽/1940，去外环文字）→ 重着色为白"""
    alpha = Image.open(EMBLEM_MONO_SRC).getchannel("A")
    w, h = alpha.size
    ring = Image.new("L", (w, h), 0)
    r = w * 0.385  # 内圈边界
    ImageDraw.Draw(ring).ellipse(
        [w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=255
    )
    inner = Image.composite(alpha, Image.new("L", (w, h), 0), ring)
    mark = Image.new("RGBA", (w, h), "#FFFFFF")
    mark.putalpha(inner)
    return mark


def build_icon():
    base = gradient_plate()
    mark = white_tree_mark().resize((int(SIZE * 0.66),) * 2, Image.LANCZOS)
    base.paste(mark, ((SIZE - mark.width) // 2, (SIZE - mark.height) // 2), mark)
    return base


base = build_icon()
base.save("app/resources/icons/icon.png")
base.save(
    "app/resources/icons/icon.ico",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)

# macOS .icns：iconset + iconutil（仅 macOS 可用）
if os.uname().sysname == "Darwin":
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset)
        for side in (16, 32, 128, 256, 512):
            base.resize((side, side), Image.LANCZOS).save(
                os.path.join(iconset, f"icon_{side}x{side}.png")
            )
            base.resize((side * 2, side * 2), Image.LANCZOS).save(
                os.path.join(iconset, f"icon_{side}x{side}@2x.png")
            )
        subprocess.run(
            ["iconutil", "-c", "icns", iconset,
             "-o", "app/resources/icons/icon.icns"],
            check=True,
        )

# ---- macOS 托盘 mask 图标：黑白校徽 44px（22pt @2x）----
mono = Image.open(EMBLEM_MONO_SRC).convert("RGBA")
mono.resize((44, 44), Image.LANCZOS).save("app/resources/icons/menu-icon.png")

print("已生成 icon.png / icon.ico / icon.icns / menu-icon.png")
