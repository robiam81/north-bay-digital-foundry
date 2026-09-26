# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from nbdf_fleet.analysis import run_analysis
from nbdf_fleet.config import ConfigError, build_config
from nbdf_fleet.models import Meter, ServiceRecord, Status, Vehicle
from nbdf_fleet.rules import assess_vehicle, classify
from nbdf_fleet.scoring import MaintenanceScorer, RulesBasedScorer, create_scorer
from tests.conftest import SERVICE_HEADER, VEHICLE_HEADER, minimal_config_dict, write_csv

AS_OF = date(2026, 6, 30)
DUE_SOON = Fraction(17, 20)


def vehicle(**kw) -> Vehicle:
    base = dict(vehicle_id="V1", row=2, asset_class="light-duty", in_service_date=date(2024, 1, 1),
                current_odometer=Decimal(10000))
    base.update(kw)
    return Vehicle(**base)


def service(**kw) -> ServiceRecord:
    # 2026-04-01 -> 90 of 183 days on a 6-month interval (CURRENT by time)
    base = dict(vehicle_id="V1", row=2, service_date=date(2026, 4, 1), service_type="Oil change",
                odometer=Decimal(5000))
    base.update(kw)
    return ServiceRecord(**base)


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utilization, expected",
    [
        (Fraction(0), Status.CURRENT),
        (Fraction(4249, 5000), Status.CURRENT),   # just below 0.85
        (Fraction(4250, 5000), Status.DUE_SOON),  # exactly 0.85 -> DUE SOON
        (Fraction(4999, 5000), Status.DUE_SOON),  # just below 1.0
        (Fraction(1), Status.OVERDUE),            # exactly 1.0 -> OVERDUE
        (Fraction(3, 2), Status.OVERDUE),
    ],
)
def test_classification_boundaries(utilization, expected):
    assert classify(utilization, DUE_SOON) is expected


def test_mileage_interval_calculation(small_config):
    a = assess_vehicle(vehicle(current_odometer=Decimal(9250)), [service()], small_config, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    miles = next(c for c in oil.criteria if c.meter is Meter.MILES)
    assert miles.elapsed == Decimal(4250)
    assert miles.utilization == Fraction(17, 20)
    assert miles.status is Status.DUE_SOON
    assert oil.governing_criterion is miles


def test_exact_mileage_boundary_is_overdue(small_config):
    a = assess_vehicle(vehicle(current_odometer=Decimal(10000)), [service()], small_config, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    assert next(c for c in oil.criteria if c.meter is Meter.MILES).status is Status.OVERDUE


def test_months_criterion_uses_calendar_due_date(small_config):
    # 6-month interval from 2025-12-30 -> due 2026-06-30 == as-of -> utilization exactly 1.0
    a = assess_vehicle(
        vehicle(current_odometer=Decimal(5000)),
        [service(service_date=date(2025, 12, 30))], small_config, AS_OF,
    )
    months = next(c for t in a.tasks for c in t.criteria if c.meter is Meter.MONTHS)
    assert months.interval_basis == Decimal(182)
    assert months.elapsed == Decimal(182)
    assert months.utilization == Fraction(1)
    assert months.status is Status.OVERDUE
    # one day earlier is DUE SOON
    b = assess_vehicle(
        vehicle(current_odometer=Decimal(5000)),
        [service(service_date=date(2025, 12, 30))], small_config, date(2026, 6, 29),
    )
    months_b = next(c for t in b.tasks for c in t.criteria if c.meter is Meter.MONTHS)
    assert months_b.status is Status.DUE_SOON


def test_hours_based_asset_class(small_config):
    v = vehicle(asset_class="equipment", current_odometer=None, current_engine_hours=Decimal("1240.5"))
    a = assess_vehicle(v, [service(odometer=None, engine_hours=Decimal(1000))], small_config, AS_OF)
    assert [t.task_name for t in a.tasks] == ["Oil change"]  # brakes do not apply to equipment
    hours = a.tasks[0].criteria[0]
    assert hours.meter is Meter.HOURS
    assert hours.utilization == Fraction(Decimal("240.5")) / 250
    assert a.status is Status.DUE_SOON
    assert a.governing_meter is Meter.HOURS


# ---------------------------------------------------------------------------
# Missing data
# ---------------------------------------------------------------------------


def test_no_service_record_is_insufficient_data_not_current(small_config):
    a = assess_vehicle(vehicle(), [], small_config, AS_OF)
    assert a.status is Status.INSUFFICIENT_DATA
    assert all(t.status is Status.INSUFFICIENT_DATA for t in a.tasks)
    assert all(not t.assumed_baseline for t in a.tasks)
    assert len(a.data_gaps) == 3  # oil miles, oil months, brakes miles
    assert a.governing_task == "Oil change"


def test_baseline_assumption_only_when_enabled_and_labeled():
    cfg = build_config(minimal_config_dict(baseline={"assume_in_service_baseline": True}), "t")
    a = assess_vehicle(vehicle(in_service_date=date(2025, 12, 1), current_odometer=Decimal(4000)), [], cfg, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    assert oil.assumed_baseline
    assert oil.last_service_date == date(2025, 12, 1)
    assert any("ASSUMED BASELINE" in n for n in oil.notes)
    assert next(c for c in oil.criteria if c.meter is Meter.MILES).elapsed == Decimal(4000)
    # without an in-service date the baseline cannot be assumed
    b = assess_vehicle(vehicle(in_service_date=None), [], cfg, AS_OF)
    assert b.status is Status.INSUFFICIENT_DATA


def test_missing_current_reading_marks_only_that_criterion(small_config):
    a = assess_vehicle(vehicle(current_odometer=None), [service()], small_config, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    miles = next(c for c in oil.criteria if c.meter is Meter.MILES)
    months = next(c for c in oil.criteria if c.meter is Meter.MONTHS)
    assert miles.status is Status.INSUFFICIENT_DATA and "missing" in miles.note
    assert months.status is Status.CURRENT
    assert oil.status is Status.INSUFFICIENT_DATA  # a gap outranks CURRENT


def test_overdue_evidence_outranks_data_gap_but_gap_is_still_listed(small_config):
    # Oil: miles overdue; Brakes: odometer missing at last service -> gap
    records = [service(), service(row=3, service_type="brakes", odometer=None)]
    a = assess_vehicle(vehicle(current_odometer=Decimal(12000)), records, small_config, AS_OF)
    assert a.status is Status.OVERDUE
    assert a.governing_task == "Oil change"
    assert any("Brake inspection" in gap for gap in a.data_gaps)


def test_current_reading_below_last_service_is_a_gap(small_config):
    a = assess_vehicle(vehicle(current_odometer=Decimal(4000)), [service()], small_config, AS_OF)
    miles = next(c for t in a.tasks for c in t.criteria if c.meter is Meter.MILES and t.task_name == "Oil change")
    assert miles.status is Status.INSUFFICIENT_DATA
    assert "below" in miles.note


def test_unmapped_service_types_are_listed_not_evaluated(small_config):
    records = [service(service_type="Wiper blades")]
    a = assess_vehicle(vehicle(), records, small_config, AS_OF)
    assert a.unmapped_service_types == ("Wiper blades",)
    assert a.status is Status.INSUFFICIENT_DATA


def test_alias_matching_is_case_and_space_insensitive(small_config):
    records = [service(service_type="  LOF  ")]
    a = assess_vehicle(vehicle(current_odometer=Decimal(6000)), records, small_config, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    assert oil.last_service_row == 2
    assert a.unmapped_service_types == ()


def test_latest_service_wins_over_earlier(small_config):
    records = [service(row=2, service_date=date(2025, 1, 1), odometer=Decimal(1000)),
               service(row=3, service_date=date(2026, 5, 1), odometer=Decimal(9000))]
    a = assess_vehicle(vehicle(current_odometer=Decimal(10000)), records, small_config, AS_OF)
    oil = next(t for t in a.tasks if t.task_name == "Oil change")
    assert oil.last_service_row == 3
    assert oil.status is Status.CURRENT


def test_repeat_signal_counts_corrective_only_inside_window(small_config):
    records = [
        service(row=2, service_type="Starter", service_date=date(2026, 1, 1), category="corrective"),
        service(row=3, service_type="Starter", service_date=date(2025, 6, 29), category="corrective"),  # outside
        service(row=4, service_type="Starter", service_date=date(2025, 6, 30), category="corrective"),  # boundary in
        service(row=5, service_type="Oil change", service_date=date(2026, 5, 1), category="preventive"),
    ]
    a = assess_vehicle(vehicle(), records, small_config, AS_OF)
    assert a.corrective_in_window == 2
    b = assess_vehicle(vehicle(), [service()], small_config, AS_OF)
    assert b.corrective_in_window is None  # no category data at all


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_scorer_satisfies_protocol_and_is_deterministic(small_config):
    scorer = create_scorer(small_config)
    assert isinstance(scorer, MaintenanceScorer)
    assert isinstance(scorer, RulesBasedScorer)
    a = assess_vehicle(vehicle(current_odometer=Decimal(12500)), [service()], small_config, AS_OF)
    first, second = scorer.score(a), scorer.score(a)
    assert first == second
    assert sum(c.contribution for c in first.components) == first.score
    assert [c.name for c in first.components] == [
        "governing_utilization", "overdue_magnitude", "additional_pressure",
        "repeat_maintenance", "data_completeness",
    ]


def test_score_components_for_overdue_vehicle(small_config):
    # oil miles 7500/5000 = 1.5 ; oil months 180/181 ; brakes 7500/15000 = 0.5
    records = [service(service_date=date(2026, 1, 1), odometer=Decimal(5000)),
               service(row=3, service_type="brakes", service_date=date(2026, 1, 1), odometer=Decimal(5000))]
    a = assess_vehicle(vehicle(current_odometer=Decimal(12500)), records, small_config, AS_OF)
    result = create_scorer(small_config).score(a)
    by_name = {c.name: c for c in result.components}
    assert by_name["governing_utilization"].value == 1
    assert by_name["overdue_magnitude"].value == Fraction(1, 2)
    assert by_name["additional_pressure"].value == Fraction(1, 2)  # months due soon, brakes current
    assert by_name["repeat_maintenance"].value == 0
    assert by_name["data_completeness"].value == 0
    assert result.score == 30 + Fraction(25, 2) + 5
    assert result.band == "MEDIUM"
    assert all(c.inputs and c.explanation for c in result.components)


def test_incomplete_records_score_above_healthy_ones(small_config):
    scorer = create_scorer(small_config)
    no_data = scorer.score(assess_vehicle(vehicle(), [], small_config, AS_OF))
    healthy = scorer.score(assess_vehicle(vehicle(current_odometer=Decimal(5500)), [
        service(), service(row=3, service_type="brakes")], small_config, AS_OF))
    assert no_data.score == 25
    assert no_data.band == "MEDIUM"  # exactly at the band boundary
    assert no_data.score > healthy.score
    assert healthy.band == "LOW"


def test_weights_must_sum_to_one_and_method_must_exist():
    bad = minimal_config_dict()
    bad["scoring"]["weights"]["governing_utilization"] = 0.5
    with pytest.raises(ConfigError, match="sum to exactly 1.0"):
        build_config(bad, "t")
    unknown = minimal_config_dict()
    unknown["scoring"]["method"] = "neural"
    with pytest.raises(ConfigError, match="not available"):
        create_scorer(build_config(unknown, "t"))


def test_config_rejects_bad_task_definitions():
    dup_alias = minimal_config_dict()
    dup_alias["tasks"][1]["aliases"] = ["oil"]
    with pytest.raises(ConfigError, match="claimed by both"):
        build_config(dup_alias, "t")
    bad_class = minimal_config_dict()
    bad_class["tasks"][0]["schedules"][0]["asset_classes"] = ["hovercraft"]
    with pytest.raises(ConfigError, match="undefined asset class"):
        build_config(bad_class, "t")
    no_interval = minimal_config_dict()
    no_interval["tasks"][1]["schedules"][0] = {"asset_classes": ["light-duty"]}
    with pytest.raises(ConfigError, match="at least one of"):
        build_config(no_interval, "t")


def test_config_hash_ignores_formatting_but_not_values():
    a = build_config(minimal_config_dict(), "a")
    b = build_config(minimal_config_dict(), "b")
    assert a.config_hash == b.config_hash
    changed = minimal_config_dict(thresholds={"due_soon_utilization": 0.8})
    assert build_config(changed, "c").config_hash != a.config_hash


def test_ranking_is_score_desc_then_vehicle_id(tmp_path, small_config):
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, [
        "B,,,,light-duty,,,10000,", "A,,,,light-duty,,,10000,", "C,,,,light-duty,,,12000,",
    ])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, [
        "A,2026-01-01,Oil change,5000,,,,", "B,2026-01-01,Oil change,5000,,,,",
        "C,2026-01-01,Oil change,5000,,,,",
    ])
    result = run_analysis(v, s, small_config, AS_OF)
    assert [r.assessment.vehicle.vehicle_id for r in result.results] == ["C", "A", "B"]
    assert [r.rank for r in result.results] == [1, 2, 3]
    assert result.results[1].score.score == result.results[2].score.score
