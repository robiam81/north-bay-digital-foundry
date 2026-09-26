# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""The bundled package resources must stay byte-identical to the project copies."""

from importlib import resources

from nbdf_fleet.config import load_config
from tests.conftest import PROJECT_DIR


def _bundled(name: str) -> bytes:
    return resources.files("nbdf_fleet.resources").joinpath(name).read_bytes()


def test_bundled_default_config_matches_config_directory():
    assert _bundled("default_rules.toml") == (PROJECT_DIR / "config" / "default_rules.toml").read_bytes()


def test_bundled_demo_data_matches_examples_directory():
    for name in ("demo_vehicles.csv", "demo_service_history.csv"):
        assert _bundled(name) == (PROJECT_DIR / "examples" / name).read_bytes(), name


def test_default_config_loads_and_is_documented():
    config = load_config(None)
    assert config.scoring.method == "rules"
    assert sum(w for _, w in config.scoring.weights) == 1
    assert {c.name for c in config.asset_classes} >= {"light-duty", "heavy-duty", "off-road-equipment"}
    assert not config.baseline.assume_in_service_baseline
    text = _bundled("default_rules.toml").decode("utf-8")
    assert "PLACEHOLDER" in text  # the intervals are declared as placeholders
