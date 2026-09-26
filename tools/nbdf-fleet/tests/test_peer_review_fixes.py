# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Regression tests for the pass-2 peer review (findings F1-F8)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from nbdf_fleet import output as output_module
from nbdf_fleet.analysis import load_and_validate
from nbdf_fleet.cli import EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, EXIT_VALIDATION, main
from nbdf_fleet.config import ConfigError, build_config, load_config
from nbdf_fleet.ingest import load_services, load_vehicles
from nbdf_fleet.models import Severity
from nbdf_fleet.output import PlannedFile, write_outputs
from nbdf_fleet.reports import render_csv
from tests.conftest import PROJECT_DIR, SERVICE_HEADER, VEHICLE_HEADER, minimal_config_dict, write_csv

AS_OF = date(2026, 6, 30)
DEFAULT_TOML = (PROJECT_DIR / "config" / "default_rules.toml").read_text(encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(folder: Path) -> dict[str, str]:
    return {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}


@pytest.fixture
def fleet(tmp_path):
    v = write_csv(tmp_path / "vehicles.csv", VEHICLE_HEADER, ["V1,2020,M,X,light-duty,D,2020-01-01,10000,"])
    s = write_csv(tmp_path / "services.csv", SERVICE_HEADER, ["V1,2026-04-01,Oil change,9000,,10,,"])
    c = tmp_path / "rules.toml"
    c.write_text(DEFAULT_TOML, encoding="utf-8")
    return v, s, c


# ===========================================================================
# F1 - outputs may never overwrite inputs, with or without --force
# ===========================================================================


@pytest.mark.parametrize("victim", ["vehicle", "service", "config"])
@pytest.mark.parametrize("force", [False, True])
def test_report_output_cannot_be_an_input(fleet, capsys, victim, force):
    v, s, c = fleet
    target = {"vehicle": v, "service": s, "config": c}[victim]
    before = {p: sha(p) for p in (v, s, c)}
    argv = ["report", str(v), str(s), "--config", str(c), "--as-of", "2026-06-30",
            "--format", "json", "--output", str(target)]
    if force:
        argv.append("--force")
    assert main(argv) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "input file" in err and "--force does not override" in err
    assert {p: sha(p) for p in (v, s, c)} == before


def test_equivalent_spellings_of_an_input_are_recognized(fleet, capsys, monkeypatch):
    v, s, c = fleet
    monkeypatch.chdir(v.parent)
    before = sha(v)
    sub = v.parent / "sub"
    sub.mkdir()
    for spelling in ("vehicles.csv", ".\\vehicles.csv", "sub\\..\\vehicles.csv", "VEHICLES.CSV",
                     str(v).upper()):
        argv = ["report", "vehicles.csv", "services.csv", "--as-of", "2026-06-30",
                "--format", "csv", "--output", spelling, "--force"]
        assert main(argv) == EXIT_USAGE, spelling
    capsys.readouterr()
    assert sha(v) == before


def test_review_f1_reproduction_is_refused(tmp_path, capsys, monkeypatch):
    """The review's exact case: report victim.csv s.csv ... --output victim.csv --force."""
    monkeypatch.chdir(tmp_path)
    write_csv(tmp_path / "victim.csv", VEHICLE_HEADER, ["V1,,,,light-duty,,,10000,"])
    write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,2026-04-01,Oil change,9000,,,,"])
    before = sha(tmp_path / "victim.csv")
    code = main(["report", "victim.csv", "s.csv", "--as-of", "2026-06-30",
                 "--format", "json", "--output", "victim.csv", "--force"])
    assert code == EXIT_USAGE
    assert sha(tmp_path / "victim.csv") == before


@pytest.mark.parametrize("name", ["fleet_analysis.csv", "fleet_analysis.json", "findings.csv"])
def test_analyze_output_dir_cannot_overwrite_an_input(tmp_path, capsys, name):
    # The inventory itself lives in the output folder under a bundle name.
    v = write_csv(tmp_path / name, VEHICLE_HEADER, ["V1,,,,light-duty,,,10000,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,2026-04-01,Oil change,9000,,,,"])
    before = snapshot(tmp_path)
    code = main(["analyze", str(v), str(s), "--as-of", "2026-06-30",
                 "--output-dir", str(tmp_path), "--force"])
    assert code == EXIT_USAGE
    assert snapshot(tmp_path) == before  # nothing written, nothing replaced


def test_demo_output_dir_cannot_overwrite_its_config(tmp_path, capsys):
    c = tmp_path / "fleet_analysis.json"
    c.write_text(DEFAULT_TOML, encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["demo", "--config", str(c), "--output-dir", str(tmp_path), "--force"]) == EXIT_USAGE
    assert snapshot(tmp_path) == before


# ===========================================================================
# F2 - malformed CSV is an ERROR naming file and row, never a silent change
# ===========================================================================


def test_review_f2_extra_field_is_an_error_not_a_changed_reading(tmp_path, capsys):
    # The review's row: an unquoted thousands separator splits 10,000 in two.
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, [
        "V1,2020,Make,Model,light-duty,Dept,2020-01-01,10,000,500",
        "V2,2020,Make,Model,light-duty,Dept,2020-01-01,5000,",
    ])
    vehicles, findings = load_vehicles(v)
    assert [x.vehicle_id for x in vehicles] == ["V2"]  # the damaged row never reaches analysis
    bad = [f for f in findings if f.code == "wrong_field_count"]
    assert len(bad) == 1
    assert (bad[0].severity, bad[0].file, bad[0].row) == (Severity.ERROR, "v.csv", 2)
    assert "10 fields but the header has 9" in bad[0].message
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V2,2026-04-01,Oil change,4000,,,,"])
    assert main(["validate", str(v), str(s), "--as-of", "2026-06-30"]) == EXIT_VALIDATION
    out = capsys.readouterr().out
    assert "ERROR   wrong_field_count  v.csv row 2" in out
    assert main(["report", str(v), str(s), "--as-of", "2026-06-30", "--format", "json"]) == EXIT_VALIDATION


def test_too_few_fields_is_an_error(tmp_path):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,2020,Make,Model,light-duty"])
    vehicles, findings = load_vehicles(v)
    assert vehicles == []
    assert [(f.code, f.row) for f in findings] == [("wrong_field_count", 2)]
    assert "5 fields but the header has 9" in findings[0].message


@pytest.mark.parametrize(
    "row",
    [
        'V1,2020,Make,Model,light-duty,"Streets Division,2020-01-01,10000,',  # never closed
        'V1,2020,Make,Model,light-duty,"Streets" Division,2020-01-01,10000,',  # text after quote
    ],
)
def test_review_f2_broken_quoting_is_an_error(tmp_path, capsys, row):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V0,2020,Make,Model,light-duty,Dept,2020-01-01,1,", row])
    vehicles, findings = load_vehicles(v)
    codes = [(f.code, f.row, f.severity) for f in findings]
    assert ("malformed_csv", 3, Severity.ERROR) in codes
    assert all(x.vehicle_id != "V1" for x in vehicles)
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V0,2026-04-01,Oil change,1,,,,"])
    assert main(["validate", str(v), str(s), "--as-of", "2026-06-30"]) == EXIT_VALIDATION
    assert "malformed_csv  v.csv row 3" in capsys.readouterr().out


def test_legitimate_quoting_and_empty_fields_still_work(tmp_path):
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        'V1,2026-04-01,Oil change,9000,,10,,"note with a comma, and ""quotes"""',
        'V1,2026-04-02,Brakes,9001,,,,"two-line',
        'note"',
        "V1,2026-04-03,Tires,,,,,",
    ])
    services, findings = load_services(s)
    assert findings == []
    assert [r.row for r in services] == [2, 3, 5]  # multi-line record reports its first line
    assert services[0].notes == 'note with a comma, and "quotes"'
    assert services[1].notes == "two-line\nnote"
    assert services[2].odometer is None and services[2].cost is None  # blank stays missing


# ===========================================================================
# F3 - failure-safe output
# ===========================================================================


def test_existing_file_blocks_the_whole_bundle_before_any_write(fleet, tmp_path, capsys):
    v, s, _ = fleet
    out = tmp_path / "out"
    out.mkdir()
    (out / "fleet_analysis.json").write_text("OLD", encoding="utf-8")
    before = snapshot(out)
    assert main(["analyze", str(v), str(s), "--as-of", "2026-06-30", "--output-dir", str(out)]) == EXIT_USAGE
    assert "nothing was written" in capsys.readouterr().err
    assert snapshot(out) == before  # the review saw a new CSV appear here


def _old_bundle(out: Path) -> dict[str, str]:
    out.mkdir(parents=True, exist_ok=True)
    for name in ("fleet_analysis.csv", "fleet_analysis.json", "findings.csv"):
        (out / name).write_text(f"OLD {name}\n", encoding="utf-8")
    return snapshot(out)


def test_write_failure_mid_bundle_leaves_directory_unchanged(fleet, tmp_path, capsys, monkeypatch):
    v, s, _ = fleet
    out = tmp_path / "out"
    before = _old_bundle(out)
    real = output_module._write_temp
    calls = {"n": 0}

    def flaky(item):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(28, "No space left on device (simulated)")
        return real(item)

    monkeypatch.setattr(output_module, "_write_temp", flaky)
    code = main(["analyze", str(v), str(s), "--as-of", "2026-06-30", "--output-dir", str(out), "--force"])
    assert code == EXIT_USAGE
    assert "nothing was changed" in capsys.readouterr().err
    assert snapshot(out) == before  # old bundle intact, no temp files


def test_swap_failure_rolls_back_already_replaced_files(fleet, tmp_path, capsys, monkeypatch):
    v, s, _ = fleet
    out = tmp_path / "out"
    before = _old_bundle(out)
    real = output_module._replace
    calls = {"n": 0}

    def flaky(temp, destination):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(5, "I/O error (simulated)")
        return real(temp, destination)

    monkeypatch.setattr(output_module, "_replace", flaky)
    code = main(["analyze", str(v), str(s), "--as-of", "2026-06-30", "--output-dir", str(out), "--force"])
    assert code == EXIT_USAGE
    assert "restored" in capsys.readouterr().err
    assert snapshot(out) == before  # files 1 and 2 were swapped back; no .nbdf-* leftovers


def test_single_file_failure_after_partial_write_leaves_no_truncated_file(tmp_path, monkeypatch):
    """The review's case: a failure mid-write used to leave a 7-byte fragment.

    The real _write_temp runs; fsync fails after the bytes reached the temp
    file, which is the point where a full disk or I/O error would strike.
    """
    def broken_fsync(fd):
        raise OSError(28, "No space left on device (simulated)")

    monkeypatch.setattr(output_module.os, "fsync", broken_fsync)
    target = tmp_path / "report.json"
    target.write_text('{"complete": "old report"}\n', encoding="utf-8")
    before = snapshot(tmp_path)
    with pytest.raises(output_module.OutputError):
        write_outputs([PlannedFile(target, "x" * 100_000)], force=True)
    assert snapshot(tmp_path) == before  # old report intact, temp removed
    new_target = tmp_path / "new.json"
    with pytest.raises(output_module.OutputError):
        write_outputs([PlannedFile(new_target, "x" * 100_000)], force=False)
    assert not new_target.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json"]


def test_failure_removes_directories_it_created(tmp_path, monkeypatch):
    def always_fail(item):
        raise OSError(28, "No space left on device (simulated)")

    monkeypatch.setattr(output_module, "_write_temp", always_fail)
    with pytest.raises(output_module.OutputError):
        write_outputs([PlannedFile(tmp_path / "new" / "deeper" / "x.csv", "a")], force=False)
    assert list(tmp_path.iterdir()) == []


# ===========================================================================
# F4 - unknown configuration keys and wrong types are errors
# ===========================================================================


def test_review_f4_placeholder_typo_is_rejected():
    data = minimal_config_dict(meta={"placeholder_interval": True})
    with pytest.raises(ConfigError, match=r"unknown key\(s\) in \[meta\]: placeholder_interval"):
        build_config(data, "t")


def test_review_f4_interval_months_typo_is_rejected():
    data = minimal_config_dict()
    data["tasks"][0]["schedules"][0] = {"asset_classes": ["light-duty"], "interval_miles": 5000,
                                        "interval_month": 6}
    with pytest.raises(ConfigError, match="interval_month"):
        build_config(data, "t")


def test_review_f4_schema_version_true_is_rejected():
    data = minimal_config_dict()
    data["schema_version"] = True
    with pytest.raises(ConfigError, match="schema_version must be the whole number 1"):
        build_config(data, "t")


@pytest.mark.parametrize(
    "mutate, where",
    [
        (lambda d: d.update(extra_table={}), "the top level"),
        (lambda d: d["thresholds"].update(due_soon=0.8), "[thresholds]"),
        (lambda d: d["validation"].update(max_mile_per_day=1), "[validation]"),
        (lambda d: d["baseline"].update(assume_baseline=True), "[baseline]"),
        (lambda d: d["scoring"].update(methd="rules"), "[scoring]"),
        (lambda d: d["scoring"]["weights"].update(repeat=0.0), "[scoring.weights]"),
        (lambda d: d["scoring"]["bands"].update(low=10), "[scoring.bands]"),
        (lambda d: d["asset_classes"][0].update(meter="miles"), "asset_classes[0]"),
        (lambda d: d["tasks"][0].update(alias=["x"]), "tasks[0]"),
        (lambda d: d["tasks"][1]["schedules"][0].update(interval_mile=1), "schedules[0]"),
    ],
)
def test_unknown_keys_rejected_in_every_table(mutate, where):
    data = minimal_config_dict()
    mutate(data)
    with pytest.raises(ConfigError, match=r"unknown key") as info:
        build_config(data, "t")
    assert where in str(info.value)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d["validation"].update(min_model_year=True), "min_model_year must be a whole number"),
        (lambda d: d["validation"].update(max_model_years_ahead=False), "must be a whole number"),
        (lambda d: d["scoring"].update(repeat_lookback_months=True), "must be a whole number"),
        (lambda d: d["scoring"].update(repeat_saturation_count=True), "must be a whole number"),
        (lambda d: d["tasks"][0]["schedules"][0].update(interval_months=True), "positive whole number"),
        (lambda d: d["tasks"][0]["schedules"][0].update(interval_months=6.0), "positive whole number"),
        (lambda d: d["thresholds"].update(due_soon_utilization=True), "must be a number"),
    ],
)
def test_bool_is_never_accepted_as_a_number(mutate, fragment):
    data = minimal_config_dict()
    mutate(data)
    with pytest.raises(ConfigError, match=fragment):
        build_config(data, "t")


def test_bundled_default_config_passes_strict_checks():
    assert load_config(None).placeholder_intervals is True


# ===========================================================================
# F5 - the release builder never deletes files it did not create
# ===========================================================================


def _builder():
    spec = importlib.util.spec_from_file_location("build_release", PROJECT_DIR / "scripts" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_builder_refuses_folder_with_unrelated_files_and_keeps_them(tmp_path):
    builder = _builder()
    out = tmp_path / "dist"
    out.mkdir()
    sentinel = out / "KEEP.txt"
    sentinel.write_text("do not delete", encoding="utf-8")
    with pytest.raises(SystemExit, match="did not create: KEEP.txt"):
        builder.main(["--outdir", str(out)])
    with pytest.raises(SystemExit, match="did not create"):
        builder.main(["--outdir", str(out), "--replace"])  # --replace never covers foreign files
    assert sentinel.read_text(encoding="utf-8") == "do not delete"


def test_builder_requires_replace_for_existing_artifacts(tmp_path):
    builder = _builder()
    out = tmp_path / "dist"
    out.mkdir()
    for name in ("nbdf_fleet-0.1.0-py3-none-any.whl", "nbdf-fleet-0.1.0-source.zip", "SHA256SUMS.txt"):
        (out / name).write_text("old", encoding="utf-8")
    with pytest.raises(SystemExit, match="--replace"):
        builder.check_outdir(out, replace=False)
    builder.check_outdir(out, replace=True)  # allowed; replaces only those names later
    builder.check_outdir(tmp_path / "fresh", replace=False)  # new folder is fine


def test_builder_refuses_any_folder_inside_the_repository():
    builder = _builder()
    repo = builder.repository_root(PROJECT_DIR)
    assert repo is not None and (repo / ".git").exists()
    for inside in (repo / "release", PROJECT_DIR / "dist", repo / "assets" / "x"):
        with pytest.raises(SystemExit, match="outside the repository"):
            builder.check_outdir(inside, replace=True)


def test_builder_source_has_no_blanket_delete():
    text = (PROJECT_DIR / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert ".unlink(" not in text and "rmtree" not in text and "os.remove" not in text


# ===========================================================================
# F6 - bad values are validation/config errors, never internal errors
# ===========================================================================


def _config_file(tmp_path, old: str, new: str) -> Path:
    assert old in DEFAULT_TOML
    path = tmp_path / "bad.toml"
    path.write_text(DEFAULT_TOML.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "old, new, fragment",
    [
        ("due_soon_utilization = 0.85", "due_soon_utilization = nan", "must be a finite number"),
        ("interval_miles = 5000", "interval_miles = inf", "must be a finite number"),
        ("interval_miles = 5000", "interval_miles = nan", "must be a finite number"),
        ("interval_months = 6", "interval_months = 999999", "at most 1200"),
        ("min_model_year = 1950", "min_model_year = " + "9" * 4400, "cannot be read"),
        ("max_miles_per_day = 600", "max_miles_per_day = " + "9" * 30, "too large"),
    ],
)
def test_bad_config_values_exit_two_with_a_message(fleet, tmp_path, capsys, old, new, fragment):
    v, s, _ = fleet
    cfg = _config_file(tmp_path, old, new)
    code = main(["analyze", str(v), str(s), "--config", str(cfg), "--as-of", "2026-06-30"])
    err = capsys.readouterr().err
    assert code == EXIT_USAGE, err
    assert fragment in err and "internal error" not in err


def test_oversized_text_field_is_a_validation_error(tmp_path, capsys):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,2020,M,X,light-duty," + "D" * 131_073 + ",,1,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,2026-04-01,Oil change,1,,,,"])
    code = main(["validate", str(v), str(s), "--as-of", "2026-06-30"])
    out = capsys.readouterr()
    assert code == EXIT_VALIDATION and "internal error" not in out.err
    assert "malformed_csv  v.csv row 2" in out.out and "longer than" in out.out


@pytest.mark.parametrize(
    "row, field",
    [
        ("V1," + "2" * 4400 + ",M,X,light-duty,D,2020-01-01,1,", "year"),
        ("V1,2020,M,X,light-duty,D,2020-01-01," + "9" * 400 + ",", "current_odometer"),
        ("V1,2020,M,X,light-duty,D,2020-01-01,4249.9999999999999999999999999999,", "current_odometer"),
    ],
)
def test_oversized_numbers_are_validation_errors(tmp_path, capsys, row, field):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, [row])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,2026-04-01,Oil change,1,,,,"])
    code = main(["analyze", str(v), str(s), "--as-of", "2026-06-30"])
    out = capsys.readouterr()
    assert code == EXIT_VALIDATION and "internal error" not in out.err
    assert f"number_out_of_range  v.csv row 2 [{field}]" in out.out


def test_ordinary_precision_still_accepted(tmp_path):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,2020,M,X,light-duty,D,2020-01-01,999999999999.123456,0.5"])
    vehicles, findings = load_vehicles(v)
    assert findings == []
    assert vehicles[0].current_odometer == Decimal("999999999999.123456")


def test_service_date_near_end_of_calendar_is_a_validation_error(tmp_path, capsys, config):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,2020,M,X,light-duty,D,2020-01-01,10000,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,9999-12-15,Oil change,9000,,,,"])
    code = main(["analyze", str(v), str(s), "--as-of", "9999-12-31"])
    out = capsys.readouterr()
    assert code == EXIT_VALIDATION and "internal error" not in out.err
    assert "date_out_of_range  s.csv row 2 [service_date]" in out.out
    findings, _, _ = load_and_validate(v, s, config, date(9999, 12, 31))
    assert [f.code for f in findings if f.severity is Severity.ERROR] == ["date_out_of_range"]


def test_existing_file_as_output_parent_is_a_usage_error(fleet, tmp_path, capsys):
    v, s, _ = fleet
    blocker = tmp_path / "notadir"
    blocker.write_text("x", encoding="utf-8")
    for argv in (
        ["report", str(v), str(s), "--as-of", "2026-06-30", "--format", "csv", "--output", str(blocker / "r.csv")],
        ["analyze", str(v), str(s), "--as-of", "2026-06-30", "--output-dir", str(blocker / "out")],
        ["init", str(blocker / "ws")],
    ):
        code = main(argv)
        err = capsys.readouterr().err
        assert code == EXIT_USAGE, argv
        assert "is a file, not a directory" in err and "internal error" not in err
    assert blocker.read_text(encoding="utf-8") == "x"


def test_internal_errors_are_still_exit_three(fleet, monkeypatch, capsys):
    from nbdf_fleet import cli

    v, s, _ = fleet
    monkeypatch.setattr(cli, "run_analysis", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert main(["analyze", str(v), str(s), "--as-of", "2026-06-30"]) == EXIT_INTERNAL


# ===========================================================================
# F7 - printed guidance works as printed
# ===========================================================================


def test_init_quotes_paths_with_spaces(tmp_path, capsys):
    target = tmp_path / "my fleet data"
    assert main(["init", str(target)]) == EXIT_OK
    out = capsys.readouterr().out
    quoted = f'"{target / "vehicles.csv"}"'
    assert f"nbdf-fleet validate {quoted}" in out
    assert f'--config "{target / "rules.toml"}"' in out
    assert f"explain  {quoted}" in out


def test_explain_help_and_report_hint_show_all_three_arguments(examples, capsys):
    with pytest.raises(SystemExit) as info:
        main(["explain", "--help"])
    assert info.value.code == 0
    usage = capsys.readouterr().out
    assert "vehicle-file service-file vehicle-id" in usage
    assert main(["analyze", str(examples / "demo_vehicles.csv"), str(examples / "demo_service_history.csv"),
                 "--as-of", "2026-06-30"]) == EXIT_OK
    report = capsys.readouterr().out
    assert "nbdf-fleet explain <vehicle-file> <service-file> <vehicle-id> --as-of 2026-06-30" in report
    assert "Use 'explain <vehicle-id>'" not in report


def test_demo_points_wheel_users_to_init_not_examples(capsys):
    assert main(["demo"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "copy examples/" not in out
    assert "nbdf-fleet init nbdf-fleet-data" in out
    assert "intentional examples of warning output" in out


def test_duplicate_record_fix_no_longer_suggests_notes(tmp_path, config):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,,,,light-duty,,,10000,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        "V1,2026-04-01,Oil change,9000,,10,,first",
        "V1,2026-04-01,Oil change,9000,,10,,second - a different note is still a duplicate",
    ])
    findings, _, _ = load_and_validate(v, s, config, AS_OF)
    dup = next(f for f in findings if f.code == "duplicate_service_record")
    assert "notes are not compared" in dup.message
    assert "note" not in dup.fix
    assert "date, readings, or cost" in dup.fix


# ===========================================================================
# F8 - documentation matches what CSV actually carries
# ===========================================================================


def test_csv_context_claims_match_the_output(examples, config):
    from nbdf_fleet.analysis import run_analysis

    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    csv_text = render_csv(result)
    assert "heuristic" not in csv_text.lower() and "2026-06-30" not in csv_text  # by design
    docs = (PROJECT_DIR / "docs" / "scoring-method.md").read_text(encoding="utf-8")
    assert "printed in every format" not in docs
    assert "Metadata in every export" not in docs
    assert "not in the flat CSV" in docs
    for name in ("README.md", "docs/configuration.md", "docs/sample-output.md"):
        text = (PROJECT_DIR / name).read_text(encoding="utf-8")
        assert "Every report\ncarries this disclaimer" not in text


def test_json_still_carries_full_context(examples, config):
    from nbdf_fleet.analysis import run_analysis
    from nbdf_fleet.reports import render_json

    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    meta = json.loads(render_json(result))["metadata"]
    for key in ("as_of", "tool_version", "schema_version", "config_hash", "scoring_method",
                "placeholder_config", "disclaimer"):
        assert meta[key] not in (None, "")
