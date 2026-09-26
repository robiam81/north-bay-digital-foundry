# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Maintenance priority scoring.

Defines the :class:`MaintenanceScorer` Protocol (the integration point for a
future validated statistical or ML scorer) and the only implementation that
exists today: :class:`RulesBasedScorer`, a deterministic weighted sum of
explainable components.

The score is a PLANNING HEURISTIC. It orders vehicles for human review. It is
not a failure probability and has not been validated against outcomes.

Adding a new scorer:
  1. Implement a class with ``method_id`` and ``score(assessment)``.
  2. Register it in :data:`SCORERS`.
  3. Select it with ``[scoring] method = "<method_id>"`` in the TOML config.
Ingestion, validation, reporting, and the CLI do not change.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Protocol, runtime_checkable

from .config import BAND_HIGH, BAND_LOW, BAND_MEDIUM, ConfigError, RulesConfig
from .models import CriterionResult, ScoreComponent, ScoreResult, Status, VehicleAssessment

DUE_STATUSES = (Status.DUE_SOON, Status.OVERDUE)


@runtime_checkable
class MaintenanceScorer(Protocol):
    """Anything that turns a :class:`VehicleAssessment` into a :class:`ScoreResult`."""

    method_id: str

    def score(self, assessment: VehicleAssessment) -> ScoreResult: ...


def band_for(score: Fraction, config: RulesConfig) -> str:
    """Priority band from the score rounded to one decimal place."""
    rounded = round(score, 1)
    if rounded >= config.scoring.band_high:
        return BAND_HIGH
    if rounded >= config.scoring.band_medium:
        return BAND_MEDIUM
    return BAND_LOW


def _fmt_fraction(value: Fraction | None, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


class RulesBasedScorer:
    """Deterministic weighted-sum scorer over rules-engine results."""

    method_id = "rules"

    def __init__(self, config: RulesConfig) -> None:
        self.config = config

    def score(self, assessment: VehicleAssessment) -> ScoreResult:
        scoring = self.config.scoring
        evaluated: list[tuple[str, CriterionResult]] = [
            (task.task_name, criterion)
            for task in assessment.tasks
            for criterion in task.criteria
            if criterion.utilization is not None
        ]
        all_criteria = [criterion for task in assessment.tasks for criterion in task.criteria]

        # Highest utilization anywhere; ties resolved by task then meter order,
        # which is the iteration order of ``evaluated``.
        top: tuple[str, CriterionResult] | None = None
        for item in evaluated:
            if top is None or item[1].utilization > top[1].utilization:  # type: ignore[operator]
                top = item
        top_utilization = top[1].utilization if top else None

        components: list[ScoreComponent] = []

        # 1. governing utilization ------------------------------------------
        if top_utilization is None:
            value = Fraction(0)
            explanation = "no criterion could be evaluated, so this component is 0"
            inputs = (("evaluated criteria", "0"),)
        else:
            value = min(Fraction(1), top_utilization)
            explanation = (
                f"highest utilization is {_fmt_fraction(top_utilization)} on "
                f"'{top[0]}' ({top[1].meter.value}); capped at 1.0"
            )
            inputs = (
                ("task", top[0]),
                ("meter", top[1].meter.value),
                ("elapsed", str(top[1].elapsed)),
                ("interval basis", str(top[1].interval_basis)),
                ("utilization", _fmt_fraction(top_utilization)),
            )
        components.append(
            ScoreComponent("governing_utilization", scoring.weight("governing_utilization"), value, inputs, explanation)
        )

        # 2. overdue magnitude ------------------------------------------------
        if top_utilization is None or top_utilization <= 1:
            value = Fraction(0)
            explanation = "no criterion is past its interval, so this component is 0"
            inputs = (("highest utilization", _fmt_fraction(top_utilization)),)
        else:
            excess = top_utilization - 1
            value = min(Fraction(1), excess / scoring.overdue_saturation)
            explanation = (
                f"'{top[0]}' is {_fmt_fraction(excess)} past its interval; divided by "
                f"overdue_saturation {_fmt_fraction(scoring.overdue_saturation, 2)} and capped at 1.0"
            )
            inputs = (
                ("task", top[0]),
                ("utilization", _fmt_fraction(top_utilization)),
                ("excess over 1.0", _fmt_fraction(excess)),
                ("overdue_saturation", _fmt_fraction(scoring.overdue_saturation, 2)),
            )
        components.append(
            ScoreComponent("overdue_magnitude", scoring.weight("overdue_magnitude"), value, inputs, explanation)
        )

        # 3. additional pressure ---------------------------------------------
        others = [item for item in evaluated if top is None or item[1] is not top[1]]
        due_others = [item for item in others if item[1].status in DUE_STATUSES]
        if not others:
            value = Fraction(0)
            explanation = "no other evaluated criteria, so this component is 0"
        else:
            value = Fraction(len(due_others), len(others))
            explanation = (
                f"{len(due_others)} of {len(others)} other evaluated criteria are DUE SOON or OVERDUE"
            )
        inputs = (
            ("other evaluated criteria", str(len(others))),
            ("of which due soon/overdue", ", ".join(f"{t} ({c.meter.value})" for t, c in due_others) or "none"),
        )
        components.append(
            ScoreComponent("additional_pressure", scoring.weight("additional_pressure"), value, inputs, explanation)
        )

        # 4. repeat maintenance ----------------------------------------------
        if assessment.corrective_in_window is None:
            value = Fraction(0)
            explanation = (
                "service history has no preventive/corrective category data for this vehicle; "
                "signal not computed (component is 0, not evidence of reliability)"
            )
            inputs = (("category data", "absent"),)
        else:
            value = min(Fraction(1), Fraction(assessment.corrective_in_window, scoring.repeat_saturation_count))
            explanation = (
                f"{assessment.corrective_in_window} corrective record(s) in the last "
                f"{assessment.repeat_window_months} months; saturates at {scoring.repeat_saturation_count}"
            )
            inputs = (
                ("corrective records in window", str(assessment.corrective_in_window)),
                ("window (months)", str(assessment.repeat_window_months)),
                ("saturation count", str(scoring.repeat_saturation_count)),
            )
        components.append(
            ScoreComponent("repeat_maintenance", scoring.weight("repeat_maintenance"), value, inputs, explanation)
        )

        # 5. data completeness (missing share RAISES priority) ---------------
        missing = [c for c in all_criteria if c.status is Status.INSUFFICIENT_DATA]
        if not all_criteria:
            value = Fraction(1)
            explanation = "no maintenance rules apply, so nothing could be checked; treated as fully incomplete"
            inputs = (("criteria checked", "0"),)
        else:
            value = Fraction(len(missing), len(all_criteria))
            explanation = (
                f"{len(missing)} of {len(all_criteria)} criteria could not be evaluated; "
                "missing data raises priority so the record is reviewed"
            )
            inputs = (
                ("criteria checked", str(len(all_criteria))),
                ("criteria with insufficient data", str(len(missing))),
            )
        components.append(
            ScoreComponent("data_completeness", scoring.weight("data_completeness"), value, inputs, explanation)
        )

        total = sum((c.contribution for c in components), Fraction(0))
        return ScoreResult(
            score=total,
            band=band_for(total, self.config),
            method_id=self.method_id,
            components=tuple(components),
        )


# Registry of available scoring methods, keyed by ``[scoring] method``.
SCORERS: dict[str, type] = {
    RulesBasedScorer.method_id: RulesBasedScorer,
}


def create_scorer(config: RulesConfig) -> MaintenanceScorer:
    method = config.scoring.method
    scorer_type = SCORERS.get(method)
    if scorer_type is None:
        available = ", ".join(sorted(SCORERS))
        raise ConfigError(
            f"scoring.method '{method}' is not available; implemented methods: {available}"
        )
    return scorer_type(config)
