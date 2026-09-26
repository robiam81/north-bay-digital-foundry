# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Domain models.

All models are frozen dataclasses. A missing value is always represented as
``None`` - never as zero, an empty string, or a sentinel number. ``Decimal``
is used for meter readings and costs so that exact-boundary comparisons are
exact and outputs are reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from fractions import Fraction


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    """One validation finding.

    ``row`` is the physical line number in the source file where line 1 is the
    header, so the first data row is row 2. This matches what a spreadsheet
    shows when the file is opened. ``row`` is ``None`` for file-level findings.
    """

    severity: Severity
    code: str
    file: str
    row: int | None
    field: str | None
    message: str
    fix: str
    vehicle_id: str | None = None

    def sort_key(self) -> tuple:
        return (
            0 if self.severity is Severity.ERROR else 1,
            self.file,
            self.row if self.row is not None else 0,
            self.field or "",
            self.code,
            self.message,
        )


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    row: int
    asset_class: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    department: str | None = None
    in_service_date: date | None = None
    current_odometer: Decimal | None = None
    current_engine_hours: Decimal | None = None


@dataclass(frozen=True)
class ServiceRecord:
    vehicle_id: str
    row: int
    service_date: date
    service_type: str
    odometer: Decimal | None = None
    engine_hours: Decimal | None = None
    cost: Decimal | None = None
    notes: str | None = None
    # Optional. "preventive" or "corrective" when supplied; None when the
    # column is absent or the cell is blank. Only used for the
    # repeated-maintenance signal, which is skipped without it.
    category: str | None = None


class Status(str, Enum):
    """Maintenance status for a criterion, a task, or a vehicle.

    Severity order (most severe first):
      OVERDUE > DUE_SOON > INSUFFICIENT_DATA > CURRENT

    INSUFFICIENT_DATA outranks CURRENT deliberately: a missing reading is
    never treated as evidence that a task is current.
    """

    CURRENT = "CURRENT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"

    @property
    def rank(self) -> int:
        return _STATUS_RANK[self]

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")


_STATUS_RANK = {
    Status.CURRENT: 0,
    Status.INSUFFICIENT_DATA: 1,
    Status.DUE_SOON: 2,
    Status.OVERDUE: 3,
}


class Meter(str, Enum):
    MILES = "miles"
    HOURS = "hours"
    MONTHS = "months"


@dataclass(frozen=True)
class CriterionResult:
    """Evaluation of one interval criterion (miles, hours, or months)."""

    meter: Meter
    status: Status
    interval: Decimal
    # Elapsed miles/hours since last service, or elapsed days for months.
    elapsed: Decimal | None
    # For the months meter this is the full interval expressed in days so
    # the utilization denominator is explicit in explanations.
    interval_basis: Decimal | None
    utilization: Fraction | None
    last_value: str | None
    current_value: str | None
    note: str | None = None


@dataclass(frozen=True)
class TaskResult:
    task_name: str
    status: Status
    last_service_date: date | None
    last_service_row: int | None
    assumed_baseline: bool
    criteria: tuple[CriterionResult, ...]
    governing_criterion: CriterionResult | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class VehicleAssessment:
    vehicle: Vehicle
    status: Status
    governing_task: str | None
    governing_meter: Meter | None
    governing_utilization: Fraction | None
    tasks: tuple[TaskResult, ...]
    unmapped_service_types: tuple[str, ...]
    service_record_count: int
    # None when the service history has no category information at all for
    # this vehicle; otherwise the count of corrective records in the window.
    corrective_in_window: int | None
    repeat_window_months: int
    data_gaps: tuple[str, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    weight: Fraction
    value: Fraction  # 0..1
    inputs: tuple[tuple[str, str], ...]
    explanation: str

    @property
    def contribution(self) -> Fraction:
        """Points contributed to the 0-100 score."""
        return self.weight * self.value * 100


@dataclass(frozen=True)
class ScoreResult:
    score: Fraction  # 0..100
    band: str
    method_id: str
    components: tuple[ScoreComponent, ...]


@dataclass(frozen=True)
class VehicleResult:
    assessment: VehicleAssessment
    score: ScoreResult
    rank: int


@dataclass(frozen=True)
class AnalysisMetadata:
    tool_version: str
    schema_version: str
    config_hash: str
    config_source: str
    as_of: date
    scoring_method: str
    vehicle_file: str
    service_file: str
    placeholder_config: bool = False


@dataclass(frozen=True)
class AnalysisResult:
    metadata: AnalysisMetadata
    findings: tuple[Finding, ...]
    results: tuple[VehicleResult, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def blocked(self) -> bool:
        return bool(self.errors)
