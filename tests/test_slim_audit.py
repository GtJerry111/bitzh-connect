import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "slim_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("slim_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


slim_audit = _load_module()


def test_classifies_known_processes():
    rows = slim_audit.parse_process_rows(
        "101 1 120000 2.0 BITZH Connect\n102 1 900000 40.0 zju-connect"
    )
    assert rows[0].name == "gui"
    assert rows[1].name == "kernel"


def test_classifies_linux_gui_process():
    rows = slim_audit.parse_process_rows(
        "105 1 90000 1.0 /usr/lib/bitzh-connect/bitzh-connect\n106 1 7000 0.0 /usr/bin/python3"
    )
    assert rows[0].name == "gui"
    assert rows[1].name == "other"


def test_classifies_helper_and_other_processes():
    rows = slim_audit.parse_process_rows(
        "103 1 5000 0.1 bitzh-helper\n104 1 7000 0.0 /usr/bin/python3"
    )
    assert rows[0].name == "helper"
    assert rows[1].name == "other"


def test_parse_reads_stable_columns():
    rows = slim_audit.parse_process_rows("101 1 2048 2.5 /Applications/BITZH Connect")
    row = rows[0]
    assert row.pid == 101
    assert row.ppid == 1
    assert row.rss_mb == 2.0
    assert row.cpu_percent == 2.5
    assert row.threads is None
    assert row.command == "/Applications/BITZH Connect"


def test_parse_marks_unavailable_cpu_as_none_and_reads_threads():
    rows = slim_audit.parse_process_rows(
        "101 1 2048 NA 7 BITZH Connect", threads_column=True
    )
    assert rows[0].cpu_percent is None
    assert rows[0].threads == 7


def test_artifact_totals_are_deterministic(tmp_path):
    (tmp_path / "a").write_bytes(b"123")
    (tmp_path / "b").write_bytes(b"12345")
    assert slim_audit.artifact_size(tmp_path) == 8


def test_artifact_size_missing_path_is_zero(tmp_path):
    assert slim_audit.artifact_size(tmp_path / "missing") == 0


def test_largest_files_sorted_and_limited(tmp_path):
    for index in range(25):
        (tmp_path / f"f{index:02d}").write_bytes(b"x" * (index + 1))
    largest = slim_audit.largest_files(tmp_path, limit=20)
    assert len(largest) == 20
    assert largest[0]["bytes"] == 25
    sizes = [entry["bytes"] for entry in largest]
    assert sizes == sorted(sizes, reverse=True)


def test_artifact_command_is_read_only(tmp_path, capsys):
    (tmp_path / "a").write_bytes(b"123")
    before = sorted(
        (path.name, path.read_bytes()) for path in tmp_path.rglob("*") if path.is_file()
    )
    slim_audit.main(["artifact", str(tmp_path)])
    after = sorted(
        (path.name, path.read_bytes()) for path in tmp_path.rglob("*") if path.is_file()
    )
    assert before == after


def test_artifact_command_emits_json(tmp_path, capsys):
    (tmp_path / "a").write_bytes(b"123")
    assert slim_audit.main(["artifact", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["available"] is True
    assert payload["total_bytes"] == 3
    assert payload["largest_files"] == [{"path": "a", "bytes": 3}]


def test_artifact_command_missing_path_reports_unavailable(tmp_path, capsys):
    assert slim_audit.main(["artifact", str(tmp_path / "nope")]) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["available"] is False
    assert payload["reason"]


def test_processes_command_emits_stable_records(monkeypatch, capsys):
    monkeypatch.setattr(
        slim_audit,
        "_collect_process_output",
        lambda: ("101 1 120000 2.0 BITZH Connect\n102 1 900000 40.0 zju-connect", None),
    )
    assert slim_audit.main(["processes"]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert [record["kind"] for record in records] == ["gui", "kernel"]
    assert records[0]["command"] == "BITZH Connect"
    assert records[0]["rss_mb"] == round(120000 / 1024.0, 2)


def test_processes_command_unavailable_is_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(slim_audit, "_collect_process_output", lambda: (None, "ps failed"))
    assert slim_audit.main(["processes"]) == 0
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["available"] is False
    assert "ps failed" in payload["reason"]


def test_logs_command_reports_existing_and_missing(tmp_path, capsys, monkeypatch):
    log = tmp_path / "bitzh-connect.log"
    log.write_bytes(b"hello")
    monkeypatch.setattr(
        slim_audit, "known_log_paths", lambda: [str(log), str(tmp_path / "absent.log")]
    )
    assert slim_audit.main(["logs"]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert records[0] == {"available": True, "path": str(log), "exists": True, "bytes": 5}
    assert records[1]["exists"] is False
    assert records[1]["bytes"] == 0
