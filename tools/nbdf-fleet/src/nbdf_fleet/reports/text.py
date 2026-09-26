# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Plain-text, ASCII-only terminal reports."""

from __future__ import annotations

import textwrap

from .. import HEURISTIC_DISCLAIMER, PLACEHOLDER_BANNER
from ..models import AnalysisResult, Finding, VehicleResult
from .common import (
    BAND_ORDER,
    STATUS_ORDER,
    criterion_elapsed_unit,
    criterion_interval_text,
    governing_threshold_text,
    number,
    score_value,
    summary_dict,
    utilization_value,
    warning_counts,
)

WIDTH = 100


def _rule(char: str = "-") -> str:
    return char * WIDTH


def _wrap(text: str, indent: str = "") -> str:
    return textwrap.fill(text, width=WIDTH, initial_indent=indent, subsequent_indent=indent)


def _header(result: AnalysisResult, title: str) -> list[str]:
    m = result.metadata
    lines = [
        _rule("="),
        f"NBDF Fleet Maintenance CLI v{m.tool_version} - {title}",
        _rule("="),
        f"As-of date:      {m.as_of.isoformat()}",
        f"Inputs:          {m.vehicle_file}, {m.service_file}",
        f"Config:          {m.config_source} (hash {m.config_hash})",
        f"Scoring method:  {m.scoring_method} (deterministic planning heuristic)",
        f"Schema version:  {m.schema_version}",
        "",
        _wrap("DISCLAIMER: " + HEURISTIC_DISCLAIMER),
        "",
    ]
    if m.placeholder_config:
        lines.extend([_rule("!"), _wrap(PLACEHOLDER_BANNER), _rule("!"), ""])
    return lines


def _table(headers: list[str], rows: list[list[str]], right: set[int] = frozenset()) -> list[str]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def fmt(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            parts.append(cell.rjust(widths[i]) if i in right else cell.ljust(widths[i]))
        return "  ".join(parts).rstrip()
    lines = [fmt(headers), "  ".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in rows)
    return lines


def render_findings(findings: tuple[Finding, ...] | list[Finding], heading: str = "Validation findings") -> str:
    lines = [heading, _rule()]
    if not findings:
        lines.append("none")
        return "\n".join(lines) + "\n"
    for f in findings:
        where = f.file
        if f.row is not None:
            where += f" row {f.row}"
        if f.field:
            where += f" [{f.field}]"
        vehicle = f" vehicle {f.vehicle_id}" if f.vehicle_id else ""
        lines.append(f"{f.severity.value:<7} {f.code}  {where}{vehicle}")
        lines.append(_wrap(f.message, "        "))
        lines.append(_wrap("fix: " + f.fix, "        "))
    return "\n".join(lines) + "\n"


def render_validation(result: AnalysisResult) -> str:
    lines = _header(result, "validation")
    errors, warnings = result.errors, result.warnings
    lines.append(f"Errors:   {len(errors)}")
    lines.append(f"Warnings: {len(warnings)}")
    lines.append("")
    if errors:
        lines.append(render_findings(errors, "Errors (analysis is blocked until these are fixed)").rstrip("\n"))
        lines.append("")
    lines.append(render_findings(warnings, "Warnings (analysis proceeds; shown in results)").rstrip("\n"))
    return "\n".join(lines) + "\n"


def render_text(result: AnalysisResult) -> str:
    lines = _header(result, "fleet analysis")
    if result.blocked:
        lines.append(render_findings(result.errors, "Errors (analysis is blocked until these are fixed)").rstrip("\n"))
        lines.append("")
        lines.append(f"Warnings: {len(result.warnings)} (run 'validate' to list them)")
        return "\n".join(lines) + "\n"

    summary = summary_dict(result)
    lines.append("FLEET SUMMARY")
    lines.append(_rule())
    lines.append(f"Vehicles analyzed:        {summary['vehicles']}")
    for status in STATUS_ORDER:
        lines.append(f"  {status.label:<22}  {summary['by_status'][status.value]}")
    lines.append("Priority bands:")
    for band in BAND_ORDER:
        lines.append(f"  {band:<22}  {summary['by_priority_band'][band]}")
    lines.append(f"Vehicles with data gaps:  {summary['vehicles_with_data_gaps']}")
    lines.append(f"Service records analyzed: {summary['service_records_analyzed']}")
    lines.append(f"Excluded (future-dated):  {summary['service_records_excluded_future_dated']}")
    lines.append(f"Validation warnings:      {summary['warnings']}")
    lines.append("")

    lines.append("VEHICLES (ranked by score, then vehicle ID)")
    lines.append(_rule())
    per_vehicle_warnings = warning_counts(result)
    rows = []
    for item in result.results:
        a = item.assessment
        rows.append([
            str(item.rank),
            a.vehicle.vehicle_id,
            a.vehicle.department or "-",
            a.vehicle.asset_class,
            a.status.label,
            f"{score_value(item.score.score):.1f}",
            item.score.band,
            str(len(a.data_gaps)),
            str(per_vehicle_warnings.get(a.vehicle.vehicle_id, 0)),
            governing_threshold_text(item),
        ])
    lines.extend(_table(
        ["#", "VEHICLE", "DEPARTMENT", "CLASS", "STATUS", "SCORE", "BAND", "GAPS", "WARN", "GOVERNING TASK / THRESHOLD"],
        rows, right={0, 5, 7, 8},
    ))
    lines.append("")

    unmapped = sorted({t for r in result.results for t in r.assessment.unmapped_service_types}, key=str.lower)
    if unmapped:
        lines.append("Unmapped service types (excluded from rule evaluation):")
        for name in unmapped:
            lines.append(f"  - {name}")
        lines.append("")

    if result.warnings:
        lines.append(render_findings(result.warnings, f"Validation warnings ({len(result.warnings)})").rstrip("\n"))
        lines.append("")
    lines.append("For the classification and score breakdown of one vehicle, run:")
    lines.append(
        f"  nbdf-fleet explain <vehicle-file> <service-file> <vehicle-id> "
        f"--as-of {result.metadata.as_of.isoformat()}"
    )
    return "\n".join(lines) + "\n"


def render_explanation(result: AnalysisResult, item: VehicleResult) -> str:
    a = item.assessment
    v = a.vehicle
    lines = _header(result, f"explanation for {v.vehicle_id}")
    lines.append("VEHICLE")
    lines.append(_rule())
    desc = " ".join(str(x) for x in (v.year, v.make, v.model) if x is not None) or "(no description)"
    lines.append(f"{v.vehicle_id}  {desc}")
    lines.append(f"Asset class: {v.asset_class}   Department: {v.department or '-'}")
    lines.append(
        f"In service: {v.in_service_date.isoformat() if v.in_service_date else 'MISSING'}   "
        f"Current odometer: {_num(v.current_odometer)} mi   "
        f"Current engine hours: {_num(v.current_engine_hours)} h"
    )
    lines.append(f"Service records: {a.service_record_count}")
    lines.append("")

    lines.append("CLASSIFICATION")
    lines.append(_rule())
    lines.append(f"Vehicle status: {a.status.label}")
    if a.governing_task:
        lines.append(_wrap(f"Governing: {governing_threshold_text(item)}", ""))
    for note in a.notes:
        lines.append(_wrap("Note: " + note))
    lines.append("")
    for t in a.tasks:
        head = f"  {t.task_name}: {t.status.label}"
        if t.last_service_date:
            head += f"  (last service {t.last_service_date.isoformat()}"
            head += ", ASSUMED BASELINE)" if t.assumed_baseline else f", row {t.last_service_row})"
        lines.append(head)
        for c in t.criteria:
            marker = "*" if t.governing_criterion is c else " "
            if c.utilization is None:
                lines.append(f"    {marker} {c.meter.value:<6} INSUFFICIENT DATA - {c.note}")
            else:
                util = utilization_value(c.utilization)
                lines.append(
                    f"    {marker} {c.meter.value:<6} {c.status.label:<17} "
                    f"elapsed {_num(c.elapsed)} {criterion_elapsed_unit(c)} of "
                    f"{criterion_interval_text(c)}; utilization {util:.4f}"
                )
        for note in t.notes:
            lines.append(_wrap(note, "      "))
    lines.append("  (* = governing criterion within the task)")
    lines.append("")

    if a.unmapped_service_types:
        lines.append("Unmapped service types for this vehicle (not evaluated): " + "; ".join(a.unmapped_service_types))
        lines.append("")
    if a.data_gaps:
        lines.append("DATA GAPS (missing data is never treated as low risk)")
        lines.append(_rule())
        for gap in a.data_gaps:
            lines.append("  - " + gap)
        lines.append("")

    lines.append("SCORE")
    lines.append(_rule())
    rows = []
    for c in item.score.components:
        rows.append([
            c.name,
            f"{float(c.weight):.2f}",
            f"{float(round(c.value, 4)):.4f}",
            f"{float(round(c.contribution, 2)):.2f}",
        ])
    lines.extend(_table(["COMPONENT", "WEIGHT", "VALUE", "POINTS"], rows, right={1, 2, 3}))
    lines.append(f"{'TOTAL':<22}  {'':>6}  {'':>6}  {score_value(item.score.score):>6.1f}   band {item.score.band}")
    lines.append("")
    for c in item.score.components:
        lines.append(f"{c.name}:")
        lines.append(_wrap(c.explanation, "    "))
        for k, val in c.inputs:
            lines.append(f"      {k}: {val}")
    lines.append("")
    lines.append(_wrap(
        "The score orders vehicles for human review. It is not a failure probability and has not "
        "been validated against outcomes."
    ))
    return "\n".join(lines) + "\n"


def _num(value) -> str:
    n = number(value)
    return "MISSING" if n is None else str(n)
