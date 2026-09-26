# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Date parsing and calendar arithmetic.

Accepted input forms:
  * ISO 8601 calendar date  ``YYYY-MM-DD``  (primary)
  * U.S. slash form         ``M/D/YYYY`` or ``MM/DD/YYYY``

Everything else is rejected with a message that names the accepted forms.
Two-digit years are rejected explicitly because they are ambiguous.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_US_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_TWO_DIGIT_YEAR_RE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2})$")

ACCEPTED_DATE_FORMS = "YYYY-MM-DD or M/D/YYYY"


class DateParseError(ValueError):
    """Raised when a date string is not in an accepted, unambiguous form."""


def parse_date(text: str) -> date:
    """Parse ``text`` into a :class:`datetime.date`.

    Raises :class:`DateParseError` with an actionable message otherwise.
    """
    value = text.strip()
    if not value:
        raise DateParseError("empty date")

    match = _ISO_RE.match(value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return _build(year, month, day, value)

    match = _US_RE.match(value)
    if match:
        month, day, year = (int(part) for part in match.groups())
        return _build(year, month, day, value)

    if _TWO_DIGIT_YEAR_RE.match(value):
        raise DateParseError(
            f"'{value}' uses a two-digit year, which is ambiguous; "
            f"use a four-digit year ({ACCEPTED_DATE_FORMS})"
        )
    raise DateParseError(
        f"'{value}' is not an accepted date form; use {ACCEPTED_DATE_FORMS}"
    )


def _build(year: int, month: int, day: int, original: str) -> date:
    if year < 1000:
        raise DateParseError(
            f"'{original}' has an implausible year; use a four-digit year ({ACCEPTED_DATE_FORMS})"
        )
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise DateParseError(f"'{original}' is not a valid calendar date ({exc})") from exc


def add_months(start: date, months: int) -> date:
    """Return ``start`` advanced by ``months`` calendar months.

    The day of month is clamped to the last day of the target month
    (e.g. 2026-01-31 + 1 month = 2026-02-28).
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_between(earlier: date, later: date) -> int:
    """Whole days from ``earlier`` to ``later`` (negative if reversed)."""
    return (later - earlier).days
