# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Month arithmetic audit: end-of-month clamping, leap February, exact
boundaries, partial months, and unit consistency across every output format."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from nbdf_fleet.analysis import run_analysis
from nbdf_fleet.dates import add_months
from nbdf_fleet.models import Meter, ServiceRecord, Status, Vehicle
from nbdf_fleet.reports import render_csv, render_explanation, render_html, render_json, render_text
from nbdf_fleet.reports.common import criterion_interval_text, governing_threshold_text
from nbdf_fleet.rules import assess_vehicle
from tests.conftest import SERVICE_HEADER, VEHICLE_HEADER, write_csv


def _months(vehicle_odometer, last_date, as_of, config, interval_task="Oil change"):
    v = Vehicle(vehicle_id="V1", row=2, asset_class="light-duty", current_odometer=Decimal(vehicle_odometer))
    s = ServiceRecord(vehicle_id="V1", row=2, service_date=last_date, service_type=interval_task,
                      odometer=Decimal(5000))
    a = assess_vehicle(v, [s], config, as_of)
    task = next(t for t in a.tasks if t.task_name == interval_task)
    return next(c for c in task.criteria if c.meter is Meter.MONTHS)


@pytest.mark.parametrize(
    "start, months, expected",
    [
        (date(2026, 1, 31), 1, date(2026, 2, 28)),   # clamp to non-leap February
        (date(2024, 1, 31), 1, date(2024, 2, 29)),   # clamp to leap February
        (date(2024, 2, 29), 12, date(2025, 2, 28)),  # leap day + 1 year
        (date(2024, 2, 29), 48, date(2028, 2, 29)),  # leap day + 4 years
        (date(2025, 8, 31), 6, date(2026, 2, 28)),   # 6-month interval crossing a year end
        (date(2026, 3, 31), 1, date(2026, 4, 30)),   # 31st -> 30-day month
        (date(2026, 1, 15), 6, date(2026, 7, 15)),   # ordinary day is preserved
    ],
)
def test_add_months_end_of_month_and_leap_year(start, months, expected):
    assert add_months(start, months) == expected


def test_interval_basis_is_calendar_days_of_the_actual_interval(small_config):
    # 6 months from 2025-08-31 is 2026-02-28: 181 days (not 6 x 30.4375).
    c = _months(5000, date(2025, 8, 31), date(2026, 1, 1), small_config)
    assert c.interval == Decimal(6)
    assert c.interval_basis == Decimal(181)
    assert c.elapsed == Decimal(123)
    assert c.utilization == Fraction(123, 181)
    # Leap year: 6 months from 2023-12-31 is 2024-06-30 -> 182 days including Feb 29.
    c = _months(5000, date(2023, 12, 31), date(2024, 3, 1), small_config)
    assert c.interval_basis == Decimal(182)
    assert c.elapsed == Decimal(61)


def test_exact_month_boundaries(small_config):
    last = date(2025, 12, 30)  # 6 months -> due 2026-06-30
    due_day = _months(5000, last, date(2026, 6, 30), small_config)
    assert due_day.utilization == Fraction(1) and due_day.status is Status.OVERDUE
    day_before = _months(5000, last, date(2026, 6, 29), small_config)
    assert day_before.utilization == Fraction(181, 182) and day_before.status is Status.DUE_SOON
    same_day = _months(5000, last, last, small_config)
    assert same_day.utilization == Fraction(0) and same_day.status is Status.CURRENT
    # exact due-soon boundary: 182 * 0.85 = 154.7 is not a whole day, so use a
    # 12-month interval from 2025-06-30 (365 days): 0.85 * 365 = 310.25 -> also
    # fractional. Use the 6-month interval from a leap-free 180-day span: no
    # such span exists in the calendar, so assert the ordering instead.
    just_below = _months(5000, last, date(2026, 5, 23), small_config)  # 144/182 = 0.791
    assert just_below.status is Status.CURRENT
    just_above = _months(5000, last, date(2026, 6, 4), small_config)  # 156/182 = 0.857
    assert just_above.status is Status.DUE_SOON


def test_partial_months_are_fractional_days_not_whole_months(small_config):
    # 45 days into a 183-day interval -> 0.2459, not "1 month of 6".
    c = _months(5000, date(2026, 1, 1), date(2026, 2, 15), small_config)
    assert c.elapsed == Decimal(45)
    assert c.interval_basis == Decimal(181)
    assert c.utilization == Fraction(45, 181)


def test_month_display_helper_units():
    class C:
        meter = Meter.MONTHS
        interval = Decimal(12)
        interval_basis = Decimal(365)
        elapsed = Decimal(411)

    assert criterion_interval_text(C()) == "365 days (12-month interval)"


def test_time_criterion_renders_consistently_in_every_format(tmp_path, small_config):
    # OVERDUE by time only: last oil 2025-05-15, 6 months -> due 2025-11-15 (184 d);
    # as-of 2026-06-30 -> 411 elapsed days; miles 200/5000 stay CURRENT.
    v = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["V1,,,,light-duty,,,5200,"])
    s = write_csv(tmp_path / "s.csv", SERVICE_HEADER, ["V1,2025-05-15,Oil change,5000,,10,,"])
    result = run_analysis(v, s, small_config, date(2026, 6, 30))
    item = result.results[0]
    assert item.assessment.governing_meter is Meter.MONTHS

    expected = "Engine oil".replace("Engine oil", "Oil change") + ": 411 of 184 days (6-month interval) (223%)"
    assert governing_threshold_text(item) == expected

    text = render_text(result)
    assert expected in text
    # guards against the "411 of 12 months" wording seen in an intermediate pass-1
    # build (fixed before the pass-1 snapshot); days must never be shown as months
    assert "of 6 months (" not in text

    explanation = render_explanation(result, item)
    assert "elapsed 411 days of 184 days (6-month interval); utilization 2.2337" in explanation

    doc = json.loads(render_json(result))
    criterion = next(c for t in doc["vehicles"][0]["tasks"] for c in t["criteria"] if c["meter"] == "months")
    assert (criterion["elapsed"], criterion["interval_basis"], criterion["interval"]) == (411, 184, 6)
    assert criterion["utilization"] == 2.2337
    assert doc["vehicles"][0]["governing_utilization"] == 2.2337

    rows = list(csv.DictReader(io.StringIO(render_csv(result), newline="")))
    assert rows[0]["governing_meter"] == "months"
    assert rows[0]["governing_utilization"] == "2.2337"

    html = render_html(result)
    assert "411 of 184 days (6-month interval) (223%)" in html
    assert '<td class="num">411</td>' in html and "184 days (6-month interval)" in html
    assert "2.2337" in html
