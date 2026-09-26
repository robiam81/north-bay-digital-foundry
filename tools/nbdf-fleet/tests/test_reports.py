# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

import csv
import io
import json
from datetime import date

from nbdf_fleet.analysis import run_analysis
from nbdf_fleet.reports import render_csv, render_explanation, render_html, render_json, render_text
from nbdf_fleet.reports.common import VEHICLE_COLUMNS, neutralize
from nbdf_fleet.reports.csv_out import render_findings_csv
from tests.conftest import SERVICE_HEADER, VEHICLE_HEADER, write_csv

AS_OF = date(2026, 6, 30)


def _hostile_fleet(tmp_path):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, [
        '"=CMD()|calc",2020,"+Make","-Model",light-duty,"@Dept",2020-01-01,10000,',
        'V2,2020,"<b>Make</b>",Model,light-duty,"Dept & Co",2020-01-01,10000,',
    ])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        '"=CMD()|calc",2026-01-01,Oil change,5000,,10,,"=HYPERLINK(""x"")"',
        'V2,2026-01-01,"<script>alert(1)</script>",5000,,10,,"<img src=x onerror=alert(1)>"',
    ])
    return v, s


def test_neutralize_prefixes_formula_characters():
    assert neutralize("=SUM(A1)") == "'=SUM(A1)"
    assert neutralize("+1") == "'+1"
    assert neutralize("-1") == "'-1"
    assert neutralize("@cmd") == "'@cmd"
    assert neutralize("plain") == "plain"
    assert neutralize("") == ""
    assert neutralize(5) == 5


def test_csv_export_neutralizes_text_and_keeps_column_order(tmp_path, small_config):
    v, s = _hostile_fleet(tmp_path)
    result = run_analysis(v, s, small_config, AS_OF)
    text = render_csv(result)
    assert text.count("\r\n") == 3  # header + 2 rows, CRLF
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert list(rows[0].keys()) == list(VEHICLE_COLUMNS)
    hostile = next(r for r in rows if "CMD" in r["vehicle_id"])
    assert hostile["vehicle_id"] == "'=CMD()|calc"
    assert hostile["make"] == "'+Make"
    assert hostile["model"] == "'-Model"
    assert hostile["department"] == "'@Dept"
    assert hostile["score"].replace(".", "").isdigit()  # numbers untouched
    findings = render_findings_csv(result)
    finding_rows = list(csv.DictReader(io.StringIO(findings, newline="")))
    unmapped = next(r for r in finding_rows if r["code"] == "unmapped_service_type" and "script" in r["message"])
    assert unmapped["message"].startswith("service type")  # only formula characters are neutralized
    assert "\r\n" in findings


def test_json_export_is_stable_ascii_and_ordered(tmp_path, small_config):
    v, s = _hostile_fleet(tmp_path)
    result = run_analysis(v, s, small_config, AS_OF)
    text = render_json(result)
    assert text.isascii()
    doc = json.loads(text)
    assert list(doc.keys()) == ["metadata", "summary", "vehicles", "findings"]
    assert doc["metadata"]["as_of"] == "2026-06-30"
    assert doc["metadata"]["tool_version"] and doc["metadata"]["schema_version"]
    assert doc["metadata"]["config_hash"] == small_config.config_hash
    assert "heuristic" in doc["metadata"]["disclaimer"].lower()
    assert doc["vehicles"][0]["rank"] == 1
    assert doc["vehicles"][0]["score_components"][0]["name"] == "governing_utilization"
    # raw values are preserved in JSON (neutralization is a CSV concern)
    assert any(item["vehicle_id"] == "=CMD()|calc" for item in doc["vehicles"])
    assert render_json(result) == text


def test_html_escapes_all_user_text(tmp_path, small_config):
    v, s = _hostile_fleet(tmp_path)
    result = run_analysis(v, s, small_config, AS_OF)
    html = render_html(result)
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html
    assert "&lt;b&gt;Make&lt;/b&gt;" in html
    assert "Dept &amp; Co" in html
    assert "<script" not in html.lower()  # no JavaScript at all
    assert 'src="http' not in html and "<link" not in html  # self-contained
    assert "Planning heuristic only" in html
    assert "2026-06-30" in html


def test_text_report_and_explanation_are_ascii_and_mention_as_of(examples, config):
    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    report = render_text(result)
    assert report.isascii()
    assert "As-of date:      2026-06-30" in report
    assert "config" in report.lower() and config.config_hash in report
    assert "LD-103" in report and "OVERDUE" in report
    explanation = render_explanation(result, result.results[0])
    assert explanation.isascii()
    for name in ("governing_utilization", "overdue_magnitude", "additional_pressure",
                 "repeat_maintenance", "data_completeness"):
        assert name in explanation
    assert "utilization 1.5000" in explanation
    assert "not a failure probability" in explanation


def test_text_report_shows_data_gaps_and_unmapped_types(examples, config):
    result = run_analysis(examples / "demo_vehicles.csv", examples / "demo_service_history.csv", config, AS_OF)
    report = render_text(result)
    assert "Track tension check" in report
    assert "INSUFFICIENT DATA" in report
    explanation = render_explanation(result, next(r for r in result.results if r.assessment.vehicle.vehicle_id == "LD-104"))
    assert "DATA GAPS" in explanation
    assert "no service record matches this task" in explanation
