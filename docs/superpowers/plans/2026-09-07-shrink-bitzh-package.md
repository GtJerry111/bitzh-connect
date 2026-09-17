# Shrink BITZH Connect Package Size Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把一个 Qt 小工具的体积瘦下来：开发 venv 从 ~1.2G 降到 ~400~550M（addons 实测独占 879M，整体出包），Nuitka 打包产物从 ~115M 降到 ~100M。

**Architecture:** 应用的唯一体积黑洞是不必要地装了完整的 `pyside6`（essentials+addons）。实测拆分：essentials 332M + addons 独有 879M（WebEngineCore 591M、QtPdf、Qt3D/QtQuick3D、Multimedia ffmpeg 等）。换包成 `pyside6-essentials` 后 addons 整体出包（注意：essentials 仍含 QtQuick/QML/Designer 等，venv 降不到 150M 量级，属正常）；Nuitka 产物只打 app 实际 import 的 Core/Gui/Widgets，再配合 `--lto=yes` 压缩主二进制、收窄 `--include-data-dir` 只打内核二进制，即可达成目标。

**Tech Stack:** Python 3.11 / uv / PySide6(Qt6) / Nuitka standalone / GitHub Actions 六目标矩阵（win amd64+arm64, mac intel+arm, linux amd64+arm）

---

## 现状关键数据（基线，改前记录）

- 开发 venv：`.venv` ≈ **1.2G**，其中 `PySide6/Qt` ≈ 1.0G（`QtWebEngineCore.framework` 590M、ffmpeg libavcodec 27M×2、QtPdf/QtDesigner/QtQuick/Qt3D…全部没被 app 用到）
- 应用代码实际 import：仅 `QtCore` / `QtGui` / `QtWidgets`（已核全 53 处 import，无 addons）
- 已装产物：`/Applications/BITZH Connect.app` ≈ **115M**（`main` 26M + `zju-connect` 13M + Qt 库 ~26M + PySide6 绑定 .so ~20M + Python 运行时 ~15M）
- app 运行时按路径读取的外部文件只有 `app/core/zju-connect`（+ win 的 `wintun.dll`）；其余资源全走编译进 `app/common/resources.py` 的 `:/` Qt 资源

---

## 文件结构

- `pyproject.toml` — 换 `pyside6`→`pyside6-essentials`；`nuitka` 移出运行时 `dependencies`，新建 `[dependency-groups] build`
- `.github/workflows/release.yml` — 构建同步命令加 `--group build`；三个平台（mac/win/linux）Nuitka 命令加 `--lto=yes` 并收窄 `--include-data-dir`→`--include-data-files`；构建步骤后加内核存在性断言；setup-uv 缓存 key 补 uv.lock
- `docs/superpowers/plans/2026-09-07-shrink-bitzh-package.md` — 本计划
- `uv.lock` — 由 `uv sync` 重新生成并提交

---

## Task 1: 换包 `pyside6` → `pyside6-essentials`

**Files:**
- Modify: `pyproject.toml:13`

- [ ] **Step 1: 修改 pyproject.toml**

将第 13 行：

```toml
    "pyside6>=6.11.0",
```

改为：

```toml
    "pyside6-essentials>=6.11.0",
```

- [ ] **Step 2: 重建 venv**

`uv sync` 不会干净地移除旧 addons，直接重建它。重建前留一份当前环境清单兜底（若曾手动 `uv pip install` 过临时包，重建后照单补回）：

```bash
uv pip freeze > /tmp/bitzh-venv-freeze.bak
rm -rf .venv && uv sync
```

Expected: `uv.lock` 更新；`.venv` 明显变小；site-packages 里出现 `pyside6_essentials-*.dist-info`，**不再出现** `pyside6_addons-*.dist-info`。

- [ ] **Step 3: 验证 essentials 可用且 addons 已移除**

```bash
.venv/bin/python -c "from PySide6.QtWidgets import QApplication; from PySide6.QtGui import QIcon; from PySide6.QtCore import Qt; print('essentials OK')"
du -sh .venv
find .venv -name "QtWebEngineCore.framework" -o -name "pyside6_addons-*.dist-info" | head
```

Expected: 打印 `essentials OK`；`find` 无输出（WebEngine 与 addons 均不存在）。`.venv` 预期 ~400~550M（essentials 本体实测 332M + Python/其他依赖；减重几乎全部来自 addons 出包）——只要远小于 1.2G 即正常，**不要因没到 150M 而停下来"修"**。

- [ ] **Step 4: 验证 `pyside6-rcc` 仍可用并重生成资源**

```bash
.venv/bin/pyside6-rcc app/resources/resources.qrc -o app/common/resources.py
git diff --stat app/common/resources.py
```

Expected: `pyside6-rcc` 正常执行；若 resources.py 无变化则 `git diff --stat` 为空（若变了，说明 qrc 内容有更新，确认后一并提交）。

- [ ] **Step 5: 冒烟启动**

```bash
.venv/bin/python app/main.py
```

Expected: 主窗口正常弹出，无 Qt/PySide6 报错。手动关掉窗口。

- [ ] **Step 6: 跑测试**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: 全绿（或与改之前一致的通过情况）。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml uv.lock app/common/resources.py
git commit -m "chore(deps): switch pyside6 to pyside6-essentials to trim venv & bundle"
```

---

## Task 2: `nuitka` 移出运行时，新建 build 组并同步 CI

**Files:**
- Modify: `pyproject.toml:7-22`
- Modify: `.github/workflows/release.yml:100`

- [ ] **Step 1: 从运行时 dependencies 去掉 nuitka**

将 pyproject.toml 依赖块中：

```toml
dependencies = [
    "keyring>=25.5",
    "nuitka>=4.0.8",
    "packaging>=26.2",
    "psutil>=6.0",
    "pyobjc>=12.1 ; sys_platform == 'darwin'",
    "pyside6-essentials>=6.11.0",
    "requests>=2.33.1",
]
```

改为（删掉 `nuitka>=4.0.8,`）：

```toml
dependencies = [
    "keyring>=25.5",
    "packaging>=26.2",
    "psutil>=6.0",
    "pyobjc>=12.1 ; sys_platform == 'darwin'",
    "pyside6-essentials>=6.11.0",
    "requests>=2.33.1",
]
```

- [ ] **Step 2: 新增 build 组**

将依赖分组：

```toml
[dependency-groups]
dev = [
    "pillow>=12.3.0",
    "pytest>=8.3",
    "pytest-qt>=4.4",
]
```

改为在 `dev` 之后追加 `build` 组：

```toml
[dependency-groups]
dev = [
    "pillow>=12.3.0",
    "pytest>=8.3",
    "pytest-qt>=4.4",
]
build = [
    "nuitka>=4.0.8",
]
```

- [ ] **Step 3: 更新 CI 同步命令**

将 `.github/workflows/release.yml:100` 的：

```yaml
        run: uv sync
```

改为：

```yaml
        run: uv sync --group build
```

Expected: `uv sync --group build` = 运行时依赖 + dev 组 + build 组，CI 构建仍能拿到 nuitka。

- [ ] **Step 4: 本地验证 build 组可装**

```bash
uv sync --group build && .venv/bin/python -m nuitka --version
```

Expected: nuitka 版本号正常打印。

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml uv.lock .github/workflows/release.yml
git commit -m "chore(deps): move nuitka to build dependency group"
```

- [ ] **Step 6: setup-uv 缓存 key 补 uv.lock（顺手修既有问题，单独提交）**

`release.yml` 的 `cache-dependency-glob: "**/pyproject.toml"` 不含 uv.lock——本次 pyproject 会变不受影响，但以后仅升级 lock 的依赖更新会吃到旧缓存。改为：

```yaml
          cache-dependency-glob: |
            **/pyproject.toml
            **/uv.lock
```

```bash
git add .github/workflows/release.yml
git commit -m "ci: add uv.lock to setup-uv cache-dependency-glob"
```

---

## Task 3: Nuitka 全平台加 `--lto=yes`

**Files:**
- Modify: `.github/workflows/release.yml`（mac 块 132-145 / win 块 171-185 / linux 块 229-241；行号为基线快照，前面 Task 的插入会让其前移，以块内容定位为准）

> 说明：`--lto=yes` 让 Nuitka 把编译出的 C 代码交给链接器做 link-time optimization，压缩 `main` 主二进制（约 26M→~20M）。需要各 runner 自带的编译器（mac=clang, linux=gcc, win=mingw/MSVC），CI 均已具备。

- [ ] **Step 1: macOS 块加 LTO**

在 `.github/workflows/release.yml` mac 块，`python -m nuitka \` 后紧接的 `--standalone \` 之前插入一行：

```yaml
            --lto=yes \
```

即最终：

```yaml
          python -m nuitka \
            --lto=yes \
            --standalone \
            --assume-yes-for-downloads \
            --enable-plugin=pyside6 \
```

- [ ] **Step 2: Windows 块加 LTO**

在 win 块同样处理：

```yaml
          python -m nuitka `
            --lto=yes `
            --standalone `
            --assume-yes-for-downloads `
            --enable-plugin=pyside6 `
```

- [ ] **Step 3: Linux 块加 LTO**

在 linux 块同样处理：

```yaml
          python -m nuitka \
            --lto=yes \
            --standalone \
            --assume-yes-for-downloads \
            --enable-plugin=pyside6 \
```

- [ ] **Step 4: 提交**

```bash
git add .github/workflows/release.yml
git commit -m "build: enable Nuitka LTO to compress main binary"
```

---

## Task 4: 收窄 `--include-data-dir` → `--include-data-files`（只打内核二进制）

**Files:**
- Modify: `.github/workflows/release.yml`（mac / win / linux 三处）

> 说明：`--include-data-dir=app=app` 把整个 `app/` 目录当数据打进产物。运行时真正按路径读取的只有 `app/core/zju-connect`（win 另有 `wintun.dll`），其余资源（icons/brand/qrc）都走 `:/` 编译资源。收窄后产物里不再附带重复的 resources 数据文件。
> ⚠️ 收窄后数据文件目标路径必须落在 `app/core/` 下（与 `connection_utils.py` 中 `base_path/app/core/zju-connect` 拼出的路径一致），否则运行时找不到内核。

- [ ] **Step 1: macOS 块收窄**

将 mac 块中：

```yaml
            --include-data-dir=app=app \
            --include-data-files=.app-version=.app-version \
```

改为：

```yaml
            --include-data-files=app/core/zju-connect=app/core/zju-connect \
            --include-data-files=.app-version=.app-version \
```

- [ ] **Step 2: Windows 块收窄**

将 win 块中：

```yaml
            --include-data-dir=app=app `
            --include-data-files=app\core\zju-connect.exe=app\core\zju-connect.exe `
            --include-data-files=.app-version=.app-version `
```

改为（wintun.dll 依赖前面的步骤拷进了 app/core，需一并打入）：

```yaml
            --include-data-files=app\core\zju-connect.exe=app\core\zju-connect.exe `
            --include-data-files=app\core\wintun.dll=app\core\wintun.dll `
            --include-data-files=.app-version=.app-version `
```

- [ ] **Step 3: Linux 块收窄**

将 linux 块中：

```yaml
            --include-data-dir=app=app \
            --include-data-files=.app-version=.app-version \
```

改为：

```yaml
            --include-data-files=app/core/zju-connect=app/core/zju-connect \
            --include-data-files=.app-version=.app-version \
```

- [ ] **Step 4: 三平台构建步骤后加内核存在性断言**

收窄路径一旦写错，CI 构建本身仍是绿的（静默回归）。加断言让错误直接红，且对以后每次构建永久生效。在各平台 Build 步骤之后插入：

macOS（`Build Executable (macOS)` 之后）：

```yaml
      - name: Verify kernel bundled (macOS)
        if: runner.os == 'macOS'
        run: test -f "dist/BITZH Connect.app/Contents/MacOS/app/core/zju-connect"
```

Windows（`Build Executable (Windows)` 之后、`Compile Installer` 之前；产物路径已与 setup.iss 的 `dist\main.dist\*` 对齐核实）：

```yaml
      - name: Verify kernel bundled (Windows)
        if: runner.os == 'Windows'
        run: |
          if (-not (Test-Path "dist\main.dist\app\core\zju-connect.exe")) { throw "zju-connect.exe missing" }
          if (-not (Test-Path "dist\main.dist\app\core\wintun.dll")) { throw "wintun.dll missing" }
```

Linux（`Build Executable (Linux)` 之后，注意该步骤末尾已 `mv` 为 `dist/bitzh-connect`）：

```yaml
      - name: Verify kernel bundled (Linux)
        if: runner.os == 'Linux'
        run: test -f dist/bitzh-connect/app/core/zju-connect
```

- [ ] **Step 5: 提交**

```bash
git add .github/workflows/release.yml
git commit -m "build: narrow include-data-dir to only bundle the zju-connect kernel"
```

---

## Task 5: 本地重建产物并测量/冒烟（mac 落实验收）

> 前置：本机已通过 Task 1 重建了 essentials venv；`app/core/zju-connect` 存在（13M）。

- [ ] **Step 1: 本地执行 mac 版 Nuitka 构建（含 LTO + 收窄后的 include-data-files）**

```bash
source .venv/bin/activate
pyside6-rcc app/resources/resources.qrc -o app/common/resources.py
python -m nuitka \
  --lto=yes \
  --standalone \
  --assume-yes-for-downloads \
  --enable-plugin=pyside6 \
  --include-data-files=app/core/zju-connect=app/core/zju-connect \
  --include-data-files=.app-version=.app-version \
  --macos-create-app-bundle \
  --macos-app-icon=app/resources/icons/icon.icns \
  --macos-app-name="BITZH Connect" \
  --macos-app-version=$(cat .app-version) \
  --output-dir=dist \
  --remove-output \
  app/main.py
```

Expected: 构建成功，`dist/BITZH Connect.app` 生成。

- [ ] **Step 2: 验证内核二进制已入包（目标路径正确）**

```bash
ls -la "dist/BITZH Connect.app/Contents/MacOS/app/core/zju-connect"
```

Expected: 存在且为可执行（`-rwxr-xr-x`）。若不存在 → 收窄路径不对，回退 Task 4 改为保留 `--include-data-dir=app=app`，并向用户确认。

- [ ] **Step 3: 测量产物体积**

```bash
du -sh "dist/BITZH Connect.app"
du -sh "dist/BITZH Connect.app/Contents/MacOS/main" "dist/BITZH Connect.app/Contents/MacOS/app" "dist/BITZH Connect.app/Contents/MacOS/PySide6"
```

Expected: `.app` 总大小 ≈ 100M（对比基线 115M）；`main` < 26M；`app/` ≈ 13M（只剩 zju-connect）；`PySide6/` 不含 addons。（比基线大或异常 → 停下核对。）

- [ ] **Step 4: 冒烟启动并确认连接链路能找到内核**

```bash
open "dist/BITZH Connect.app"
```

Expected: 窗口正常打开；点击连接后日志显示 `Running command: .../app/core/zju-connect` 且能进入登录/连接流程（可用 `scripts/ec_login_debug.py` 或观察日志确认未报“找不到内核”）。验证后退出。

- [ ] **Step 5: 清理产物并提交（如需）**

```bash
rm -rf dist
```

（构建产物已被 `.gitignore` 忽略，无需提交。）

---

## Task 6: 推 CI 全矩阵验收（触发一次构建）

- [ ] **Step 1: 推送触发矩阵**

```bash
git push origin main
```

Expected: GitHub Actions 六目标矩阵（win amd64/arm64、mac intel/arm、linux amd64/arm）全部通过；mac 产物上传为 `bitzh-connect-darwin-*.dmg`。

- [ ] **Step 2: 抽查产物体积（Actions Artifacts）**

内核存在性已由 Task 4 的 CI 断言兜底（缺失则构建直接红），此步只看体积，无需解包安装：
- mac 的 `bitzh-connect-darwin-*.dmg`：本机挂载即可看 `.app` 体积（期望 ≈ 100M）
- win 的 `*-setup.exe` 与 linux 的 `*.deb`：直接对比文件大小相对基线的降幅即可（win 基线安装后 ~150M，降幅主要来自 QtPdf 移除）

Expected: 均明显小于基线；无新增运行时报错。

- [ ] **Step 3: 全矩阵出包无回归确认**

若任一平台构建失败（最可能是 win 的 `--lto=yes` 链接阶段）：打开该平台构建日志，核对是否有 `-flto`/链接错误；必要时参考 Task 3 回退策略——仅把出问题的平台去掉 `--lto=yes`，单独提交。

---

## 回退预案

- **`--lto=yes` 在某平台失败**：从该平台命令中删掉 `--lto=yes` 即可，其余平台保留（体积收益对该平台降级为 0，但构建恢复稳定）。
- **收窄 `--include-data-dir` 后内核找不到**：把该平台回退为 `--include-data-dir=app=app`（或确认 `--include-data-files` 目标路径后重试）。
- **换 essentials 后启动/资源异常**：`git revert` Task 1 的 commit，或临时改回 `pyside6>=6.11.0` 重建 venv。
- **venv 重建后发现缺包**：对照 `/tmp/bitzh-venv-freeze.bak` 逐项 `uv pip install` 补回（或确认其本就该被清掉）。

## 自检清单

- [ ] `pyproject.toml` 运行时 `dependencies` 不再包含 `nuitka`；`pyside6-essentials` 已替换 `pyside6`
- [ ] `[dependency-groups] build` 含 nuitka；CI `uv sync` 已改为 `--group build`
- [ ] 三平台 Nuitka 命令均含 `--lto=yes`
- [ ] 三平台均收窄为 `--include-data-files`（win 含 wintun.dll）
- [ ] 本机 mac 已实测产物体积下降 + 冒烟通过
- [ ] 三平台构建步骤后均有内核存在性断言
- [ ] setup-uv `cache-dependency-glob` 已含 `uv.lock`
- [ ] 重建 venv 前已 `uv pip freeze > /tmp/bitzh-venv-freeze.bak` 留底
- [ ] 已提交 Task 1–4 的增量 commit
