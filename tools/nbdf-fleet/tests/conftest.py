# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Shared fixtures. All generated output goes to pytest's tmp_path."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.dont_write_bytecode = True  # belt and braces; PYTHONDONTWRITEBYTECODE=1 is the documented way

from nbdf_fleet.config import RulesConfig, build_config, load_config  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
EXAMPLES = PROJECT_DIR / "examples"
INVALID = EXAMPLES / "invalid"
AS_OF = date(2026, 6, 30)


@pytest.fixture
def as_of() -> date:
    return AS_OF


@pytest.fixture
def config() -> RulesConfig:
    return load_config(None)


@pytest.fixture
def examples() -> Path:
    return EXAMPLES


@pytest.fixture
def invalid_examples() -> Path:
    return INVALID


def minimal_config_dict(**overrides) -> dict:
    """A small, valid configuration used to build focused rule tests."""
    data = {
        "schema_version": 1,
        "thresholds": {"due_soon_utilization": 0.85},
        "validation": {
            "max_miles_per_day": 600,
            "max_engine_hours_per_day": 24,
            "min_model_year": 1950,
            "max_model_years_ahead": 1,
        },
        "baseline": {"assume_in_service_baseline": False},
        "scoring": {
            "method": "rules",
            "overdue_saturation": 1.0,
            "repeat_lookback_months": 12,
            "repeat_saturation_count": 3,
            "weights": {
                "governing_utilization": 0.30,
                "overdue_magnitude": 0.25,
                "additional_pressure": 0.10,
                "repeat_maintenance": 0.10,
                "data_completeness": 0.25,
            },
            "bands": {"high": 50, "medium": 25},
        },
        "asset_classes": [
            {"name": "light-duty", "primary_meter": "miles"},
            {"name": "equipment", "primary_meter": "hours"},
        ],
        "tasks": [
            {
                "name": "Oil change",
                "aliases": ["oil", "lof"],
                "schedules": [
                    {"asset_classes": ["light-duty"], "interval_miles": 5000, "interval_months": 6},
                    {"asset_classes": ["equipment"], "interval_hours": 250},
                ],
            },
            {
                "name": "Brake inspection",
                "aliases": ["brakes"],
                "schedules": [{"asset_classes": ["light-duty"], "interval_miles": 15000}],
            },
        ],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


@pytest.fixture
def small_config() -> RulesConfig:
    return build_config(minimal_config_dict(), "test-config")


def write_csv(path: Path, header: str, rows: list[str], *, bom: bool = False, crlf: bool = False) -> Path:
    newline = "\r\n" if crlf else "\n"
    text = newline.join([header, *rows]) + newline
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return path


VEHICLE_HEADER = (
    "vehicle_id,year,make,model,asset_class,department,in_service_date,"
    "current_odometer,current_engine_hours"
)
SERVICE_HEADER = "vehicle_id,service_date,service_type,odometer,engine_hours,cost,category,notes"
