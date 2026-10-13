#!/usr/bin/env python3
"""只读审计脚本：统计进程运行态、产物体积与诊断日志。

设计约束：
- 只读——绝不删除、截断或写入任何文件，也不启动应用进程；
- 每条命令输出 JSON lines；平台命令或可选路径不可用时返回退出码 0，
  并输出一条 `available: false` 且带 `reason` 的记录；
- 纯解析/统计函数不依赖 QApplication（供测试离线注入数据）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_GUI_MARKERS = ("bitzh connect", "bitzh-connect")
_KERNEL_MARKERS = ("zju-connect",)
_HELPER_MARKERS = ("bitzh-helper",)


def classify(command: str) -> str:
    lowered = command.lower()
    if any(marker in lowered for marker in _KERNEL_MARKERS):
        return "kernel"
    if any(marker in lowered for marker in _HELPER_MARKERS):
        return "helper"
    if any(marker in lowered for marker in _GUI_MARKERS):
        return "gui"
    return "other"


@dataclass(frozen=True)
class ProcessRow:
    name: str
    pid: int
    ppid: int
    rss_mb: float
    cpu_percent: float | None
    threads: int | None
    command: str

    @property
    def kind(self) -> str:
        return self.name


def parse_process_rows(text: str, *, threads_column: bool = False) -> list[ProcessRow]:
    rows: list[ProcessRow] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 5 if threads_column else 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            rss_mb = int(parts[2]) / 1024.0
            cpu_percent = None if parts[3].upper() in {"NA", "N/A"} else float(parts[3])
        except ValueError:
            continue
        threads: int | None = None
        command_parts = parts[4:]
        if threads_column and len(command_parts) >= 2:
            try:
                threads = int(command_parts[0])
                command_parts = command_parts[1:]
            except ValueError:
                threads = None
        command = " ".join(command_parts)
        rows.append(
            ProcessRow(classify(command), pid, ppid, rss_mb, cpu_percent, threads, command)
        )
    return rows


def iter_files(root):
    base = Path(root)
    try:
        if base.is_file():
            yield base
            return
        for path in base.rglob("*"):
            if path.is_file():
                yield path
    except OSError:
        return


def artifact_size(root) -> int:
    total = 0
    for path in iter_files(root):
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def largest_files(root, limit: int = 20) -> list[dict]:
    entries: list[dict] = []
    for path in iter_files(root):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append({"path": _relative(path, root), "bytes": size})
    entries.sort(key=lambda entry: (-entry["bytes"], entry["path"]))
    return entries[:limit]


def _relative(path: Path, root) -> str:
    try:
        return os.path.relpath(str(path), os.path.abspath(str(root)))
    except ValueError:
        return str(path)


def log_records(paths):
    for path in paths:
        target = Path(path)
        try:
            exists = target.exists()
            size = target.stat().st_size if target.is_file() else 0
        except OSError as exc:
            yield {"available": False, "path": str(target), "reason": str(exc)}
            continue
        yield {"available": True, "path": str(target), "exists": exists, "bytes": size}


def _diagnostics_log_path() -> str:
    app_dir = str(Path(__file__).resolve().parent.parent / "app")
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        from utils import diagnostics

        return diagnostics.log_path()
    except Exception:
        return os.path.join(tempfile.gettempdir(), "BITZH Connect", "bitzh-connect.log")


def known_log_paths() -> list[str]:
    log = _diagnostics_log_path()
    paths = [log, log + ".1", log + ".2", log + ".3"]
    paths.extend(sorted(glob.glob(os.path.join(tempfile.gettempdir(), "bitzh-tun-*"))))
    return paths


def _collect_process_output():
    if os.name == "nt":
        return _powershell_process_output()
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,rss=,%cpu=,command="],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or "ps returned a non-zero status").strip()
    return proc.stdout, None


def _thread_count(pid: int) -> int | None:
    """Return a best-effort thread count without making CPU data up."""
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["ps", "-M", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        return max(len(lines) - 1, 0)
    if os.name != "nt":
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("Threads:"):
                    return int(line.split(":", 1)[1].strip())
        except (OSError, ValueError):
            return None
    return None


def _powershell_process_output():
    # Win32_Process 提供 ppid/线程数但不提供 CPU 百分比. CPU is null rather
    # than a fabricated zero so callers cannot mistake unavailable data for idle.
    command = (
        "Get-CimInstance Win32_Process | ForEach-Object { "
        "'{0} {1} {2} {3} {4} {5}' -f $_.ProcessId, $_.ParentProcessId, "
        "[int]($_.WorkingSetSize / 1KB), 'NA', $_.ThreadCount, $_.CommandLine }"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or "powershell returned a non-zero status").strip()
    return proc.stdout, None


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))


def cmd_artifact(path: str) -> int:
    root = os.path.abspath(path)
    if not os.path.exists(root):
        _emit({"available": False, "root": root, "reason": "path does not exist"})
        return 0
    _emit(
        {
            "available": True,
            "root": root,
            "total_bytes": artifact_size(root),
            "largest_files": largest_files(root),
        }
    )
    return 0


def cmd_processes() -> int:
    output, error = _collect_process_output()
    if output is None:
        _emit({"available": False, "reason": error or "process listing unavailable"})
        return 0
    rows = parse_process_rows(output, threads_column=(os.name == "nt"))
    if not rows:
        _emit({"available": False, "reason": "no process rows parsed"})
        return 0
    for row in rows:
        threads = row.threads if row.threads is not None else _thread_count(row.pid)
        cpu_percent = row.cpu_percent
        if os.name == "nt" and row.cpu_percent == 0.0 and "NA" in output:
            cpu_percent = None
        _emit(
            {
                "available": True,
                "kind": row.kind,
                "pid": row.pid,
                "ppid": row.ppid,
                "rss_mb": round(row.rss_mb, 2),
                "cpu_percent": cpu_percent,
                "threads": threads,
                "command": row.command,
            }
        )
    return 0


def cmd_logs() -> int:
    for record in log_records(known_log_paths()):
        _emit(record)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slim_audit.py", description="只读审计：进程、产物、日志"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    artifact = sub.add_parser("artifact", help="统计路径下的产物体积")
    artifact.add_argument("path")
    artifact.set_defaults(func=lambda args: cmd_artifact(args.path))
    sub.add_parser("processes", help="列出进程运行态").set_defaults(
        func=lambda args: cmd_processes()
    )
    sub.add_parser("logs", help="报告诊断与临时日志").set_defaults(
        func=lambda args: cmd_logs()
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
