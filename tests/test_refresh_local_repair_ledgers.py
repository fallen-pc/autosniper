from __future__ import annotations

import os
from pathlib import Path

import scripts.refresh_local_repair_ledgers as refresh


def _write_with_mtime(path: Path, content: str, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_outputs_are_stale_when_any_output_is_missing(tmp_path) -> None:
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    _write_with_mtime(source, "source", 100)

    assert refresh.outputs_are_stale([source], [output]) is True


def test_outputs_are_stale_when_an_input_is_newer(tmp_path) -> None:
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    _write_with_mtime(source, "source", 200)
    _write_with_mtime(output, "output", 100)

    assert refresh.outputs_are_stale([source], [output]) is True


def test_outputs_are_current_when_every_output_is_newer(tmp_path) -> None:
    source = tmp_path / "source.csv"
    outputs = [tmp_path / "one.csv", tmp_path / "two.json"]
    _write_with_mtime(source, "source", 100)
    for output in outputs:
        _write_with_mtime(output, "output", 200)

    assert refresh.outputs_are_stale([source], outputs) is False


def test_refresh_runs_only_stale_builder(monkeypatch, tmp_path) -> None:
    audit_input = tmp_path / "audit-input.csv"
    audit_output = tmp_path / "audit-output.csv"
    matrix_input = tmp_path / "matrix-input.csv"
    matrix_output = tmp_path / "matrix-output.csv"
    _write_with_mtime(audit_input, "source", 100)
    _write_with_mtime(audit_output, "output", 200)
    _write_with_mtime(matrix_input, "source", 300)
    _write_with_mtime(matrix_output, "output", 200)
    calls: list[list[str]] = []

    monkeypatch.setattr(refresh, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(refresh, "REPAIR_AUDIT_INPUTS", (Path("audit-input.csv"),))
    monkeypatch.setattr(refresh, "REPAIR_AUDIT_OUTPUTS", (Path("audit-output.csv"),))
    monkeypatch.setattr(refresh, "PRICING_MATRIX_INPUTS", (Path("matrix-input.csv"),))
    monkeypatch.setattr(refresh, "PRICING_MATRIX_OUTPUTS", (Path("matrix-output.csv"),))
    monkeypatch.setattr(refresh, "_run_builder", lambda command: calls.append(command))

    rebuilt = refresh.refresh_derived_ledgers()

    assert rebuilt == (False, True)
    assert len(calls) == 1
    assert calls[0][-2:] == ["--limit", "0"]


def test_sync_runtime_sources_preserves_unchanged_destination(monkeypatch, tmp_path) -> None:
    relative = Path("CSV_data/scrapers/sold_cars.csv")
    destination = tmp_path / relative
    _write_with_mtime(destination, "url,general_condition\n1,dent\n", 100)
    key_path = tmp_path / "key"
    key_path.write_text("key", encoding="utf-8")

    def fake_run(command, check):
        Path(command[-1]).write_text("url,general_condition\n1,dent\n", encoding="utf-8")

    monkeypatch.setattr(refresh, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(refresh, "RUNTIME_SOURCE_PATHS", (relative,))
    monkeypatch.setattr(refresh.subprocess, "run", fake_run)

    changed = refresh.sync_runtime_sources(
        host="example.test",
        user="root",
        key_path=key_path,
        remote_root="/opt/autosniper",
    )

    assert changed == []
    assert destination.read_text(encoding="utf-8") == "url,general_condition\n1,dent\n"
