# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Maintenance rules: match service history to tasks and classify status.

Classification per criterion (miles, hours, months):

    utilization = elapsed / interval

    utilization <  due_soon_utilization        -> CURRENT
    due_soon_utilization <= utilization < 1    -> DUE_SOON
    utilization >= 1                           -> OVERDUE

Exact boundaries: a value exactly at ``due_soon_utilization`` is DUE_SOON; a
value exactly at 1.0 is OVERDUE. Utilization is computed with
:class:`fractions.Fraction` so these comparisons are exact.

For the months criterion the interval is converted to a calendar due date
(last service date + N months, day clamped to month end) and utilization is
``elapsed_days / days_in_interval``. The as-of date equal to the due date is
therefore exactly 1.0 -> OVERDUE.

Missing data never counts as CURRENT. A criterion that cannot be evaluated is
INSUFFICIENT_DATA, which outranks CURRENT but is outranked by DUE_SOON and
OVERDUE (evidence of a due condition takes precedence over a data gap, but
the gap is still listed).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

from .config import RulesConfig, Schedule, TaskConfig
from .dates import add_months
from .ingest import normalize_text
from .models import (
    CriterionResult,
    Meter,
    ServiceRecord,
    Status,
    TaskResult,
    Vehicle,
    VehicleAssessment,
)

METER_ORDER = {Meter.MILES: 0, Meter.HOURS: 1, Meter.MONTHS: 2}


def classify(utilization: Fraction, due_soon_threshold: Fraction) -> Status:
    if utilization >= 1:
        return Status.OVERDUE
    if utilization >= due_soon_threshold:
        return Status.DUE_SOON
    return Status.CURRENT


def build_alias_index(config: RulesConfig) -> dict[str, TaskConfig]:
    index: dict[str, TaskConfig] = {}
    for task in config.tasks:
        for alias in task.aliases:
            index[alias] = task
    return index


def assess_vehicle(
    vehicle: Vehicle,
    services: list[ServiceRecord],
    config: RulesConfig,
    as_of: date,
    alias_index: dict[str, TaskConfig] | None = None,
) -> VehicleAssessment:
    """Evaluate every configured task for one vehicle."""
    index = alias_index if alias_index is not None else build_alias_index(config)
    history = sorted(
        (s for s in services if s.vehicle_id == vehicle.vehicle_id),
        key=lambda s: (s.service_date, s.row),
    )

    unmapped: dict[str, str] = {}
    by_task: dict[str, list[ServiceRecord]] = {}
    for record in history:
        task = index.get(normalize_text(record.service_type))
        if task is None:
            unmapped.setdefault(normalize_text(record.service_type), record.service_type)
        else:
            by_task.setdefault(task.name, []).append(record)

    notes: list[str] = []
    gaps: list[str] = []
    applicable = config.tasks_for(vehicle.asset_class)
    task_results: list[TaskResult] = []
    if not applicable:
        if config.asset_class(vehicle.asset_class) is None:
            notes.append(f"asset class '{vehicle.asset_class}' is not defined in the configuration")
        else:
            notes.append(f"no maintenance tasks are configured for asset class '{vehicle.asset_class}'")
        gaps.append("no applicable maintenance rules; nothing could be evaluated")
    for task, schedule in applicable:
        result = _assess_task(vehicle, task, schedule, by_task.get(task.name, []), config, as_of)
        task_results.append(result)
        for criterion in result.criteria:
            if criterion.status is Status.INSUFFICIENT_DATA:
                gaps.append(f"{task.name} / {criterion.meter.value}: {criterion.note}")

    status = Status.INSUFFICIENT_DATA
    governing: TaskResult | None = None
    if task_results:
        status = max((t.status for t in task_results), key=lambda s: s.rank)
        candidates = [t for t in task_results if t.status is status]
        governing = max(
            candidates,
            key=lambda t: (
                _utilization_key(t),
                -task_results.index(t),  # earlier config order wins ties
            ),
        )

    # Repeated corrective maintenance in the lookback window (only when the
    # history carries category information for this vehicle).
    corrective: int | None = None
    if any(r.category is not None for r in history):
        window_start = add_months(as_of, -config.scoring.repeat_lookback_months)
        corrective = sum(
            1
            for r in history
            if r.category == "corrective" and window_start <= r.service_date <= as_of
        )

    return VehicleAssessment(
        vehicle=vehicle,
        status=status,
        governing_task=governing.task_name if governing else None,
        governing_meter=(
            governing.governing_criterion.meter
            if governing and governing.governing_criterion
            else None
        ),
        governing_utilization=(
            governing.governing_criterion.utilization
            if governing and governing.governing_criterion
            else None
        ),
        tasks=tuple(task_results),
        unmapped_service_types=tuple(sorted(unmapped.values(), key=str.lower)),
        service_record_count=len(history),
        corrective_in_window=corrective,
        repeat_window_months=config.scoring.repeat_lookback_months,
        data_gaps=tuple(gaps),
        notes=tuple(notes),
    )


def _utilization_key(task: TaskResult) -> Fraction:
    if task.governing_criterion is None or task.governing_criterion.utilization is None:
        return Fraction(-1)
    return task.governing_criterion.utilization


def _assess_task(
    vehicle: Vehicle,
    task: TaskConfig,
    schedule: Schedule,
    records: list[ServiceRecord],
    config: RulesConfig,
    as_of: date,
) -> TaskResult:
    notes: list[str] = []
    assumed = False
    last: ServiceRecord | None = None
    if records:
        # Latest by date; ties broken by highest odometer, then later row.
        last = max(
            records,
            key=lambda r: (r.service_date, r.odometer if r.odometer is not None else Decimal(-1), r.row),
        )
        last_date: date | None = last.service_date
        last_odometer = last.odometer
        last_hours = last.engine_hours
    elif config.baseline.assume_in_service_baseline and vehicle.in_service_date is not None:
        assumed = True
        last_date = vehicle.in_service_date
        last_odometer = Decimal(0)
        last_hours = Decimal(0)
        notes.append(
            "ASSUMED BASELINE: no service record for this task; the in-service date "
            f"{last_date.isoformat()} with zero miles and zero hours is used as the last "
            "service because baseline.assume_in_service_baseline is enabled"
        )
    else:
        reason = "no service record matches this task"
        if config.baseline.assume_in_service_baseline:
            reason += " and the vehicle has no in-service date for a baseline"
        criteria = tuple(
            CriterionResult(
                meter=meter, status=Status.INSUFFICIENT_DATA, interval=interval, elapsed=None,
                interval_basis=None, utilization=None, last_value=None,
                current_value=_current_display(vehicle, meter, as_of), note=reason,
            )
            for meter, interval in schedule.intervals()
        )
        return TaskResult(
            task_name=task.name, status=Status.INSUFFICIENT_DATA, last_service_date=None,
            last_service_row=None, assumed_baseline=False, criteria=criteria,
            governing_criterion=criteria[0] if criteria else None, notes=(reason,),
        )

    criteria: list[CriterionResult] = []
    for meter, interval in schedule.intervals():
        if meter is Meter.MILES:
            criteria.append(
                _reading_criterion(meter, interval, last_odometer, vehicle.current_odometer,
                                   "odometer", config)
            )
        elif meter is Meter.HOURS:
            criteria.append(
                _reading_criterion(meter, interval, last_hours, vehicle.current_engine_hours,
                                   "engine hours", config)
            )
        else:
            criteria.append(_months_criterion(interval, last_date, as_of, config))

    status = max((c.status for c in criteria), key=lambda s: s.rank)
    candidates = [c for c in criteria if c.status is status]
    governing = max(
        candidates,
        key=lambda c: (
            c.utilization if c.utilization is not None else Fraction(-1),
            -METER_ORDER[c.meter],
        ),
    )
    return TaskResult(
        task_name=task.name,
        status=status,
        last_service_date=last_date,
        last_service_row=last.row if last else None,
        assumed_baseline=assumed,
        criteria=tuple(criteria),
        governing_criterion=governing,
        notes=tuple(notes),
    )


def _reading_criterion(
    meter: Meter,
    interval: Decimal,
    last_value: Decimal | None,
    current_value: Decimal | None,
    label: str,
    config: RulesConfig,
) -> CriterionResult:
    last_display = _fmt(last_value)
    current_display = _fmt(current_value)
    if last_value is None:
        return CriterionResult(
            meter, Status.INSUFFICIENT_DATA, interval, None, None, None, last_display,
            current_display, f"{label} not recorded at the last service",
        )
    if current_value is None:
        return CriterionResult(
            meter, Status.INSUFFICIENT_DATA, interval, None, None, None, last_display,
            current_display, f"current {label} is missing from the inventory",
        )
    if current_value < last_value:
        return CriterionResult(
            meter, Status.INSUFFICIENT_DATA, interval, None, None, None, last_display,
            current_display, f"current {label} is below the reading at the last service",
        )
    elapsed = current_value - last_value
    utilization = Fraction(elapsed) / Fraction(interval)
    return CriterionResult(
        meter, classify(utilization, config.thresholds.due_soon_utilization), interval, elapsed,
        interval, utilization, last_display, current_display, None,
    )


def _months_criterion(
    interval: Decimal, last_date: date | None, as_of: date, config: RulesConfig
) -> CriterionResult:
    if last_date is None:  # pragma: no cover - callers always supply a date here
        return CriterionResult(
            Meter.MONTHS, Status.INSUFFICIENT_DATA, interval, None, None, None, None,
            as_of.isoformat(), "last service date unknown",
        )
    months = int(interval)
    due = add_months(last_date, months)
    basis = Decimal((due - last_date).days)
    elapsed_days = (as_of - last_date).days
    if elapsed_days < 0:
        return CriterionResult(
            Meter.MONTHS, Status.INSUFFICIENT_DATA, interval, None, basis, None,
            last_date.isoformat(), as_of.isoformat(),
            "last service date is after the as-of date",
        )
    utilization = Fraction(elapsed_days) / Fraction(basis)
    return CriterionResult(
        Meter.MONTHS, classify(utilization, config.thresholds.due_soon_utilization), interval,
        Decimal(elapsed_days), basis, utilization, last_date.isoformat(), as_of.isoformat(), None,
    )


def _current_display(vehicle: Vehicle, meter: Meter, as_of: date) -> str | None:
    if meter is Meter.MILES:
        return _fmt(vehicle.current_odometer)
    if meter is Meter.HOURS:
        return _fmt(vehicle.current_engine_hours)
    return as_of.isoformat()


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
