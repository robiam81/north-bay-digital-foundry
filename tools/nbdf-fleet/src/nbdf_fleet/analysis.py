# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Analysis service: ingest -> validate -> assess -> score -> rank.

This is the single orchestration point used by every CLI command. It has no
knowledge of output formats.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from . import SCHEMA_VERSION, __version__
from .config import RulesConfig
from .ingest import load_services, load_vehicles
from .models import AnalysisMetadata, AnalysisResult, Finding, VehicleResult
from .rules import assess_vehicle, build_alias_index
from .scoring import create_scorer
from .validation import validate


def load_and_validate(
    vehicle_path: Path,
    service_path: Path,
    config: RulesConfig,
    as_of: date,
):
    """Read both files and run every validation. Never raises on bad rows."""
    vehicles, vehicle_findings = load_vehicles(vehicle_path)
    services, service_findings = load_services(service_path)
    cross_findings, vehicles, services = validate(
        vehicles, services, config, as_of, vehicle_path.name, service_path.name
    )
    findings = sorted(
        [*vehicle_findings, *service_findings, *cross_findings], key=Finding.sort_key
    )
    return findings, vehicles, services


def run_analysis(
    vehicle_path: Path,
    service_path: Path,
    config: RulesConfig,
    as_of: date,
) -> AnalysisResult:
    """Full pipeline. If validation errors exist the result carries only findings."""
    scorer = create_scorer(config)  # fail fast on an unknown method
    metadata = AnalysisMetadata(
        tool_version=__version__,
        schema_version=SCHEMA_VERSION,
        config_hash=config.config_hash,
        config_source=config.source,
        as_of=as_of,
        scoring_method=scorer.method_id,
        vehicle_file=vehicle_path.name,
        service_file=service_path.name,
        placeholder_config=config.placeholder_intervals,
    )
    findings, vehicles, services = load_and_validate(vehicle_path, service_path, config, as_of)
    result = AnalysisResult(metadata=metadata, findings=tuple(findings))
    if result.blocked:
        return result

    alias_index = build_alias_index(config)
    scored: list[VehicleResult] = []
    for vehicle in vehicles:
        assessment = assess_vehicle(vehicle, services, config, as_of, alias_index)
        scored.append(VehicleResult(assessment=assessment, score=scorer.score(assessment), rank=0))

    # Explicit, stable ordering: score descending, then vehicle ID ascending.
    scored.sort(key=lambda r: (-r.score.score, r.assessment.vehicle.vehicle_id))
    ranked = tuple(
        VehicleResult(assessment=r.assessment, score=r.score, rank=index)
        for index, r in enumerate(scored, start=1)
    )
    return AnalysisResult(metadata=metadata, findings=tuple(findings), results=ranked)


def find_vehicle(result: AnalysisResult, vehicle_id: str) -> VehicleResult | None:
    wanted = vehicle_id.strip()
    for item in result.results:
        if item.assessment.vehicle.vehicle_id == wanted:
            return item
    lowered = wanted.lower()
    for item in result.results:
        if item.assessment.vehicle.vehicle_id.lower() == lowered:
            return item
    return None
