# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

from datetime import date
from decimal import Decimal

import pytest

from nbdf_fleet.analysis import load_and_validate
from nbdf_fleet.ingest import IngestError, load_services, load_vehicles, normalize_header, read_table
from nbdf_fleet.models import Severity
from tests.conftest import SERVICE_HEADER, VEHICLE_HEADER, write_csv


def codes(findings, severity=None):
    return sorted(f.code for f in findings if severity is None or f.severity is severity)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_bom_and_crlf_are_tolerated(tmp_path):
    path = write_csv(
        tmp_path / "v.csv", VEHICLE_HEADER,
        ["V1,2020,Make,Model,light-duty,Dept,2020-01-01,1000,"], bom=True, crlf=True,
    )
    vehicles, findings = load_vehicles(path)
    assert findings == []
    assert vehicles[0].vehicle_id == "V1"
    assert vehicles[0].row == 2
    assert vehicles[0].current_odometer == Decimal(1000)


def test_header_normalization_is_case_and_whitespace_insensitive():
    assert normalize_header("  Vehicle ID ") == "vehicle_id"
    assert normalize_header("Current-Odometer") == "current_odometer"
    assert normalize_header("﻿vehicle_id") == "vehicle_id"


def test_unknown_column_warns_and_is_ignored(tmp_path):
    path = write_csv(
        tmp_path / "v.csv", VEHICLE_HEADER + ",Color",
        ["V1,2020,Make,Model,light-duty,Dept,2020-01-01,1000,,blue"],
    )
    vehicles, findings = load_vehicles(path)
    assert codes(findings) == ["unknown_column"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].row == 1
    assert len(vehicles) == 1


def test_missing_required_column_is_error(tmp_path):
    path = write_csv(tmp_path / "v.csv", "vehicle_id,year", ["V1,2020"])
    vehicles, findings = load_vehicles(path)
    assert vehicles == []
    assert ("missing_required_column", "asset_class") in [(f.code, f.field) for f in findings]
    assert all(f.severity is Severity.ERROR for f in findings if f.code == "missing_required_column")


def test_missing_optional_column_warns(tmp_path):
    path = write_csv(tmp_path / "s.csv", "vehicle_id,service_date,service_type", ["V1,2026-01-01,Oil"])
    services, findings = load_services(path)
    assert len(services) == 1
    warned = {f.field for f in findings if f.code == "missing_optional_column"}
    assert warned == {"odometer", "engine_hours", "cost"}  # notes and category are silent


def test_empty_file_and_undecodable_file(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_bytes(b"")
    with pytest.raises(IngestError):
        read_table(empty)
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"vehicle_id\n\xff\xfe\n")
    with pytest.raises(IngestError, match="UTF-8"):
        read_table(bad)


def test_blank_lines_are_skipped(tmp_path):
    path = write_csv(tmp_path / "v.csv", VEHICLE_HEADER, ["", "V1,,,,light-duty,,,,", "   ,,,,,,,,"])
    vehicles, findings = load_vehicles(path)
    assert [v.vehicle_id for v in vehicles] == ["V1"]
    assert findings == []


# ---------------------------------------------------------------------------
# Cell parsing
# ---------------------------------------------------------------------------


def test_zero_is_zero_and_blank_is_missing(tmp_path):
    path = write_csv(
        tmp_path / "v.csv", VEHICLE_HEADER,
        ["V1,,,,light-duty,,,0,", "V2,,,,light-duty,,,   ,0.0"],
    )
    vehicles, findings = load_vehicles(path)
    assert findings == []
    assert vehicles[0].current_odometer == Decimal(0)
    assert vehicles[0].current_engine_hours is None
    assert vehicles[1].current_odometer is None
    assert vehicles[1].current_engine_hours == Decimal("0.0")
    assert vehicles[0].year is None and vehicles[0].make is None


def test_malformed_numbers_dates_and_required_fields(tmp_path):
    path = write_csv(
        tmp_path / "v.csv", VEHICLE_HEADER,
        [
            "V1,abc,,,light-duty,,,1000,",           # bad year
            "V2,2020,,,light-duty,,,\"12,345\",",     # thousands separator
            "V3,2020,,,light-duty,,3/5/24,1000,",     # two-digit year
            "V4,2020,,,light-duty,,,-10,",            # negative
            ",2020,,,light-duty,,,10,",               # blank id
            "V6,2020,,,,,,10,",                       # blank asset class
            "V7,2020,,,light-duty,,,10,",             # valid
        ],
    )
    vehicles, findings = load_vehicles(path)
    assert [v.vehicle_id for v in vehicles] == ["V7"]
    by_row = {(f.row, f.field): f for f in findings}
    assert by_row[(2, "year")].code == "invalid_integer"
    assert by_row[(3, "current_odometer")].code == "invalid_number"
    assert "thousands separators" in by_row[(3, "current_odometer")].fix
    assert by_row[(4, "in_service_date")].code == "invalid_date"
    assert "two-digit year" in by_row[(4, "in_service_date")].message
    assert by_row[(5, "current_odometer")].code == "negative_number"
    assert by_row[(6, "vehicle_id")].code == "missing_required_field"
    assert by_row[(7, "asset_class")].code == "missing_required_field"
    assert all(f.severity is Severity.ERROR for f in findings)
    assert all(f.fix for f in findings)


def test_service_parsing_accepts_us_dates_and_normalizes_category(tmp_path):
    path = write_csv(
        tmp_path / "s.csv", SERVICE_HEADER,
        [
            "V1,3/2/2026,OIL & FILTER,100,,10,Preventive,note",
            "V1,2026-03-03,Oil,110,,10,routine,",
            "V1,2026-03-04,,120,,10,,",
            "V1,,Oil,120,,10,,",
        ],
    )
    services, findings = load_services(path)
    assert len(services) == 2
    assert services[0].service_date == date(2026, 3, 2)
    assert services[0].category == "preventive"
    assert services[1].category is None
    assert codes(findings) == ["missing_required_field", "missing_required_field", "unknown_category"]


# ---------------------------------------------------------------------------
# Cross-record validation
# ---------------------------------------------------------------------------


def _fleet(tmp_path, vehicle_rows, service_rows):
    v = write_csv(tmp_path / "vehicles.csv", VEHICLE_HEADER, vehicle_rows)
    s = write_csv(tmp_path / "services.csv", SERVICE_HEADER, service_rows)
    return v, s


def test_duplicate_ids_unknown_vehicle_and_duplicate_service_are_errors(tmp_path, config, as_of):
    v, s = _fleet(
        tmp_path,
        ["V1,,,,light-duty,,,1000,", "V1,,,,light-duty,,,1000,"],
        [
            "V1,2026-01-01,Oil change,500,,10,,",
            "V1,2026-01-01,oil change,500,,10,,",
            "V9,2026-01-01,Oil change,500,,10,,",
        ],
    )
    findings, vehicles, services = load_and_validate(v, s, config, as_of)
    assert codes(findings, Severity.ERROR) == [
        "duplicate_service_record", "duplicate_vehicle_id", "unknown_vehicle",
    ]
    dup = next(f for f in findings if f.code == "duplicate_vehicle_id")
    assert dup.row == 3 and "row 2" in dup.message
    assert len(services) == 1  # duplicate and unknown removed


def test_reading_consistency_warnings(tmp_path, config, as_of):
    v, s = _fleet(
        tmp_path,
        [
            "V1,,,,light-duty,,,20000,",     # current below last service (25000)
            "V2,,,,light-duty,,,90000,",     # implausible jump from 30000 in 29 days
            "V3,,,,light-duty,,,45000,100",  # hours decrease; service->service odometer jump
        ],
        [
            "V1,2026-03-01,Tire rotation,26000,,10,,",
            "V1,2026-05-01,Oil change,25000,,10,,",
            "V2,2026-06-01,Oil change,30000,,10,,",
            "V3,2026-01-01,Oil change,1000,90,10,,",
            "V3,2026-02-01,Oil change,1500,80,10,,",
            "V3,2026-02-02,Oil change,40000,85,10,,",
        ],
    )
    findings, _, _ = load_and_validate(v, s, config, as_of)
    assert codes(findings, Severity.ERROR) == []
    assert codes(findings, Severity.WARNING) == [
        "current_below_last_service_odometer",
        "decreasing_engine_hours",
        "decreasing_odometer",
        "implausible_odometer_jump",
        "implausible_odometer_jump",
    ]
    for f in findings:
        assert f.file and f.row and f.field and f.fix


def test_future_records_and_unknown_class_and_unmapped_type(tmp_path, config, as_of):
    v, s = _fleet(
        tmp_path,
        ["V1,1900,,,light-duty,,2027-01-01,1000,", "V2,,,,boat,,,1000,"],
        [
            "V1,2026-08-15,Oil change,900,,10,,",
            "V1,2026-01-15,Wiper blades,800,,10,,",
            "V1,2026-01-16,wiper blades,800,,10,,",
        ],
    )
    findings, _, services = load_and_validate(v, s, config, as_of)
    assert codes(findings, Severity.ERROR) == []
    assert codes(findings, Severity.WARNING) == [
        "future_in_service_date",
        "future_service_date",
        "implausible_year",
        "service_before_in_service",
        "service_before_in_service",
        "unknown_asset_class",
        "unmapped_service_type",
    ]
    assert [r.row for r in services] == [3, 4]  # future-dated row 2 excluded


def test_example_invalid_set_has_expected_findings(invalid_examples, config, as_of):
    findings, _, _ = load_and_validate(
        invalid_examples / "vehicles_invalid.csv",
        invalid_examples / "service_history_invalid.csv",
        config, as_of,
    )
    errors = codes(findings, Severity.ERROR)
    warnings = codes(findings, Severity.WARNING)
    assert errors == [
        "duplicate_service_record", "duplicate_vehicle_id", "invalid_date", "invalid_date",
        "invalid_integer", "invalid_number", "missing_required_field", "missing_required_field",
        "negative_number", "unknown_vehicle",
    ]
    assert "unknown_column" in warnings and "implausible_odometer_jump" in warnings
    assert "future_service_date" in warnings and "decreasing_odometer" in warnings
