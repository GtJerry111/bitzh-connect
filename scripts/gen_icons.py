"""Generate platform icon formats from the approved 1024 px app icon PNG.

Run with: uv run python scripts/gen_icons.py
"""

import os
import platform
import subprocess
import tempfile

from PIL import Image

ICON_PATH = "app/resources/icons/icon.png"


def main():
    base = Image.open(ICON_PATH).convert("RGBA")
    if base.size != (1024, 1024):
        raise ValueError(f"Expected a 1024x1024 icon, got {base.size}")

    base.save(
        "app/resources/icons/icon.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    if platform.system() == "Darwin":
        with tempfile.TemporaryDirectory() as tmp:
            iconset = os.path.join(tmp, "icon.iconset")
            os.makedirs(iconset)
            for side in (16, 32, 128, 256, 512):
                base.resize((side, side), Image.Resampling.LANCZOS).save(
                    os.path.join(iconset, f"icon_{side}x{side}.png")
                )
                base.resize((side * 2, side * 2), Image.Resampling.LANCZOS).save(
                    os.path.join(iconset, f"icon_{side}x{side}@2x.png")
                )
            subprocess.run(
                [
                    "iconutil",
                    "-c",
                    "icns",
                    iconset,
                    "-o",
                    "app/resources/icons/icon.icns",
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
