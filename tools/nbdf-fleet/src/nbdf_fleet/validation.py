# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Cross-record validation.

Row-level parsing problems are produced by :mod:`nbdf_fleet.ingest`. This
module checks relationships between records and against the as-of date.

Severity policy (see docs/validation.md for the rationale):

ERROR - the record's identity or a governing quantity is unusable, so any
analysis built on it would be misleading. Analysis is blocked.
  * duplicate vehicle IDs
  * exact duplicate service records
  * service records that reference an unknown vehicle

WARNING - the data is inconsistent or incomplete but the tool can still
proceed while showing the inconsistency in the results.
  * future-dated service records (excluded from the analysis)
  * future in-service dates
  * service dated before the vehicle's in-service date
  * decreasing odometer or engine hours over time
  * current reading lower than the latest service reading
  * implausible jumps between readings
  * implausible model years
  * asset classes with no configured rules
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from .config import RulesConfig
from .dates import add_months
from .ingest import normalize_text
from .models import Finding, ServiceRecord, Severity, Vehicle


def validate(
    vehicles: list[Vehicle],
    services: list[ServiceRecord],
    config: RulesConfig,
    as_of: date,
    vehicle_file: str,
    service_file: str,
) -> tuple[list[Finding], list[Vehicle], list[ServiceRecord]]:
    """Return findings plus the vehicles and services usable for analysis.

    Vehicles with duplicate IDs are all kept in the returned list only when
    there are no errors (in which case analysis proceeds); callers must not
    analyze when any ERROR finding is present.
    """
    findings: list[Finding] = []

    # -- vehicles -----------------------------------------------------------
    seen: dict[str, int] = {}
    for vehicle in vehicles:
        first_row = seen.get(vehicle.vehicle_id)
        if first_row is not None:
            findings.append(
                Finding(
                    Severity.ERROR, "duplicate_vehicle_id", vehicle_file, vehicle.row, "vehicle_id",
                    f"vehicle_id '{vehicle.vehicle_id}' also appears on row {first_row}",
                    "give each vehicle a unique identifier or remove the duplicate row",
                    vehicle.vehicle_id,
                )
            )
        else:
            seen[vehicle.vehicle_id] = vehicle.row

        if vehicle.year is not None:
            low = config.validation.min_model_year
            high = as_of.year + config.validation.max_model_years_ahead
            if vehicle.year < low or vehicle.year > high:
                findings.append(
                    Finding(
                        Severity.WARNING, "implausible_year", vehicle_file, vehicle.row, "year",
                        f"model year {vehicle.year} is outside the plausible range {low}-{high}",
                        "check the model year", vehicle.vehicle_id,
                    )
                )
        if vehicle.in_service_date is not None and vehicle.in_service_date > as_of:
            findings.append(
                Finding(
                    Severity.WARNING, "future_in_service_date", vehicle_file, vehicle.row,
                    "in_service_date",
                    f"in-service date {vehicle.in_service_date.isoformat()} is after the as-of "
                    f"date {as_of.isoformat()}",
                    "check the date, or run with a later --as-of", vehicle.vehicle_id,
                )
            )
        if config.asset_class(vehicle.asset_class) is None:
            known = ", ".join(c.name for c in config.asset_classes)
            findings.append(
                Finding(
                    Severity.WARNING, "unknown_asset_class", vehicle_file, vehicle.row, "asset_class",
                    f"asset class '{vehicle.asset_class}' has no rules in the configuration; "
                    "the vehicle will be reported as INSUFFICIENT DATA",
                    f"use one of: {known}; or add the class to the config", vehicle.vehicle_id,
                )
            )

    # -- services -----------------------------------------------------------
    vehicle_by_id = {v.vehicle_id: v for v in vehicles}
    usable: list[ServiceRecord] = []
    seen_service: dict[tuple, int] = {}
    for record in services:
        if record.vehicle_id not in vehicle_by_id:
            findings.append(
                Finding(
                    Severity.ERROR, "unknown_vehicle", service_file, record.row, "vehicle_id",
                    f"vehicle_id '{record.vehicle_id}' does not exist in {vehicle_file}",
                    "correct the vehicle_id or add the vehicle to the inventory",
                    record.vehicle_id,
                )
            )
            continue
        key = (
            record.vehicle_id,
            record.service_date,
            normalize_text(record.service_type),
            record.odometer,
            record.engine_hours,
            record.cost,
        )
        first_row = seen_service.get(key)
        if first_row is not None:
            findings.append(
                Finding(
                    Severity.ERROR, "duplicate_service_record", service_file, record.row, None,
                    f"exact duplicate of the service record on row {first_row} "
                    f"(same vehicle, date, type, readings, and cost; notes are not compared)",
                    "remove the duplicate row; if both services really happened, correct the "
                    "date, readings, or cost on the one that was entered wrong", record.vehicle_id,
                )
            )
            continue
        seen_service[key] = record.row

        if record.service_date > as_of:
            findings.append(
                Finding(
                    Severity.WARNING, "future_service_date", service_file, record.row, "service_date",
                    f"service date {record.service_date.isoformat()} is after the as-of date "
                    f"{as_of.isoformat()}; the record is excluded from this analysis",
                    "check the date, or run with a later --as-of", record.vehicle_id,
                )
            )
            continue
        vehicle = vehicle_by_id[record.vehicle_id]
        months = _max_interval_months(config, vehicle.asset_class)
        if months and not _due_date_fits(record.service_date, months):
            findings.append(
                Finding(
                    Severity.ERROR, "date_out_of_range", service_file, record.row, "service_date",
                    f"service date {record.service_date.isoformat()} plus the configured "
                    f"{months}-month interval falls after {date.max.isoformat()}, the last "
                    "date the tool can represent",
                    "check the service date; a year this far ahead is almost always a typo",
                    record.vehicle_id,
                )
            )
            continue
        if vehicle.in_service_date is not None and record.service_date < vehicle.in_service_date:
            findings.append(
                Finding(
                    Severity.WARNING, "service_before_in_service", service_file, record.row,
                    "service_date",
                    f"service date {record.service_date.isoformat()} is before the vehicle's "
                    f"in-service date {vehicle.in_service_date.isoformat()}",
                    "check both dates", record.vehicle_id,
                )
            )
        usable.append(record)

    # -- unmapped service types (one warning per distinct type) --------------
    # Records categorized "corrective" are unscheduled repairs by definition,
    # so not matching a scheduled task is expected and does not warn. They
    # are still listed as unmapped in the results.
    known_aliases = {alias for task in config.tasks for alias in task.aliases}
    reported: set[str] = set()
    for record in usable:
        key = normalize_text(record.service_type)
        if key in known_aliases or key in reported or record.category == "corrective":
            continue
        reported.add(key)
        findings.append(
            Finding(
                Severity.WARNING, "unmapped_service_type", service_file, record.row, "service_type",
                f"service type '{record.service_type}' matches no configured task alias; "
                "such records are shown in results but excluded from rule evaluation",
                "add the spelling to a task's aliases in the config, or leave it if it is "
                "not a scheduled task", record.vehicle_id,
            )
        )

    # -- reading consistency per vehicle ------------------------------------
    by_vehicle: dict[str, list[ServiceRecord]] = {}
    for record in usable:
        by_vehicle.setdefault(record.vehicle_id, []).append(record)
    for vehicle_id, records in by_vehicle.items():
        vehicle = vehicle_by_id[vehicle_id]
        ordered = sorted(records, key=lambda r: (r.service_date, r.row))
        _check_sequence(ordered, vehicle, config, as_of, service_file, vehicle_file, findings)

    # -- in-service dates used as an assumed baseline ------------------------
    if config.baseline.assume_in_service_baseline:
        for vehicle in vehicles:
            months = _max_interval_months(config, vehicle.asset_class)
            if vehicle.in_service_date is not None and months \
                    and not _due_date_fits(vehicle.in_service_date, months):
                findings.append(
                    Finding(
                        Severity.ERROR, "date_out_of_range", vehicle_file, vehicle.row,
                        "in_service_date",
                        f"in-service date {vehicle.in_service_date.isoformat()} plus the configured "
                        f"{months}-month interval falls after {date.max.isoformat()}",
                        "check the in-service date", vehicle.vehicle_id,
                    )
                )

    findings.sort(key=Finding.sort_key)
    return findings, vehicles, usable


def _max_interval_months(config: RulesConfig, asset_class: str) -> int:
    months = [
        schedule.interval_months
        for _, schedule in config.tasks_for(asset_class)
        if schedule.interval_months is not None
    ]
    return max(months, default=0)


def _due_date_fits(start: date, months: int) -> bool:
    """True when ``start + months`` is a representable date.

    Uses the same month arithmetic as the rules engine, only as a probe, so
    the rules never meet a date they cannot compute.
    """
    try:
        add_months(start, months)
    except (ValueError, OverflowError):
        return False
    return True


def _check_sequence(
    ordered: list[ServiceRecord],
    vehicle: Vehicle,
    config: RulesConfig,
    as_of: date,
    service_file: str,
    vehicle_file: str,
    findings: list[Finding],
) -> None:
    for meter, field, current_field, per_day in (
        ("odometer", "odometer", "current_odometer", config.validation.max_miles_per_day),
        ("engine hours", "engine_hours", "current_engine_hours", config.validation.max_engine_hours_per_day),
    ):
        previous: ServiceRecord | None = None
        for record in ordered:
            value = getattr(record, field)
            if value is None:
                continue
            if previous is not None:
                prev_value = getattr(previous, field)
                if value < prev_value:
                    findings.append(
                        Finding(
                            Severity.WARNING, f"decreasing_{field}", service_file, record.row, field,
                            f"{meter} {value} on {record.service_date.isoformat()} is lower than "
                            f"{prev_value} on {previous.service_date.isoformat()} (row {previous.row})",
                            "check which reading is wrong; readings should not decrease over time",
                            record.vehicle_id,
                        )
                    )
                else:
                    _check_jump(
                        value - prev_value, (record.service_date - previous.service_date).days,
                        per_day, meter, field, service_file, record, findings,
                        f"since row {previous.row} ({previous.service_date.isoformat()})",
                    )
            previous = record
        current = getattr(vehicle, current_field)
        if previous is not None and current is not None:
            last_value = getattr(previous, field)
            if current < last_value:
                findings.append(
                    Finding(
                        Severity.WARNING, f"current_below_last_service_{field}", vehicle_file,
                        vehicle.row, current_field,
                        f"current {meter} {current} is lower than {last_value} recorded at the "
                        f"latest service on {previous.service_date.isoformat()} "
                        f"({service_file} row {previous.row}); the {meter} criterion cannot be "
                        "evaluated",
                        "update the current reading or correct the service record",
                        vehicle.vehicle_id,
                    )
                )
            else:
                days = (as_of - previous.service_date).days
                jump = current - last_value
                limit = per_day * max(days, 1)
                if jump > limit:
                    findings.append(
                        Finding(
                            Severity.WARNING, f"implausible_{field}_jump", vehicle_file, vehicle.row,
                            current_field,
                            f"current {meter} {current} is {jump} above the latest service reading "
                            f"{last_value} on {previous.service_date.isoformat()} ({days} days ago); "
                            f"limit is {per_day} per day",
                            "check the current reading and the latest service reading",
                            vehicle.vehicle_id,
                        )
                    )


def _check_jump(
    jump: Decimal,
    days: int,
    per_day: Decimal,
    meter: str,
    field: str,
    service_file: str,
    record: ServiceRecord,
    findings: list[Finding],
    context: str,
) -> None:
    limit = per_day * max(days, 1)
    if jump > limit:
        findings.append(
            Finding(
                Severity.WARNING, f"implausible_{field}_jump", service_file, record.row, field,
                f"{meter} increased by {jump} over {days} day(s) {context}; limit is {per_day} per day",
                "check the readings on both rows", record.vehicle_id,
            )
        )
