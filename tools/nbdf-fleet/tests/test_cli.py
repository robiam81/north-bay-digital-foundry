# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

import json
import os
import subprocess
import sys

import pytest

from nbdf_fleet import cli
from nbdf_fleet.cli import EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def demo_args(examples, *extra):
    return [str(examples / "demo_vehicles.csv"), str(examples / "demo_service_history.csv"),
            "--as-of", "2026-06-30", *extra]


def test_validate_clean_set_exits_zero_with_warnings(examples, capsys):
    assert main(["validate", *demo_args(examples)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Errors:   0" in out
    assert "WARNING unknown_asset_class" in out


def test_validate_invalid_set_exits_one(invalid_examples, capsys):
    code = main(["validate", str(invalid_examples / "vehicles_invalid.csv"),
                 str(invalid_examples / "service_history_invalid.csv"), "--as-of", "2026-06-30"])
    assert code == EXIT_VALIDATION
    out = capsys.readouterr().out
    assert "ERROR   duplicate_vehicle_id" in out
    assert "fix:" in out


def test_analyze_blocked_by_errors_writes_nothing(invalid_examples, tmp_path, capsys):
    out_dir = tmp_path / "out"
    code = main(["analyze", str(invalid_examples / "vehicles_invalid.csv"),
                 str(invalid_examples / "service_history_invalid.csv"), "--as-of", "2026-06-30",
                 "--output-dir", str(out_dir)])
    assert code == EXIT_VALIDATION
    assert not out_dir.exists()


def test_analyze_writes_exports_and_refuses_overwrite(examples, tmp_path, capsys):
    out_dir = tmp_path / "out"
    assert main(["analyze", *demo_args(examples, "--output-dir", str(out_dir))]) == EXIT_OK
    assert {p.name for p in out_dir.iterdir()} == {"fleet_analysis.csv", "fleet_analysis.json", "findings.csv"}
    first = (out_dir / "fleet_analysis.json").read_bytes()
    assert main(["analyze", *demo_args(examples, "--output-dir", str(out_dir))]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "already exist" in err and "--force" in err
    assert (out_dir / "fleet_analysis.json").read_bytes() == first
    assert main(["analyze", *demo_args(examples, "--output-dir", str(out_dir), "--force")]) == EXIT_OK


def test_report_formats(examples, tmp_path, capsys):
    for fmt, marker in (("text", "FLEET SUMMARY"), ("csv", "rank,vehicle_id"),
                        ("json", '"metadata"'), ("html", "<!DOCTYPE html>")):
        assert main(["report", *demo_args(examples, "--format", fmt)]) == EXIT_OK
        assert marker in capsys.readouterr().out
    target = tmp_path / "r.html"
    assert main(["report", *demo_args(examples, "--format", "html", "--output", str(target))]) == EXIT_OK
    assert "Planning heuristic only" in target.read_text(encoding="utf-8")
    assert main(["report", *demo_args(examples, "--format", "html", "--output", str(target))]) == EXIT_USAGE


def test_explain_known_and_unknown_vehicle(examples, capsys):
    assert main(["explain", *demo_args(examples), "MD-401"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "utilization 0.8500" in out and "DUE SOON" in out
    assert main(["explain", *demo_args(examples), "NOPE"]) == EXIT_USAGE
    assert "not in demo_vehicles.csv" in capsys.readouterr().err


def test_demo_runs_clean(capsys):
    assert main(["demo"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "SYNTHETIC DEMO DATA" in out
    assert "As-of date:      2026-06-30" in out
    assert "explanation for LD-103" in out


def test_demo_output_dir(tmp_path, capsys):
    out_dir = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(out_dir)]) == EXIT_OK
    assert (out_dir / "fleet_analysis.html").exists()
    doc = json.loads((out_dir / "fleet_analysis.json").read_text(encoding="utf-8"))
    assert doc["summary"]["vehicles"] == 13
    assert doc["summary"]["errors"] == 0


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["analyze", "missing.csv", "also-missing.csv"],
        ["analyze", "a.csv", "b.csv", "--as-of", "6/30/26"],
        ["report", "a.csv", "b.csv"],  # --format is required
    ],
)
def test_usage_errors_exit_two(argv, capsys):
    assert main(argv) == EXIT_USAGE
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_bad_config_exits_two(examples, tmp_path, capsys):
    bad = tmp_path / "rules.toml"
    bad.write_text("schema_version = 1\n[thresholds]\ndue_soon_utilization = 2\n", encoding="utf-8")
    assert main(["analyze", *demo_args(examples, "--config", str(bad))]) == EXIT_USAGE
    assert "due_soon_utilization" in capsys.readouterr().err


def test_internal_error_exits_three_and_debug_shows_traceback(examples, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(cli, "run_analysis", boom)
    assert main(["analyze", *demo_args(examples)]) == EXIT_INTERNAL
    err = capsys.readouterr().err
    assert "internal error" in err and "Traceback" not in err
    assert main(["--debug", "analyze", *demo_args(examples)]) == EXIT_INTERNAL
    assert "Traceback" in capsys.readouterr().err


def test_end_to_end_subprocess_runs_are_byte_identical(examples, tmp_path):
    runs = []
    for name in ("one", "two"):
        out_dir = tmp_path / name
        proc = subprocess.run(
            [sys.executable, "-m", "nbdf_fleet", "analyze", *demo_args(examples, "--output-dir", str(out_dir))],
            capture_output=True, text=True, env=ENV, cwd=str(tmp_path),
        )
        assert proc.returncode == EXIT_OK, proc.stderr
        assert "Traceback" not in proc.stderr
        runs.append({p.name: p.read_bytes() for p in out_dir.iterdir()})
    assert runs[0] == runs[1]
    assert set(runs[0]) == {"fleet_analysis.csv", "fleet_analysis.json", "findings.csv"}
    assert b"\r\n" in runs[0]["fleet_analysis.csv"]


def test_console_script_module_entry_reports_version():
    proc = subprocess.run([sys.executable, "-m", "nbdf_fleet", "--version"],
                          capture_output=True, text=True, env=ENV)
    assert proc.returncode == 0
    assert proc.stdout.strip().startswith("nbdf-fleet ")


def test_closed_output_pipe_is_not_an_internal_error(examples):
    """Regression: `nbdf-fleet report ... | head` used to print
    'internal error: BrokenPipeError' when the reader closed the pipe."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "nbdf_fleet", "report", *demo_args(examples, "--format", "json")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV,
    )
    assert proc.stdout is not None and proc.stderr is not None
    proc.stdout.read(64)   # take a little output, then walk away
    proc.stdout.close()
    stderr = proc.stderr.read().decode("utf-8", "replace")
    proc.wait(timeout=60)
    assert "internal error" not in stderr
    assert "Traceback" not in stderr
    assert proc.returncode == EXIT_OK


def test_legacy_console_encoding_does_not_crash(examples, tmp_path):
    """Simulate a cp437 console: output must not raise UnicodeEncodeError."""
    v = tmp_path / "v.csv"
    s = tmp_path / "s.csv"
    v.write_text(
        "vehicle_id,asset_class,current_odometer\nVé-1,light-duty,10000\n", encoding="utf-8"
    )
    s.write_text("vehicle_id,service_date,service_type,odometer\nVé-1,2026-01-01,Oil change,5000\n",
                 encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "nbdf_fleet", "analyze", str(v), str(s), "--as-of", "2026-06-30"],
        capture_output=True, env={**ENV, "PYTHONIOENCODING": "cp437", "PYTHONUTF8": "0"},
    )
    assert proc.returncode == EXIT_OK, proc.stderr
    assert b"Traceback" not in proc.stderr
