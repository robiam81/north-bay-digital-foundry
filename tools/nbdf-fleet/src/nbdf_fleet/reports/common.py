# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Shared serialization helpers used by every report format.

Everything here produces plain Python values (str, int, float, None, dict,
list) in an explicit, stable order so that JSON and CSV output is
byte-for-byte reproducible.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from fractions import Fraction

from .. import HEURISTIC_DISCLAIMER, PLACEHOLDER_BANNER
from ..config import BAND_HIGH, BAND_LOW, BAND_MEDIUM
from ..models import AnalysisResult, Finding, Status, VehicleResult

STATUS_ORDER: tuple[Status, ...] = (
    Status.OVERDUE,
    Status.DUE_SOON,
    Status.INSUFFICIENT_DATA,
    Status.CURRENT,
)
BAND_ORDER: tuple[str, ...] = (BAND_HIGH, BAND_MEDIUM, BAND_LOW)

VEHICLE_COLUMNS: tuple[str, ...] = (
    "rank",
    "vehicle_id",
    "department",
    "asset_class",
    "year",
    "make",
    "model",
    "status",
    "priority_band",
    "score",
    "governing_task",
    "governing_meter",
    "governing_utilization",
    "current_odometer",
    "current_engine_hours",
    "tasks_overdue",
    "tasks_due_soon",
    "tasks_insufficient_data",
    "tasks_current",
    "data_gap_count",
    "corrective_in_window",
    "unmapped_service_types",
    "service_record_count",
    "warning_count",
)

FINDING_COLUMNS: tuple[str, ...] = (
    "severity",
    "code",
    "file",
    "row",
    "field",
    "vehicle_id",
    "message",
    "suggested_fix",
)


def number(value: Decimal | None) -> int | float | None:
    """Decimal -> int when integral, else float. None stays None."""
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def score_value(score: Fraction) -> float:
    return float(round(score, 1))


def utilization_value(value: Fraction | None) -> float | None:
    if value is None:
        return None
    return float(round(value, 4))


def points(value: Fraction) -> float:
    return float(round(value, 2))


def metadata_dict(result: AnalysisResult) -> dict:
    m = result.metadata
    return {
        "tool": "nbdf-fleet",
        "tool_version": m.tool_version,
        "schema_version": m.schema_version,
        "as_of": m.as_of.isoformat(),
        "config_hash": m.config_hash,
        "config_source": m.config_source,
        "scoring_method": m.scoring_method,
        "vehicle_file": m.vehicle_file,
        "service_file": m.service_file,
        "placeholder_config": m.placeholder_config,
        "placeholder_banner": PLACEHOLDER_BANNER if m.placeholder_config else None,
        "disclaimer": HEURISTIC_DISCLAIMER,
    }


def excluded_future_records(result: AnalysisResult) -> int:
    return sum(1 for f in result.findings if f.code == "future_service_date")


def summary_dict(result: AnalysisResult) -> dict:
    status_counts = Counter(r.assessment.status for r in result.results)
    band_counts = Counter(r.score.band for r in result.results)
    return {
        "vehicles": len(result.results),
        "by_status": {s.value: status_counts.get(s, 0) for s in STATUS_ORDER},
        "by_priority_band": {b: band_counts.get(b, 0) for b in BAND_ORDER},
        "vehicles_with_data_gaps": sum(1 for r in result.results if r.assessment.data_gaps),
        "service_records_analyzed": sum(r.assessment.service_record_count for r in result.results),
        "service_records_excluded_future_dated": excluded_future_records(result),
        "errors": len(result.errors),
        "warnings": len(result.warnings),
    }


def criterion_interval_text(c) -> str:
    """The interval of a criterion in the units its elapsed value uses.

    Time-based criteria are evaluated in days (see docs/scoring-method.md), so
    the text is "365 days (12-month interval)"; miles/hours read "5000 miles".
    Every output format uses this one function so the units cannot drift.
    """
    if c.meter.value == "months":
        return f"{number(c.interval_basis)} days ({number(c.interval)}-month interval)"
    return f"{number(c.interval)} {c.meter.value}"


def criterion_elapsed_unit(c) -> str:
    return "days" if c.meter.value == "months" else c.meter.value


def warning_counts(result: AnalysisResult) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for finding in result.warnings:
        if finding.vehicle_id:
            counts[finding.vehicle_id] += 1
    return dict(counts)


def vehicle_row(item: VehicleResult, warnings_for_vehicle: int) -> dict:
    a = item.assessment
    v = a.vehicle
    task_counts = Counter(t.status for t in a.tasks)
    return {
        "rank": item.rank,
        "vehicle_id": v.vehicle_id,
        "department": v.department,
        "asset_class": v.asset_class,
        "year": v.year,
        "make": v.make,
        "model": v.model,
        "status": a.status.value,
        "priority_band": item.score.band,
        "score": score_value(item.score.score),
        "governing_task": a.governing_task,
        "governing_meter": a.governing_meter.value if a.governing_meter else None,
        "governing_utilization": utilization_value(a.governing_utilization),
        "current_odometer": number(v.current_odometer),
        "current_engine_hours": number(v.current_engine_hours),
        "tasks_overdue": task_counts.get(Status.OVERDUE, 0),
        "tasks_due_soon": task_counts.get(Status.DUE_SOON, 0),
        "tasks_insufficient_data": task_counts.get(Status.INSUFFICIENT_DATA, 0),
        "tasks_current": task_counts.get(Status.CURRENT, 0),
        "data_gap_count": len(a.data_gaps),
        "corrective_in_window": a.corrective_in_window,
        "unmapped_service_types": "; ".join(a.unmapped_service_types),
        "service_record_count": a.service_record_count,
        "warning_count": warnings_for_vehicle,
    }


def vehicle_detail(item: VehicleResult, warnings_for_vehicle: int) -> dict:
    a = item.assessment
    detail = vehicle_row(item, warnings_for_vehicle)
    detail["unmapped_service_types"] = list(a.unmapped_service_types)
    detail["in_service_date"] = a.vehicle.in_service_date.isoformat() if a.vehicle.in_service_date else None
    detail["repeat_window_months"] = a.repeat_window_months
    detail["data_gaps"] = list(a.data_gaps)
    detail["notes"] = list(a.notes)
    detail["tasks"] = [
        {
            "task": t.task_name,
            "status": t.status.value,
            "last_service_date": t.last_service_date.isoformat() if t.last_service_date else None,
            "last_service_row": t.last_service_row,
            "assumed_baseline": t.assumed_baseline,
            "governing_meter": t.governing_criterion.meter.value if t.governing_criterion else None,
            "notes": list(t.notes),
            "criteria": [
                {
                    "meter": c.meter.value,
                    "status": c.status.value,
                    "interval": number(c.interval),
                    "interval_basis": number(c.interval_basis),
                    "elapsed": number(c.elapsed),
                    "utilization": utilization_value(c.utilization),
                    "last_value": c.last_value,
                    "current_value": c.current_value,
                    "note": c.note,
                }
                for c in t.criteria
            ],
        }
        for t in a.tasks
    ]
    detail["score_components"] = [
        {
            "name": c.name,
            "weight": float(c.weight),
            "value": float(round(c.value, 4)),
            "points": points(c.contribution),
            "inputs": [{"name": k, "value": v} for k, v in c.inputs],
            "explanation": c.explanation,
        }
        for c in item.score.components
    ]
    return detail


def finding_dict(finding: Finding) -> dict:
    return {
        "severity": finding.severity.value,
        "code": finding.code,
        "file": finding.file,
        "row": finding.row,
        "field": finding.field,
        "vehicle_id": finding.vehicle_id,
        "message": finding.message,
        "suggested_fix": finding.fix,
    }


def neutralize(value: object) -> object:
    """Prefix spreadsheet-formula-leading text with an apostrophe.

    Applied to every text field written to CSV so that a value such as
    ``=HYPERLINK(...)`` or ``-1+1`` in a vehicle ID or note is displayed as
    text rather than executed when the file is opened in a spreadsheet.
    """
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return "'" + value
    return value


def governing_threshold_text(item: VehicleResult) -> str:
    """Human-readable 'which threshold triggered it' for tables."""
    a = item.assessment
    if a.governing_task is None:
        return a.notes[0] if a.notes else "no rules applied"
    task = next(t for t in a.tasks if t.task_name == a.governing_task)
    c = task.governing_criterion
    if c is None:
        return a.governing_task
    if c.utilization is None:
        return f"{a.governing_task}: {c.meter.value} - {c.note}"
    return (
        f"{a.governing_task}: {number(c.elapsed)} of {criterion_interval_text(c)} "
        f"({float(c.utilization) * 100:.0f}%)"
    )
