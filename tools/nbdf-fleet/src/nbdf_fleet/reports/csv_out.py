# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""CSV export with stable column order and formula neutralization."""

from __future__ import annotations

import csv
import io

from ..models import AnalysisResult
from .common import FINDING_COLUMNS, VEHICLE_COLUMNS, finding_dict, neutralize, vehicle_row, warning_counts


def _writer(buffer: io.StringIO) -> csv.writer:
    # RFC 4180 line endings; the buffer is created with newline="" by callers.
    return csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)


def _cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return neutralize(value)


def render_csv(result: AnalysisResult) -> str:
    """Vehicle-level results, one row per vehicle, ranked."""
    buffer = io.StringIO(newline="")
    writer = _writer(buffer)
    writer.writerow(VEHICLE_COLUMNS)
    counts = warning_counts(result)
    for item in result.results:
        row = vehicle_row(item, counts.get(item.assessment.vehicle.vehicle_id, 0))
        writer.writerow([_cell(row[column]) for column in VEHICLE_COLUMNS])
    return buffer.getvalue()


def render_findings_csv(result: AnalysisResult) -> str:
    buffer = io.StringIO(newline="")
    writer = _writer(buffer)
    writer.writerow(FINDING_COLUMNS)
    for finding in result.findings:
        row = finding_dict(finding)
        writer.writerow([_cell(row[column]) for column in FINDING_COLUMNS])
    return buffer.getvalue()
