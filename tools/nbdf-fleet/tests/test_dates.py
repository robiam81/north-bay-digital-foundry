# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

from datetime import date

import pytest

from nbdf_fleet.dates import DateParseError, add_months, parse_date


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-06-30", date(2026, 6, 30)),
        ("  2026-06-30 ", date(2026, 6, 30)),
        ("6/30/2026", date(2026, 6, 30)),
        ("06/30/2026", date(2026, 6, 30)),
        ("1/5/2024", date(2024, 1, 5)),
    ],
)
def test_accepted_forms(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("6/30/26", "two-digit year"),
        ("06-30-26", "two-digit year"),
        ("2026/06/30", "not an accepted date form"),
        ("30/06/2026", "not a valid calendar date"),
        ("2026-6-30", "not an accepted date form"),
        ("2026-02-30", "not a valid calendar date"),
        ("2026-06-30T00:00:00", "not an accepted date form"),
        ("June 30 2026", "not an accepted date form"),
        ("", "empty"),
        ("0999-01-01", "implausible year"),
    ],
)
def test_rejected_forms(text, fragment):
    with pytest.raises(DateParseError) as info:
        parse_date(text)
    assert fragment in str(info.value)


def test_add_months_clamps_day_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 3, 31), 6) == date(2026, 9, 30)


def test_add_months_negative_and_year_rollover():
    assert add_months(date(2026, 6, 30), -12) == date(2025, 6, 30)
    assert add_months(date(2025, 11, 15), 3) == date(2026, 2, 15)
