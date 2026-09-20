# app/common/panel_material.py
"""菜单栏快捷面板的材质参数（真机调参用）。

底板是系统 NSGlassEffectView —— 只有 style（regular/clear）与圆角是代码可调的，
模糊半径/白纱浓度由系统管理。其余能精细调的全部是 Qt 自绘层（chip 按钮、hairline、
行 hover/按下、内边距）。

参数分浅色/深色两套：字段名一致，数值各自独立。调参窗
（views/panel_tuner.py）实时改这些值；定稿后写回本模块的 DEFAULTS 即可固化。
"""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

DEFAULTS = {
    "glass_style": "regular",   # regular（乳白磨砂，参照图）/ clear（清透强折射）
    "corner_radius": 22.0,
    "light": {
        "chip_fill": 0.579,
        "chip_border": 0.357,
        "chip_highlight": 0.236,
        "chip_hover": 0.636,
        "chip_pressed": 0.62,
        "hairline": 0.403,
        "row_hover": 0.172,
        "row_pressed": 0.24,
        "row_height": 33,
        "pad": 14,
        "gap": 7,
    },
    "dark": {
        "chip_fill": 0.10,
        "chip_border": 0.22,
        "chip_highlight": 0.18,
        "chip_hover": 0.18,
        "chip_pressed": 0.26,
        "hairline": 0.14,
        "row_hover": 0.24,
        "row_pressed": 0.34,
        "row_height": 33,
        "pad": 10,
        "gap": 6,
    },
}

# 滑杆范围（下限, 上限, 是否整数）——调参窗与校验共用单一事实源
RANGES = {
    "chip_fill": (0.0, 1.0, False),
    "chip_border": (0.0, 1.0, False),
    "chip_highlight": (0.0, 1.0, False),
    "chip_hover": (0.0, 1.0, False),
    "chip_pressed": (0.0, 1.0, False),
    "hairline": (0.0, 0.6, False),
    "row_hover": (0.0, 0.5, False),
    "row_pressed": (0.0, 0.6, False),
    "row_height": (24, 44, True),
    "pad": (0, 24, True),
    "gap": (0, 16, True),
}

# 存盘顺序（调参窗 UI 顺序）
ORDER = ["chip_fill", "chip_border", "chip_highlight", "chip_hover", "chip_pressed",
         "hairline", "row_hover", "row_pressed", "row_height", "pad", "gap"]

LABELS = {
    "chip_fill": "chip 填充",
    "chip_border": "chip 描边",
    "chip_highlight": "chip 顶部高光",
    "chip_hover": "chip hover",
    "chip_pressed": "chip 按下",
    "hairline": "分隔线",
    "row_hover": "行 hover",
    "row_pressed": "行按下",
    "row_height": "行高",
    "pad": "面板内边距",
    "gap": "块间距",
}


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def _path() -> Path:
    """存盘位置：项目 .superpowers/（gitignore）→ 家目录 → 临时目录。"""
    root = Path(__file__).resolve().parents[2]
    for candidate in (root / ".superpowers", Path.home() / ".bitzh-connect"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate / "panel-material.json"
        except OSError:
            continue
    return Path(tempfile.gettempdir()) / "panel-material.json"


def load() -> dict:
    """磁盘上的参数覆盖默认值（缺失/损坏时安静回退默认）。"""
    params = defaults()
    try:
        raw = json.loads(_path().read_text())
    except (OSError, ValueError):
        return params
    if not isinstance(raw, dict):
        return params
    if raw.get("glass_style") in ("regular", "clear"):
        params["glass_style"] = raw["glass_style"]
    if isinstance(raw.get("corner_radius"), (int, float)):
        params["corner_radius"] = float(raw["corner_radius"])
    for mode in ("light", "dark"):
        block = raw.get(mode)
        if isinstance(block, dict):
            for key in ORDER:
                value = block.get(key)
                if isinstance(value, (int, float)):
                    params[mode][key] = value
    return params


def save(params: dict) -> Path:
    path = _path()
    path.write_text(json.dumps(params, indent=1, ensure_ascii=False))
    return path
