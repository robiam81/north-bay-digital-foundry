# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Pass-2 hardening: path-independent outputs, single-sourced version,
resource loading, CSV sanitization scope, excluded-record counts."""

from __future__ import annotations

import csv
import importlib.metadata
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import nbdf_fleet
from nbdf_fleet.analysis import run_analysis
from nbdf_fleet.cli import VERSION_TEXT, main
from nbdf_fleet.config import BUNDLED_SOURCE, load_config
from nbdf_fleet.models import (
    AnalysisMetadata,
    AnalysisResult,
    ScoreResult,
    Status,
    Vehicle,
    VehicleAssessment,
    VehicleResult,
)
from nbdf_fleet.reports import render_csv, render_html, render_json, render_text
from nbdf_fleet.reports.csv_out import _cell
from tests.conftest import PROJECT_DIR, SERVICE_HEADER, VEHICLE_HEADER, write_csv

AS_OF = date(2026, 6, 30)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SRC = PROJECT_DIR / "src" / "nbdf_fleet"


# ---------------------------------------------------------------------------
# 1.1 config_source and path independence
# ---------------------------------------------------------------------------


def test_config_source_is_name_only(tmp_path, examples):
    bundled = load_config(None)
    assert bundled.source == BUNDLED_SOURCE
    nested = tmp_path / "deep" / "er" / "my rules.toml"
    nested.parent.mkdir(parents=True)
    nested.write_bytes((PROJECT_DIR / "config" / "default_rules.toml").read_bytes())
    loaded = load_config(nested)
    assert loaded.source == "my rules.toml"
    assert str(tmp_path) not in loaded.source


def test_outputs_contain_no_machine_paths_from_two_directories(tmp_path, examples):
    """Identical inputs run from two different directories -> identical bytes."""
    outputs = []
    for name in ("alpha", "beta/nested"):
        work = tmp_path / name
        work.mkdir(parents=True)
        for csv_name in ("demo_vehicles.csv", "demo_service_history.csv"):
            shutil.copy(examples / csv_name, work / csv_name)
        shutil.copy(PROJECT_DIR / "config" / "default_rules.toml", work / "rules.toml")
        out_dir = work / "out"
        proc = subprocess.run(
            [sys.executable, "-m", "nbdf_fleet", "analyze", "demo_vehicles.csv",
             "demo_service_history.csv", "--config", "rules.toml", "--as-of", "2026-06-30",
             "--output-dir", str(out_dir)],
            cwd=str(work), capture_output=True, text=True, env=ENV,
        )
        assert proc.returncode == 0, proc.stderr
        files = {p.name: p.read_bytes() for p in out_dir.iterdir()}
        for content in files.values():
            assert str(work).encode() not in content
            assert str(tmp_path).encode() not in content
        outputs.append(files)
    assert outputs[0] == outputs[1]
    doc = json.loads(outputs[0]["fleet_analysis.json"])
    assert doc["metadata"]["config_source"] == "rules.toml"
    assert doc["metadata"]["vehicle_file"] == "demo_vehicles.csv"


# ---------------------------------------------------------------------------
# 1.5 single-sourced version
# ---------------------------------------------------------------------------


def test_version_is_single_sourced(examples, capsys):
    assert nbdf_fleet.__version__ == "0.1.0"
    pyproject = tomllib.loads((PROJECT_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in pyproject["project"]["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "nbdf_fleet.__version__"}
    assert importlib.metadata.version("nbdf-fleet") == nbdf_fleet.__version__
    assert VERSION_TEXT == "nbdf-fleet 0.1.0 (prototype)"
    with_exit = None
    try:
        main(["--version"])
    except SystemExit as exc:  # argparse's version action exits 0
        with_exit = exc.code
    assert with_exit == 0
    assert capsys.readouterr().out.strip() == "nbdf-fleet 0.1.0 (prototype)"
    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv",
                          load_config(None), AS_OF)
    doc = json.loads(render_json(result))
    assert doc["metadata"]["tool_version"] == nbdf_fleet.__version__
    assert doc["metadata"]["schema_version"] == nbdf_fleet.SCHEMA_VERSION == "2"
    assert f"tool v{nbdf_fleet.__version__}" in render_html(result)


# ---------------------------------------------------------------------------
# 1.6 resource loading
# ---------------------------------------------------------------------------


def test_bundled_resources_are_loaded_via_importlib_resources():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "__file__" in text:
            offenders.append(path.name)
    assert offenders == []
    assert "resources.files(" in (SRC / "config.py").read_text(encoding="utf-8")
    assert "resources.as_file(" in (SRC / "cli.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1.4 CSV sanitization scope
# ---------------------------------------------------------------------------


def test_csv_cell_neutralizes_text_but_not_numbers():
    assert _cell("=SUM(A1)") == "'=SUM(A1)"
    assert _cell("-text") == "'-text"
    assert _cell(-5.0) == -5.0
    assert _cell(-5) == -5
    assert _cell(0) == 0
    assert _cell(None) == ""


def test_csv_export_keeps_negative_numeric_column_unchanged():
    """A negative number in a numeric column is written as-is; text is neutralized.

    Ingestion rejects negative readings, so the vehicle is built directly to
    exercise the export layer's scope on its own.
    """
    vehicle = Vehicle(vehicle_id="=EVIL", row=2, asset_class="light-duty",
                      current_odometer=Decimal("-5.0"), current_engine_hours=Decimal("-5.5"))
    assessment = VehicleAssessment(
        vehicle=vehicle, status=Status.INSUFFICIENT_DATA, governing_task=None,
        governing_meter=None, governing_utilization=None, tasks=(), unmapped_service_types=(),
        service_record_count=0, corrective_in_window=None, repeat_window_months=12,
        data_gaps=("no rules",), notes=(),
    )
    score = ScoreResult(score=Fraction(25), band="MEDIUM", method_id="rules", components=())
    metadata = AnalysisMetadata("0.1.0", "2", "abc", "rules.toml", AS_OF, "rules", "v.csv", "s.csv")
    result = AnalysisResult(metadata=metadata, findings=(), results=(VehicleResult(assessment, score, 1),))
    rows = list(csv.DictReader(io.StringIO(render_csv(result), newline="")))
    assert rows[0]["vehicle_id"] == "'=EVIL"
    # Numeric columns are never prefixed. An integral Decimal is written as an
    # int ("-5"), a non-integral one as-is ("-5.5"); both parse back exactly.
    assert rows[0]["current_odometer"] == "-5" and float(rows[0]["current_odometer"]) == -5.0
    assert rows[0]["current_engine_hours"] == "-5.5"


# ---------------------------------------------------------------------------
# 1.3 excluded future-dated records in every format
# ---------------------------------------------------------------------------


def _fleet_with_future_record(tmp_path):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,,,,light-duty,,,10000,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        "V1,2026-04-01,Oil change,9000,,10,,",
        "V1,2026-08-15,Oil change,9900,,10,,",  # after as-of
        "V1,2027-01-01,Brake inspection,9950,,10,,",  # after as-of
    ])
    return v, s


def test_excluded_future_records_are_counted_in_every_format(tmp_path, small_config):
    v, s = _fleet_with_future_record(tmp_path)
    result = run_analysis(v, s, small_config, AS_OF)
    assert result.results[0].assessment.service_record_count == 1
    text = render_text(result)
    assert "Excluded (future-dated):  2" in text
    assert "Service records analyzed: 1" in text
    doc = json.loads(render_json(result))
    assert doc["summary"]["service_records_excluded_future_dated"] == 2
    assert doc["summary"]["service_records_analyzed"] == 1
    html = render_html(result)
    assert 'Service records excluded (future-dated)</th><td class="num">2' in html
    # CSV has no summary section by design; the per-vehicle row shows the
    # analyzed count and findings.csv carries the two warnings.
    rows = list(csv.DictReader(io.StringIO(render_csv(result), newline="")))
    assert rows[0]["service_record_count"] == "1"


def test_no_future_records_reports_zero(examples, config):
    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    assert json.loads(render_json(result))["summary"]["service_records_excluded_future_dated"] == 0


# ---------------------------------------------------------------------------
# Demo polish: corrective repairs do not warn as unmapped
# ---------------------------------------------------------------------------


def test_corrective_records_do_not_warn_as_unmapped_but_are_listed(tmp_path, small_config):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,,,,light-duty,,,10000,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        "V1,2026-04-01,Oil change,9000,,10,preventive,",
        "V1,2026-05-01,Starter replacement,9500,,300,corrective,",
        "V1,2026-05-02,Wiper blades,9510,,30,preventive,",
        "V1,2026-05-03,Bulb,9520,,5,,",
    ])
    result = run_analysis(v, s, small_config, AS_OF)
    unmapped_warnings = sorted(f.message.split("'")[1] for f in result.warnings if f.code == "unmapped_service_type")
    assert unmapped_warnings == ["Bulb", "Wiper blades"]
    assert result.results[0].assessment.unmapped_service_types == ("Bulb", "Starter replacement", "Wiper blades")


def test_demo_warnings_are_the_two_intentional_ones(examples, config):
    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    assert sorted(f.code for f in result.warnings) == ["unknown_asset_class", "unmapped_service_type"]
    assert re.search(r"'Track tension check'", result.warnings[1].message) or re.search(
        r"'Track tension check'", result.warnings[0].message)
