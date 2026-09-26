# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Placeholder-config banner in every format, and the `init` command."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import date

import pytest

from nbdf_fleet import PLACEHOLDER_BANNER
from nbdf_fleet.analysis import run_analysis
from nbdf_fleet.cli import (
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VALIDATION,
    INIT_CONFIG_NAME,
    INIT_DEFAULT_DIR,
    INIT_SERVICES_NAME,
    INIT_VEHICLES_NAME,
    main,
)
from nbdf_fleet.config import build_config, load_config
from nbdf_fleet.ingest import SERVICE_COLUMNS, VEHICLE_COLUMNS, read_table
from nbdf_fleet.reports import render_csv, render_html, render_json, render_text
from nbdf_fleet.reports.text import render_validation
from tests.conftest import PROJECT_DIR, minimal_config_dict

AS_OF = date(2026, 6, 30)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


def _run(examples, config):
    return run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)


def test_bundled_config_has_placeholder_flag():
    assert load_config(None).placeholder_intervals is True
    assert build_config(minimal_config_dict(), "t").placeholder_intervals is False  # absent -> false
    assert build_config(minimal_config_dict(meta={"placeholder_intervals": False}), "t").placeholder_intervals is False
    with pytest.raises(Exception, match="placeholder_intervals"):
        build_config(minimal_config_dict(meta={"placeholder_intervals": "yes"}), "t")


def test_banner_present_in_every_format_when_flag_true(examples):
    result = _run(examples, load_config(None))
    text = render_text(result)
    assert PLACEHOLDER_BANNER in " ".join(text.split())  # banner is word-wrapped in text
    assert text.index("PLACEHOLDER CONFIG") < text.index("FLEET SUMMARY")  # above the results
    assert "PLACEHOLDER CONFIG" in render_validation(result)
    doc = json.loads(render_json(result))
    assert doc["metadata"]["placeholder_config"] is True
    assert doc["metadata"]["placeholder_banner"] == PLACEHOLDER_BANNER
    html = render_html(result)
    assert 'class="banner"' in html and "Placeholder maintenance intervals in use" in html
    # CSV is a flat table: no banner row, by design (documented in configuration.md).
    assert "PLACEHOLDER" not in render_csv(result)


def test_banner_absent_when_flag_false_or_missing(examples, tmp_path):
    for meta in ({"placeholder_intervals": False}, None):
        data = tomllib.loads((PROJECT_DIR / "config" / "default_rules.toml").read_text(encoding="utf-8"))
        if meta is None:
            data.pop("meta")
        else:
            data["meta"] = meta
        config = build_config(data, "custom.toml")
        result = _run(examples, config)
        assert PLACEHOLDER_BANNER not in render_text(result)
        assert "PLACEHOLDER CONFIG" not in render_validation(result)
        doc = json.loads(render_json(result))
        assert doc["metadata"]["placeholder_config"] is False
        assert doc["metadata"]["placeholder_banner"] is None
        assert 'class="banner"' not in render_html(result)
        assert "PLACEHOLDER" not in render_csv(result)


def test_banner_does_not_change_scores(examples):
    with_flag = _run(examples, load_config(None))
    data = tomllib.loads((PROJECT_DIR / "config" / "default_rules.toml").read_text(encoding="utf-8"))
    data["meta"]["placeholder_intervals"] = False
    without = _run(examples, build_config(data, "x.toml"))
    assert [(r.assessment.vehicle.vehicle_id, r.score.score) for r in with_flag.results] == [
        (r.assessment.vehicle.vehicle_id, r.score.score) for r in without.results
    ]


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_config_and_templates(tmp_path, capsys):
    target = tmp_path / "ws"
    assert main(["init", str(target)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Next steps" in out and "placeholder_intervals = false" in out
    names = sorted(p.name for p in target.iterdir())
    assert names == sorted([INIT_CONFIG_NAME, INIT_VEHICLES_NAME, INIT_SERVICES_NAME])
    config = load_config(target / INIT_CONFIG_NAME)
    assert config.placeholder_intervals is True
    assert (target / INIT_CONFIG_NAME).read_bytes() == (PROJECT_DIR / "config" / "default_rules.toml").read_bytes()
    assert (target / INIT_VEHICLES_NAME).read_bytes() == (",".join(VEHICLE_COLUMNS) + "\r\n").encode()
    assert (target / INIT_SERVICES_NAME).read_bytes() == (",".join(SERVICE_COLUMNS) + "\r\n").encode()


def test_init_default_directory_is_a_subfolder(tmp_path):
    proc = subprocess.run([sys.executable, "-m", "nbdf_fleet", "init"], cwd=str(tmp_path),
                          capture_output=True, text=True, env=ENV)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / INIT_DEFAULT_DIR / INIT_CONFIG_NAME).exists()
    assert not (tmp_path / INIT_CONFIG_NAME).exists()


def test_init_refuses_to_overwrite_then_force(tmp_path, capsys):
    target = tmp_path / "ws"
    assert main(["init", str(target)]) == EXIT_OK
    (target / INIT_VEHICLES_NAME).write_text("vehicle_id\nV1\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["init", str(target)]) == EXIT_USAGE
    assert "--force" in capsys.readouterr().err
    assert (target / INIT_VEHICLES_NAME).read_text(encoding="utf-8") == "vehicle_id\nV1\n"  # untouched
    assert main(["init", str(target), "--force"]) == EXIT_OK
    assert (target / INIT_VEHICLES_NAME).read_bytes() == (",".join(VEHICLE_COLUMNS) + "\r\n").encode()


def test_template_headers_cannot_drift_from_the_parser(tmp_path):
    """The templates are produced from the parser's own column tuples, so the
    parser must accept them with every known column present."""
    target = tmp_path / "ws"
    assert main(["init", str(target)]) == EXIT_OK
    assert read_table(target / INIT_VEHICLES_NAME).columns == VEHICLE_COLUMNS
    assert read_table(target / INIT_SERVICES_NAME).columns == SERVICE_COLUMNS


def test_header_only_files_validate_with_warning_and_block_analyze(tmp_path, capsys):
    target = tmp_path / "ws"
    assert main(["init", str(target)]) == EXIT_OK
    capsys.readouterr()
    args = [str(target / INIT_VEHICLES_NAME), str(target / INIT_SERVICES_NAME),
            "--config", str(target / INIT_CONFIG_NAME), "--as-of", "2026-06-30"]
    assert main(["validate", *args]) == EXIT_OK
    out = capsys.readouterr().out
    assert "Errors:   0" in out
    assert out.count("no_data_rows") == 2
    assert "PLACEHOLDER CONFIG" in out
    assert main(["analyze", *args]) == EXIT_VALIDATION
    assert "nothing to analyze" in capsys.readouterr().out
    assert main(["report", *args, "--format", "json"]) == EXIT_VALIDATION
    capsys.readouterr()
    assert main(["explain", *args, "V1"]) == EXIT_VALIDATION


def test_header_only_service_file_with_vehicles_still_analyzes(tmp_path, capsys):
    target = tmp_path / "ws"
    assert main(["init", str(target)]) == EXIT_OK
    with open(target / INIT_VEHICLES_NAME, "a", encoding="utf-8", newline="") as fh:
        fh.write("V1,2020,Make,Model,light-duty,Dept,2020-01-01,1000,\r\n")
    capsys.readouterr()
    args = [str(target / INIT_VEHICLES_NAME), str(target / INIT_SERVICES_NAME),
            "--config", str(target / INIT_CONFIG_NAME), "--as-of", "2026-06-30"]
    assert main(["analyze", *args]) == EXIT_OK
    out = capsys.readouterr().out
    assert re.search(r"INSUFFICIENT DATA\s+1\n", out)
    assert out.count("no_data_rows") == 1
