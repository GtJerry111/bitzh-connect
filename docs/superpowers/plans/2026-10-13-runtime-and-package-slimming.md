# BITZH Connect Runtime and Package Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce development/package/installed footprint and identify runtime memory and CPU waste while preserving all current features, visual UI, visible refresh cadence, and interaction flows.

**Architecture:** Execute the work in measurement-first phases. First capture per-process RSS/CPU and package contents, then apply behavior-neutral dependency and Nuitka trimming, then fix the confirmed small worker-lifecycle leak. Do not change log semantics, sampling intervals, defaults, or UI behavior until measurements prove a separate optimization is necessary.

**Tech Stack:** Python 3.11, uv, PySide6, Nuitka, GitHub Actions, pytest, platform process tools.

## Scope and invariants

- Preserve connection, disconnect, auto-reconnect, TUN, proxy, helper installation, menu bar, settings, and update behavior.
- Preserve all layouts, colors, animations, text, controls, and visible rate updates at their current cadence.
- Do not change `debug_dump`, TUN log retention, watchdog interval, rate monitor interval, or default settings in the first implementation batch.
- Do not convert the main application to Nuitka onefile.
- Every packaging change must be followed by a built-application smoke test on the affected platform.

## File map

- Modify `pyproject.toml`: use the smaller runtime Qt distribution and keep Nuitka build-only.
- Modify `uv.lock`: regenerate from the dependency changes.
- Modify `.github/workflows/release.yml`: build dependency group, LTO, precise data inclusion, cache key, and artifact assertions.
- Modify `app/services/update_service.py`: remove workers on every terminal signal.
- Add focused tests under `tests/` for update worker cleanup and any measurement helpers introduced.
- Add `scripts/slim_audit.py`: read-only package/process audit with stable, machine-readable output.
- Modify `docs/README` only if commands or release artifact layout change; do not add product-facing UI text.

### Task 1: Establish repeatable runtime and artifact baselines

**Files:**
- Create: `scripts/slim_audit.py`
- Test: `tests/test_slim_audit.py`

- [ ] **Step 1: Write the failing tests for pure audit helpers**

Test helpers that parse process rows, classify `BITZH Connect`, `zju-connect`, and `bitzh-helper`, and sum artifact files without starting processes. Use injected command output and temporary directories so tests are platform-independent.

```python
def test_classifies_known_processes():
    rows = parse_process_rows("101 1 120000 2.0 BITZH Connect\\n102 1 900000 40.0 zju-connect")
    assert rows[0].name == "gui"
    assert rows[1].name == "kernel"

def test_artifact_totals_are_deterministic(tmp_path):
    (tmp_path / "a").write_bytes(b"123")
    (tmp_path / "b").write_bytes(b"12345")
    assert artifact_size(tmp_path) == 8
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run pytest tests/test_slim_audit.py -q`

Expected: FAIL because the audit module and helpers do not exist.

- [ ] **Step 3: Implement the read-only audit script**

Implement these subcommands without changing application behavior:

```text
python scripts/slim_audit.py artifact <path>
python scripts/slim_audit.py processes
python scripts/slim_audit.py logs
```

`processes` must use `ps` on macOS/Linux and PowerShell-compatible output on Windows, report a stable record with `kind`, `pid`, `ppid`, `rss_mb`, `cpu_percent`, `threads`, and `command`. `artifact` must report `root`, `total_bytes`, and a `largest_files` list of at most 20 `{path, bytes}` records. `logs` must report `path`, `bytes`, and `exists` for known diagnostics and `/tmp/bitzh-tun-*` files. Each command must emit JSON lines, return exit code 0 when a platform command or optional path is unavailable, and include an `available: false` record with an explanatory `reason`; it must never delete or truncate files.

- [ ] **Step 4: Run the tests and lint-level smoke check**

Run: `uv run pytest tests/test_slim_audit.py -q` and `uv run python scripts/slim_audit.py artifact .`

Expected: tests pass and the command prints deterministic size data without modifying files.

- [ ] **Step 5: Capture manual baselines before code changes**

Record, for each platform available, these scenarios for 60 seconds: GUI idle, TUN idle, proxy idle, sustained traffic, and `debug_dump` on/off. Record per-process average and peak RSS/CPU, artifact size, and log growth. This baseline is required before interpreting any later improvement.

If `zju-connect` RSS grows with traffic or reaches the reported scale, preserve the exact kernel version, command arguments, traffic profile, timestamps, and log size in the execution notes. This is the evidence required for the kernel decision in Task 7.

- [ ] **Step 6: Commit the measurement-only change**

```bash
git add scripts/slim_audit.py tests/test_slim_audit.py
git commit -m "chore: add runtime and artifact slimming audit"
```

### Task 2: Trim runtime/build dependencies without changing application imports

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Change the Qt runtime dependency and separate Nuitka**

Replace `pyside6>=6.11.0` with `pyside6-essentials>=6.11.0`. Remove `nuitka` from `dependencies` and add:

```toml
[dependency-groups]
build = ["nuitka>=4.0.8"]
```

Keep existing runtime and dev dependencies unchanged in this task.

- [ ] **Step 2: Regenerate the lock file**

Run: `uv lock`

Expected: the lock contains `pyside6-essentials`, no `pyside6-addons` package, and Nuitka remains available through the `build` group.

- [ ] **Step 3: Verify imports and the resource compiler**

Run:

```bash
uv sync --group build
uv run python -c "from PySide6.QtCore import Qt; from PySide6.QtGui import QIcon; from PySide6.QtWidgets import QApplication; print('Qt essentials OK')"
uv run pyside6-rcc app/resources/resources.qrc -o /tmp/bitzh-resources.py
uv run python -m nuitka --version
```

Expected: all commands succeed; no QtWebEngine framework or `pyside6_addons` distribution exists in `.venv`.

- [ ] **Step 4: Run the existing test suite**

Run: `uv run pytest -q`

Expected: no regression relative to the pre-change baseline.

- [ ] **Step 5: Commit the dependency change**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): use PySide6 essentials and isolate build tooling"
```

### Task 3: Remove unused files from all standalone artifacts

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Update CI dependency installation and cache inputs**

Change `uv sync` to `uv sync --group build`. Change `cache-dependency-glob` to include both `**/pyproject.toml` and `**/uv.lock`.

- [ ] **Step 2: Enable LTO for macOS, Windows, and Linux builds**

Add the platform-appropriate continuation form of `--lto=yes` immediately before `--standalone` in each main Nuitka command. Do not add it to the helper onefile command unless a separate benchmark proves it is safe and useful.

- [ ] **Step 3: Replace broad app inclusion with exact runtime files**

For macOS and Linux, replace `--include-data-dir=app=app` with:

```text
--include-data-files=app/core/zju-connect=app/core/zju-connect
--include-data-files=.app-version=.app-version
```

For Windows, include `zju-connect.exe`, `wintun.dll`, and `.app-version` explicitly. Keep Qt resources supplied by `app/common/resources.py`; do not copy the source tree, `__pycache__`, or original resource files.

- [ ] **Step 4: Add platform artifact assertions**

After each build, assert that the expected kernel path exists inside the generated artifact. On Windows assert both `zju-connect.exe` and `wintun.dll`. Fail the workflow if an unexpected source tree is present at the packaged `app` path.

- [ ] **Step 5: Add artifact size/content inspection**

Run `python scripts/slim_audit.py artifact <artifact-root>` in CI or as a local release step. Emit the 20 largest files and fail only on missing required files, not on a hardcoded size threshold that could reject legitimate Qt updates.

- [ ] **Step 6: Build and smoke-test one available platform**

Use the exact CI Nuitka command locally where possible. Launch the packaged app, verify main window, connect/disconnect, settings, menu bar/tray, update check, and helper/TUN entry points. Compare artifact contents before/after.

- [ ] **Step 7: Run tests and commit**

Run: `uv run pytest -q`

```bash
git add .github/workflows/release.yml
git commit -m "build: trim standalone artifacts to runtime files"
```

### Task 4: Fix the update worker terminal-state leak

**Files:**
- Modify: `app/services/update_service.py`
- Test: `tests/test_update_service.py`

- [ ] **Step 1: Add failing tests for all terminal signals**

Test that `_workers` returns to its previous size after `update_available`, `up_to_date`, and `error`. Use a fake worker/signal arrangement already compatible with the existing Qt test fixtures; do not make network requests.

- [ ] **Step 2: Implement one idempotent cleanup callback**

Create a closure bound to the worker that removes it only if still present, then connect that callback to all three terminal signals. Keep the existing signal return API and thread-pool behavior unchanged.

- [ ] **Step 3: Run focused and full tests**

Run: `uv run pytest tests/test_update_service.py -q` and then `uv run pytest -q`.

Expected: all tests pass; repeated update checks no longer grow `_workers`.

- [ ] **Step 4: Commit**

```bash
git add app/services/update_service.py tests/test_update_service.py
git commit -m "fix: release update workers on every terminal state"
```

### Task 5: Audit installed footprint and residual files without changing lifecycle semantics

**Files:**
- Modify only if a concrete defect is found: `app/utils/tun_utils.py`, `app/utils/helper_installer.py`, `app/utils/diagnostics.py`
- Test: focused existing helper/TUN/diagnostic tests

- [ ] **Step 1: Measure installed locations**

On macOS record sizes for the app bundle, `/Library/PrivilegedHelperTools/bitzh-helper`, `/Library/PrivilegedHelperTools/zju-connect`, LaunchDaemon plist, diagnostics logs, and `/tmp/bitzh-tun-*`. On Windows/Linux record the installed standalone directory and log/temp locations. Mark a platform as `unavailable` when it is not the current host or requires permissions that are not available; do not weaken permissions or silently omit the measurement.

- [ ] **Step 2: Verify cleanup paths using existing tests and a controlled install/uninstall**

Confirm normal disconnect removes TUN log/pid/stop files, upgrade does not leave an obsolete helper binary, and uninstall removes the helper service and socket. If controlled install/uninstall cannot run because the host or privileges are unavailable, record that result and run the corresponding existing unit tests instead. Do not remove `RunAtLoad` or `KeepAlive`; the helper’s idle residency is part of the current TUN design.

- [ ] **Step 3: Only fix observed residue**

If a reproducible residue exists, add a regression test first, then make the smallest cleanup change. Do not add log truncation or change debug logging in this plan.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_helper_installer.py tests/test_tun_worker.py tests/test_diagnostics.py -q`.

### Task 6: Investigate CPU hotspots while preserving visible timing

**Files:**
- Create or modify only after baseline confirmation: `app/services/rate_monitor.py`, `app/utils/tun_worker.py`
- Test: `tests/test_rate_monitor.py`, `tests/test_tun_worker.py`

- [ ] **Step 1: Attribute CPU before changing intervals**

Use the audit script and platform tools to compare CPU from `nettop` child processes, GUI, `zju-connect`, and helper. Keep the current one-second visible rate update contract and 300ms TUN worker behavior during this measurement.

- [ ] **Step 2: If `nettop` process creation is the hotspot, design a persistent sampler**

Replace repeated process creation only if the output parser can provide the same up/down values at the same one-second UI cadence. Add parser/process failure tests and ensure `stop()` terminates the sampler without leaving children. Do not change labels, graph samples, or callback cadence.

- [ ] **Step 3: If TUN polling is the hotspot, optimize reads without changing polling semantics**

First check file metadata before reading unchanged logs and cap only temporary allocations per read; do not truncate the log or alter user-visible output in this task. Add tests for partial lines and process termination.

- [ ] **Step 4: Re-run the same 60-second CPU scenarios**

Accept the change only if CPU decreases materially, visible rates remain one-second updates, no child process leaks, and all connection tests pass. Otherwise revert the optional CPU implementation and document the measurement.

### Task 7: Final compatibility and release acceptance

**Files:**
- No production changes unless a failed acceptance test identifies a regression.
- Update the plan execution notes or release documentation with measured results.

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`.

- [ ] **Step 2: Run packaged-app smoke tests on each available target**

Verify launch, login form, settings, theme switching, connect/disconnect, proxy mode, TUN mode, auto-reconnect, sleep/wake recovery, menu bar/tray, update check, helper install/uninstall, and clean exit.

- [ ] **Step 3: Compare before/after measurements**

Report artifact bytes, installed bytes, GUI/kernel/helper peak RSS, average/95th percentile CPU, child-process count, and log growth for identical scenarios. Treat `zju-connect` RSS growth as a separate upstream/kernel issue if it remains after GUI and packaging changes.

- [ ] **Step 4: Resolve the confirmed kernel-memory branch**

If `zju-connect` is not the source of abnormal growth, record that conclusion and close the branch. If it is the source, perform both actions below before declaring the plan complete:

1. Test the newest compatible `zju-connect` release (or the smallest known-good version) with the same command arguments and traffic profile. Keep the application integration unchanged; only replace the bundled kernel artifact for the A/B run.
2. If the newer/known-good kernel fixes the growth, update the release download/version pin and rerun packaged TUN smoke tests. If no compatible kernel fixes it, create an upstream issue or repository note containing the captured reproduction data, keep the current kernel unchanged, and mark the memory problem as a documented external blocker rather than claiming it was fixed.

Do not add an unverified memory cap, forced restart, or hidden change to connection behavior merely to reduce RSS.

- [ ] **Step 5: Inspect the final diff and commit history**

Confirm no UI files changed solely for appearance, no defaults changed, and no broad source-tree inclusion remains in release workflow.

## Self-review and exit criteria

- The plan covers package size, installed disk usage, runtime memory attribution, CPU attribution, and the confirmed update-worker leak.
- The plan deliberately leaves debug-log limits, sampling interval changes, and kernel replacement out until measurements justify them.
- No step relies on an unspecified placeholder; every change has a file, command, or acceptance condition.
- Completion requires passing tests plus packaged-app smoke checks, not only a smaller installer.

## Execution notes (Round 11, branch `chore/runtime-package-slimming`)

Code deliverables were implemented on branch `chore/runtime-package-slimming`
(base `a69de00`). The execution workflow reviewed the task commits; an independent
post-execution audit found and fixed the process-audit thread/CPU reporting gap below:

- Task 1 (Steps 1-4, 6): `34ad8d4` + fix `1addec3`
- Task 2 (Steps 1-5): `619bdc2`
- Task 3 (Steps 1-5, 7): `230202c`
- Task 4 (Steps 1-4): `62b03c7`

Full suite: **369 passed**. The measurement/packaging/multi-platform steps below were
**deferred by the project owner to manual verification** because they need the real app,
a real campus-network login, elevation, or non-macOS runners that are unavailable in the
implementation environment. They are **not yet executed** — the branch is code-complete
but not release-verified.

Post-execution audit fix: Unix process records now collect best-effort thread counts;
Windows unavailable CPU is represented as `null` instead of a fabricated zero. The
focused audit test and full suite must be rerun after this fix.

### Manual checklist (owner)

**A. Runtime baselines — Task 1 Step 5**
- [ ] For 60s each, record per-process avg/peak RSS + CPU (GUI, `zju-connect`, `bitzh-helper`):
      GUI idle / TUN idle / proxy idle / sustained traffic / `debug_dump` on / off.
      Helper: `uv run --no-sync python scripts/slim_audit.py processes`
- [ ] Record artifact size (`... slim_audit.py artifact <root>`) and log growth
      (`... slim_audit.py logs`) before/after.
- [ ] If `zju-connect` RSS grows with traffic, capture exact kernel version, argv, traffic
      profile, timestamps, log size — required evidence for Task 7 Step 4.

**B. Packaging build + smoke — Task 3 Step 6**
- [ ] Run the exact CI Nuitka command locally for macOS (see `.github/workflows/release.yml`).
- [ ] Confirm the new `Assert artifact contents (macOS)` step passes:
      kernel exists at `Contents/MacOS/app/core/zju-connect`, and `app/` contains only `core`.
- [ ] Confirm `--lto=yes` builds without error and the app still launches.
- [ ] Launch the packaged app; verify main window, connect/disconnect, settings, menu bar/tray,
      update check, helper/TUN entry points. Compare artifact contents before/after.
- [ ] Note: `.app-version` is still bundled as a data file though the app reads it from QRC;
      drop it if the build proves it unused (reviewer Minor #5).

**C. Installed footprint — Task 5**
- [ ] macOS: sizes of app bundle, `/Library/PrivilegedHelperTools/bitzh-helper`,
      `/Library/PrivilegedHelperTools/zju-connect`, LaunchDaemon plist, diagnostics logs,
      `/tmp/bitzh-tun-*`.
- [ ] Controlled install/uninstall: normal disconnect removes TUN log/pid/stop; upgrade leaves
      no obsolete helper; uninstall removes helper service + socket.
- [ ] Only fix observed residue, with a regression test first.

**D. CPU attribution — Task 6**
- [ ] Compare CPU from `nettop` children vs GUI vs `zju-connect` vs helper at the current 1s
      UI cadence / 300ms TUN worker behavior.
- [ ] Only if a hotspot is confirmed: persistent `nettop` sampler (Step 2) and/or TUN read
      optimization (Step 3); re-run the same 60s scenarios and keep only material wins.

**E. Acceptance — Task 7**
- [ ] `uv run --no-sync pytest -q`.
- [ ] Packaged smoke on each available target: launch, login form, settings, theme switching,
      connect/disconnect, proxy, TUN, auto-reconnect, sleep/wake, tray, update check,
      helper install/uninstall, clean exit.
- [ ] Before/after: artifact bytes, installed bytes, GUI/kernel/helper peak RSS, avg/p95 CPU,
      child-process count, log growth.
- [ ] Kernel-memory branch: if `zju-connect` is the source, A/B the newest compatible kernel
      with the same argv/traffic; update pin if fixed, else file an upstream note and keep the
      current kernel, marked a documented external blocker.
- [ ] Inspect final diff: no appearance-only UI changes, no default changes, no broad
      source-tree inclusion in the release workflow.

### macOS arm64 verification (2026-10-13)

- [x] Rebuilt the macOS arm64 app with the release command, adding local-only
      `--disable-cache=ccache` because the downloaded Nuitka ccache binary was x86_64
      while this host is arm64. The C compiler and linker completed successfully.
- [x] Artifact assertions passed: `Contents/MacOS/app/core/zju-connect` exists and
      `Contents/MacOS/app` contains only `core`.
- [x] Packaged executable startup smoke passed: the app stayed alive for 8 seconds and
      exited cleanly after termination; no startup log output was produced.
- [x] The new app bundle is approximately 106MB (`slim_audit.py` reports 110,813,889
      bytes). The currently installed older bundle is approximately 131MB and still
      contains `app/resources/resources.qrc` and `QtPdf`, so the local A/B indicates
      approximately 25MB (19%) installed-bundle reduction.
- [ ] Campus-network login, TUN/proxy connection, helper install/uninstall, and sustained
      RSS/CPU scenarios remain unverified on this run because they require real credentials,
      network access, and/or elevation.
