# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Rules configuration: load, validate, and hash a TOML rules file.

The configuration defines asset classes, maintenance tasks (with aliases and
per-asset-class intervals), classification thresholds, validation thresholds,
scoring weights and bands, and explicitly enabled baseline assumptions.
See ``config/default_rules.toml`` for the documented default.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from importlib import resources
from pathlib import Path
from typing import Any

from . import CONFIG_SCHEMA_VERSION
from .ingest import normalize_text
from .models import Meter

WEIGHT_NAMES: tuple[str, ...] = (
    "governing_utilization",
    "overdue_magnitude",
    "additional_pressure",
    "repeat_maintenance",
    "data_completeness",
)

BAND_HIGH = "HIGH"
BAND_MEDIUM = "MEDIUM"
BAND_LOW = "LOW"


class ConfigError(Exception):
    """The configuration file is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class AssetClassConfig:
    name: str
    description: str
    primary_meter: Meter | None


@dataclass(frozen=True)
class Schedule:
    asset_classes: tuple[str, ...]
    interval_miles: Decimal | None
    interval_hours: Decimal | None
    interval_months: int | None

    def intervals(self) -> tuple[tuple[Meter, Decimal], ...]:
        out: list[tuple[Meter, Decimal]] = []
        if self.interval_miles is not None:
            out.append((Meter.MILES, self.interval_miles))
        if self.interval_hours is not None:
            out.append((Meter.HOURS, self.interval_hours))
        if self.interval_months is not None:
            out.append((Meter.MONTHS, Decimal(self.interval_months)))
        return tuple(out)


@dataclass(frozen=True)
class TaskConfig:
    name: str
    aliases: tuple[str, ...]  # normalized, includes the normalized name
    schedules: tuple[Schedule, ...]

    def schedule_for(self, asset_class: str) -> Schedule | None:
        for schedule in self.schedules:
            if asset_class in schedule.asset_classes:
                return schedule
        return None


@dataclass(frozen=True)
class Thresholds:
    due_soon_utilization: Fraction


@dataclass(frozen=True)
class ValidationConfig:
    max_miles_per_day: Decimal
    max_engine_hours_per_day: Decimal
    min_model_year: int
    max_model_years_ahead: int


@dataclass(frozen=True)
class ScoringConfig:
    method: str
    weights: tuple[tuple[str, Fraction], ...]
    band_high: Fraction
    band_medium: Fraction
    overdue_saturation: Fraction
    repeat_lookback_months: int
    repeat_saturation_count: int

    def weight(self, name: str) -> Fraction:
        for key, value in self.weights:
            if key == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class BaselineConfig:
    assume_in_service_baseline: bool


@dataclass(frozen=True)
class RulesConfig:
    schema_version: int
    thresholds: Thresholds
    validation: ValidationConfig
    scoring: ScoringConfig
    baseline: BaselineConfig
    asset_classes: tuple[AssetClassConfig, ...]
    tasks: tuple[TaskConfig, ...]
    config_hash: str
    # Display name only: "bundled-default" or the config file's base name.
    # Never a full path, so outputs contain nothing machine-specific.
    source: str
    # [meta] placeholder_intervals: when true the text and HTML reports carry
    # a banner and JSON metadata flags it (CSV tables carry no banner).
    placeholder_intervals: bool = False

    def asset_class(self, name: str) -> AssetClassConfig | None:
        for item in self.asset_classes:
            if item.name == name:
                return item
        return None

    def tasks_for(self, asset_class: str) -> tuple[tuple[TaskConfig, Schedule], ...]:
        out: list[tuple[TaskConfig, Schedule]] = []
        for task in self.tasks:
            schedule = task.schedule_for(asset_class)
            if schedule is not None:
                out.append((task, schedule))
        return tuple(out)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def default_config_bytes() -> bytes:
    return resources.files("nbdf_fleet.resources").joinpath("default_rules.toml").read_bytes()


BUNDLED_SOURCE = "bundled-default"


def load_config(path: Path | None) -> RulesConfig:
    """Load ``path`` or, when ``None``, the bundled default rules.

    Error messages name the full path the user typed; the ``source`` stored
    in the config (and printed in the text, HTML, and JSON outputs) is only
    the base name.
    """
    if path is None:
        raw = default_config_bytes()
        label = source = BUNDLED_SOURCE
    else:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ConfigError(f"cannot read config '{path}': {exc.strerror or exc}") from exc
        label, source = str(path), path.name
    try:
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config '{label}' is not valid UTF-8: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config '{label}' is not valid TOML: {exc}") from exc
    except ValueError as exc:
        # e.g. an integer literal longer than Python's int conversion limit
        raise ConfigError(f"config '{label}' contains a value that cannot be read: {exc}") from exc
    return build_config(data, source, label)


def config_hash(data: dict[str, Any]) -> str:
    """Hash of the parsed configuration (independent of whitespace/comments)."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# Every key the configuration may contain, per table. Anything else is a
# configuration error: a misspelled key must never be silently ignored,
# because an ignored interval or flag changes results without warning.
ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "": frozenset({
        "schema_version", "meta", "thresholds", "validation", "baseline",
        "scoring", "asset_classes", "tasks",
    }),
    "meta": frozenset({"placeholder_intervals"}),
    "thresholds": frozenset({"due_soon_utilization"}),
    "validation": frozenset({
        "max_miles_per_day", "max_engine_hours_per_day", "min_model_year", "max_model_years_ahead",
    }),
    "baseline": frozenset({"assume_in_service_baseline"}),
    "scoring": frozenset({
        "method", "overdue_saturation", "repeat_lookback_months", "repeat_saturation_count",
        "weights", "bands",
    }),
    "scoring.weights": frozenset(WEIGHT_NAMES),
    "scoring.bands": frozenset({"high", "medium"}),
    "asset_classes": frozenset({"name", "description", "primary_meter"}),
    "tasks": frozenset({"name", "aliases", "schedules"}),
    "tasks.schedules": frozenset({"asset_classes", "interval_miles", "interval_hours", "interval_months"}),
}

# Month counts are capped so calendar arithmetic can never leave the
# supported date range (100 years is far beyond any maintenance interval).
MAX_MONTHS = 1200


def _check_keys(table: dict[str, Any], section: str, where: str, fail) -> None:
    allowed = ALLOWED_KEYS[section]
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise fail(
            f"unknown key(s) in {where}: {', '.join(unknown)}; "
            f"allowed keys are: {', '.join(sorted(allowed))}"
        )


def build_config(data: dict[str, Any], source: str, label: str | None = None) -> RulesConfig:
    display = label or source

    def fail(message: str) -> ConfigError:
        return ConfigError(f"config '{display}': {message}")

    _check_keys(data, "", "the top level", fail)

    meta_tbl = data.get("meta", {})
    if not isinstance(meta_tbl, dict):
        raise fail("[meta] must be a table")
    _check_keys(meta_tbl, "meta", "[meta]", fail)
    placeholder = meta_tbl.get("placeholder_intervals", False)
    if not isinstance(placeholder, bool):
        raise fail("meta.placeholder_intervals must be true or false")

    schema_version = data.get("schema_version")
    # bool is a subclass of int in Python (True == 1), so check the type
    # explicitly rather than relying on equality.
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) \
            or schema_version != CONFIG_SCHEMA_VERSION:
        raise fail(
            f"schema_version must be the whole number {CONFIG_SCHEMA_VERSION} (found {schema_version!r})"
        )

    thresholds_tbl = _table(data, "thresholds", fail)
    _check_keys(thresholds_tbl, "thresholds", "[thresholds]", fail)
    due_soon = _fraction(thresholds_tbl, "due_soon_utilization", fail, "thresholds")
    if not (0 < due_soon < 1):
        raise fail("thresholds.due_soon_utilization must be greater than 0 and less than 1")
    thresholds = Thresholds(due_soon_utilization=due_soon)

    validation_tbl = _table(data, "validation", fail)
    _check_keys(validation_tbl, "validation", "[validation]", fail)
    validation = ValidationConfig(
        max_miles_per_day=_positive_decimal(validation_tbl, "max_miles_per_day", fail, "validation"),
        max_engine_hours_per_day=_positive_decimal(
            validation_tbl, "max_engine_hours_per_day", fail, "validation"
        ),
        min_model_year=_int(validation_tbl, "min_model_year", fail, "validation"),
        max_model_years_ahead=_int(validation_tbl, "max_model_years_ahead", fail, "validation"),
    )

    baseline_tbl = data.get("baseline", {})
    if not isinstance(baseline_tbl, dict):
        raise fail("[baseline] must be a table")
    _check_keys(baseline_tbl, "baseline", "[baseline]", fail)
    assume = baseline_tbl.get("assume_in_service_baseline", False)
    if not isinstance(assume, bool):
        raise fail("baseline.assume_in_service_baseline must be true or false")
    baseline = BaselineConfig(assume_in_service_baseline=assume)

    scoring_tbl = _table(data, "scoring", fail)
    _check_keys(scoring_tbl, "scoring", "[scoring]", fail)
    method = scoring_tbl.get("method", "rules")
    if not isinstance(method, str) or not method:
        raise fail("scoring.method must be a non-empty string")
    weights_tbl = _table(scoring_tbl, "weights", fail, "scoring.weights")
    _check_keys(weights_tbl, "scoring.weights", "[scoring.weights]", fail)
    weights: list[tuple[str, Fraction]] = []
    for name in WEIGHT_NAMES:
        value = _fraction(weights_tbl, name, fail, "scoring.weights")
        if value < 0:
            raise fail(f"scoring.weights.{name} must not be negative")
        weights.append((name, value))
    extra = set(weights_tbl) - set(WEIGHT_NAMES)
    if extra:
        raise fail(f"scoring.weights has unknown keys: {', '.join(sorted(extra))}")
    total = sum(w for _, w in weights)
    if total != 1:
        raise fail(
            f"scoring.weights must sum to exactly 1.0 (found {float(total):.6f}); "
            f"weights: {', '.join(f'{k}={float(v)}' for k, v in weights)}"
        )
    bands_tbl = _table(scoring_tbl, "bands", fail, "scoring.bands")
    _check_keys(bands_tbl, "scoring.bands", "[scoring.bands]", fail)
    band_high = _fraction(bands_tbl, "high", fail, "scoring.bands")
    band_medium = _fraction(bands_tbl, "medium", fail, "scoring.bands")
    if not (0 < band_medium < band_high <= 100):
        raise fail("scoring.bands must satisfy 0 < medium < high <= 100")
    overdue_saturation = _fraction(scoring_tbl, "overdue_saturation", fail, "scoring")
    if overdue_saturation <= 0:
        raise fail("scoring.overdue_saturation must be greater than 0")
    lookback = _int(scoring_tbl, "repeat_lookback_months", fail, "scoring")
    saturation = _int(scoring_tbl, "repeat_saturation_count", fail, "scoring")
    if lookback <= 0 or saturation <= 0:
        raise fail("scoring.repeat_lookback_months and repeat_saturation_count must be positive")
    if lookback > MAX_MONTHS:
        raise fail(f"scoring.repeat_lookback_months must be at most {MAX_MONTHS}")
    scoring = ScoringConfig(
        method=method,
        weights=tuple(weights),
        band_high=band_high,
        band_medium=band_medium,
        overdue_saturation=overdue_saturation,
        repeat_lookback_months=lookback,
        repeat_saturation_count=saturation,
    )

    classes_raw = data.get("asset_classes")
    if not isinstance(classes_raw, list) or not classes_raw:
        raise fail("at least one [[asset_classes]] entry is required")
    asset_classes: list[AssetClassConfig] = []
    for index, item in enumerate(classes_raw):
        if not isinstance(item, dict):
            raise fail(f"asset_classes[{index}] must be a table")
        _check_keys(item, "asset_classes", f"asset_classes[{index}]", fail)
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise fail(f"asset_classes[{index}].name must be a non-empty string")
        name = normalize_text(name)
        if any(existing.name == name for existing in asset_classes):
            raise fail(f"asset class '{name}' is defined more than once")
        meter_raw = item.get("primary_meter")
        primary: Meter | None = None
        if meter_raw is not None:
            if meter_raw not in ("miles", "hours"):
                raise fail(f"asset_classes[{index}].primary_meter must be 'miles' or 'hours'")
            primary = Meter(meter_raw)
        description = item.get("description", "")
        if not isinstance(description, str):
            raise fail(f"asset_classes[{index}].description must be a string")
        asset_classes.append(AssetClassConfig(name=name, description=description, primary_meter=primary))
    class_names = {c.name for c in asset_classes}

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise fail("at least one [[tasks]] entry is required")
    tasks: list[TaskConfig] = []
    alias_owner: dict[str, str] = {}
    for index, item in enumerate(tasks_raw):
        if not isinstance(item, dict):
            raise fail(f"tasks[{index}] must be a table")
        _check_keys(item, "tasks", f"tasks[{index}]", fail)
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise fail(f"tasks[{index}].name must be a non-empty string")
        name = name.strip()
        if any(existing.name == name for existing in tasks):
            raise fail(f"task '{name}' is defined more than once")
        aliases_raw = item.get("aliases", [])
        if not isinstance(aliases_raw, list) or not all(isinstance(a, str) for a in aliases_raw):
            raise fail(f"tasks[{index}].aliases must be a list of strings")
        aliases: list[str] = []
        for alias in [name, *aliases_raw]:
            normalized = normalize_text(alias)
            if not normalized:
                raise fail(f"task '{name}' has an empty alias")
            owner = alias_owner.get(normalized)
            if owner is not None and owner != name:
                raise fail(f"alias '{normalized}' is claimed by both '{owner}' and '{name}'")
            alias_owner[normalized] = name
            if normalized not in aliases:
                aliases.append(normalized)
        schedules_raw = item.get("schedules")
        if not isinstance(schedules_raw, list) or not schedules_raw:
            raise fail(f"task '{name}' needs at least one [[tasks.schedules]] entry")
        schedules: list[Schedule] = []
        claimed: set[str] = set()
        for s_index, sched in enumerate(schedules_raw):
            if not isinstance(sched, dict):
                raise fail(f"task '{name}' schedules[{s_index}] must be a table")
            _check_keys(sched, "tasks.schedules", f"task '{name}' schedules[{s_index}]", fail)
            classes = sched.get("asset_classes")
            if not isinstance(classes, list) or not classes or not all(isinstance(c, str) for c in classes):
                raise fail(f"task '{name}' schedules[{s_index}].asset_classes must be a non-empty list")
            normalized_classes = tuple(normalize_text(c) for c in classes)
            for cls in normalized_classes:
                if cls not in class_names:
                    raise fail(f"task '{name}' references undefined asset class '{cls}'")
                if cls in claimed:
                    raise fail(f"task '{name}' lists asset class '{cls}' in more than one schedule")
                claimed.add(cls)
            miles = _optional_positive_decimal(sched, "interval_miles", fail, f"task '{name}'")
            hours = _optional_positive_decimal(sched, "interval_hours", fail, f"task '{name}'")
            months_raw = sched.get("interval_months")
            months: int | None = None
            if months_raw is not None:
                if isinstance(months_raw, bool) or not isinstance(months_raw, int) or months_raw <= 0:
                    raise fail(f"task '{name}' interval_months must be a positive whole number")
                if months_raw > MAX_MONTHS:
                    raise fail(f"task '{name}' interval_months must be at most {MAX_MONTHS} (100 years)")
                months = months_raw
            if miles is None and hours is None and months is None:
                raise fail(
                    f"task '{name}' schedules[{s_index}] needs at least one of "
                    "interval_miles, interval_hours, interval_months"
                )
            schedules.append(Schedule(normalized_classes, miles, hours, months))
        tasks.append(TaskConfig(name=name, aliases=tuple(aliases), schedules=tuple(schedules)))

    return RulesConfig(
        schema_version=schema_version,
        thresholds=thresholds,
        validation=validation,
        scoring=scoring,
        baseline=baseline,
        asset_classes=tuple(asset_classes),
        tasks=tuple(tasks),
        config_hash=config_hash(data),
        source=source,
        placeholder_intervals=placeholder,
    )


# ---------------------------------------------------------------------------
# Small typed accessors
# ---------------------------------------------------------------------------


def _table(parent: dict[str, Any], key: str, fail, label: str | None = None) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise fail(f"[{label or key}] table is required")
    return value


def _number(parent: dict[str, Any], key: str, fail, label: str):
    value = parent.get(key)
    if value is None:
        raise fail(f"{label}.{key} is required")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise fail(f"{label}.{key} must be a number")
    # TOML allows nan and inf; neither is a usable threshold or interval.
    if isinstance(value, float) and not math.isfinite(value):
        raise fail(f"{label}.{key} must be a finite number (found {value})")
    if isinstance(value, int) and value.bit_length() > _MAX_INT_BITS:
        raise fail(f"{label}.{key} is too large")
    return value


# 2**50 is about 1.1e15: far above any interval, limit, or year, and small
# enough to convert to text and float without Python's large-int limits.
_MAX_INT_BITS = 50


def _fraction(parent: dict[str, Any], key: str, fail, label: str) -> Fraction:
    value = _number(parent, key, fail, label)
    # Fraction(str(x)) turns the TOML literal 0.85 into exactly 17/20 rather
    # than the binary approximation, so boundary comparisons are exact.
    return Fraction(str(value))


def _int(parent: dict[str, Any], key: str, fail, label: str) -> int:
    value = parent.get(key)
    if value is None:
        raise fail(f"{label}.{key} is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise fail(f"{label}.{key} must be a whole number")
    if value.bit_length() > _MAX_INT_BITS:
        raise fail(f"{label}.{key} is too large")
    return value


def _positive_decimal(parent: dict[str, Any], key: str, fail, label: str) -> Decimal:
    value = _number(parent, key, fail, label)
    if value <= 0:
        raise fail(f"{label}.{key} must be greater than 0")
    return Decimal(str(value))


def _optional_positive_decimal(parent: dict[str, Any], key: str, fail, label: str) -> Decimal | None:
    if parent.get(key) is None:
        return None
    return _positive_decimal(parent, key, fail, label)
