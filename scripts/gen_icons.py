# scripts/gen_icons.py
"""一次性图标生成脚本：由 BIT 校徽素材生成应用图标。

设计：深绿 #005C31 圆角底板 + 校徽居中缩放到 80%——校徽内圈与底板同绿
融为一体，铜色外环自然成为图标边框。托盘 mask 图标使用黑白校徽 44px
（22pt @2x，供 macOS 菜单栏 setIsMask 使用）。

执行：uv run python scripts/gen_icons.py
"""

from PIL import Image, ImageDraw

EMBLEM_SRC = "/Users/jerry/Projects/素材/BIT_emblem_from_example9_fixed_v2.png"
MONO_SRC = "/Users/jerry/Projects/素材/BITemblem.png"
BRAND_GREEN = "#005C31"
SIZE = 1024

# ---- 主图标：深绿圆角底板 + 校徽居中 ----
base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle(
    [0, 0, SIZE, SIZE], radius=int(SIZE * 0.225), fill=255  # macOS squircle 近似
)
plate = Image.new("RGBA", (SIZE, SIZE), BRAND_GREEN)
base.paste(plate, (0, 0), mask)

emblem = Image.open(EMBLEM_SRC).convert("RGBA")
inner = int(SIZE * 0.80)
emblem = emblem.resize((inner, inner), Image.LANCZOS)
base.paste(emblem, ((SIZE - inner) // 2, (SIZE - inner) // 2), emblem)

base.save("app/resources/icons/icon.png")
base.save(
    "app/resources/icons/icon.ico",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)

# ---- macOS 托盘 mask 图标：黑白校徽 44px（22pt @2x）----
mono = Image.open(MONO_SRC).convert("RGBA")
mono.resize((44, 44), Image.LANCZOS).save("app/resources/icons/menu-icon.png")

print("已生成 icon.png / icon.ico / menu-icon.png")
