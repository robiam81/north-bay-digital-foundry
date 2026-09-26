# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""JSON export with explicit key order and ASCII-only encoding."""

from __future__ import annotations

import json

from ..models import AnalysisResult
from .common import finding_dict, metadata_dict, summary_dict, vehicle_detail, warning_counts


def build_document(result: AnalysisResult) -> dict:
    counts = warning_counts(result)
    return {
        "metadata": metadata_dict(result),
        "summary": summary_dict(result),
        "vehicles": [
            vehicle_detail(item, counts.get(item.assessment.vehicle.vehicle_id, 0))
            for item in result.results
        ],
        "findings": [finding_dict(f) for f in result.findings],
    }


def render_json(result: AnalysisResult) -> str:
    # Key order is the insertion order above (never sort_keys, so the
    # document reads top-down); ensure_ascii keeps the bytes console-safe.
    return json.dumps(build_document(result), indent=2, ensure_ascii=True) + "\n"
