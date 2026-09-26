# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""CSV ingestion: read files, normalize headers, parse cells into models.

Row-level problems become :class:`Finding` objects rather than exceptions so a
whole file can be reported at once. Cross-record checks (duplicates, unknown
vehicles, reading consistency) live in :mod:`nbdf_fleet.validation`.

Conventions:
  * UTF-8 with or without BOM; CR/LF or LF line endings.
  * Header names are lower-cased, trimmed, and spaces/hyphens become
    underscores, so ``"Vehicle ID"`` matches ``vehicle_id``.
  * An empty or whitespace-only cell is MISSING (``None``). ``0`` is zero.
  * Unknown columns are ignored with a WARNING.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .dates import DateParseError, parse_date
from .models import Finding, ServiceRecord, Severity, Vehicle

VEHICLE_COLUMNS: tuple[str, ...] = (
    "vehicle_id",
    "year",
    "make",
    "model",
    "asset_class",
    "department",
    "in_service_date",
    "current_odometer",
    "current_engine_hours",
)
VEHICLE_REQUIRED_COLUMNS: tuple[str, ...] = ("vehicle_id", "asset_class")

SERVICE_COLUMNS: tuple[str, ...] = (
    "vehicle_id",
    "service_date",
    "service_type",
    "odometer",
    "engine_hours",
    "cost",
    "notes",
    "category",
)
SERVICE_REQUIRED_COLUMNS: tuple[str, ...] = ("vehicle_id", "service_date", "service_type")
# Known columns whose absence is silently acceptable (no warning).
SERVICE_OPTIONAL_COLUMNS: tuple[str, ...] = ("notes", "category")

SERVICE_CATEGORIES: tuple[str, ...] = ("preventive", "corrective")

_NUMBER_RE = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)$")


class IngestError(Exception):
    """A file could not be read at all (missing, undecodable, no header)."""


@dataclass(frozen=True)
class RawTable:
    """A parsed CSV file: normalized header plus rows with line numbers.

    ``problems`` holds structural ERROR findings (wrong field count, broken
    quoting, oversized fields). Rows with a structural problem are never
    included in ``rows``, so their values cannot reach the analysis.
    """

    file: str
    columns: tuple[str, ...]
    rows: tuple[tuple[int, dict[str, str]], ...]  # (line_number, {col: raw})
    problems: tuple[Finding, ...] = ()


# Plain-number input limits. Fleet meters, costs, and intervals never need
# more; the limits keep every value exactly representable in the default
# decimal context (28 significant digits) and in report floats.
MAX_INTEGER_DIGITS = 12
MAX_FRACTION_DIGITS = 6
MAX_YEAR_DIGITS = 4


def normalize_header(name: str) -> str:
    text = name.strip().lstrip("﻿").lower()
    text = re.sub(r"[\s\-]+", "_", text)
    return text


def normalize_text(value: str) -> str:
    """Normalize free text used for matching (service types, categories)."""
    return re.sub(r"\s+", " ", value.strip()).lower()


def read_table(path: Path, display_name: str | None = None) -> RawTable:
    """Read a CSV file into a :class:`RawTable`.

    Tolerates a UTF-8 BOM and CRLF line endings. Raises :class:`IngestError`
    when the file is unreadable or has no header row.
    """
    name = display_name or path.name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise IngestError(f"{name}: cannot read file ({exc.strerror or exc})") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise IngestError(
            f"{name}: file is not valid UTF-8 (byte offset {exc.start}); "
            "save it as UTF-8 (Excel: 'CSV UTF-8')"
        ) from exc

    # strict=True turns quoting defects (an unterminated quote, text after a
    # closing quote) into csv.Error instead of letting the parser guess.
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise IngestError(f"{name}: file is empty; expected a header row") from None
    except csv.Error as exc:
        raise IngestError(f"{name}: header row is not valid CSV ({exc})") from None

    columns = tuple(normalize_header(h) for h in header)
    if not any(columns):
        raise IngestError(f"{name}: header row is blank")
    width = len(columns)

    rows: list[tuple[int, dict[str, str]]] = []
    problems: list[Finding] = []
    last_line = reader.line_num
    while True:
        start_line = last_line + 1
        try:
            values = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            # The parser cannot resynchronize reliably after a quoting error,
            # so nothing after this point is trusted.
            problems.append(_malformed_csv(name, start_line, exc))
            break
        last_line = reader.line_num
        if not values or all(cell.strip() == "" for cell in values):
            continue  # blank line
        if len(values) != width:
            problems.append(_wrong_width(name, start_line, len(values), width))
            continue
        record = {column: values[index] for index, column in enumerate(columns) if column}
        rows.append((start_line, record))
    return RawTable(file=name, columns=columns, rows=tuple(rows), problems=tuple(problems))


def _malformed_csv(file: str, line: int, exc: csv.Error) -> Finding:
    detail = str(exc)
    if "field larger than field limit" in detail:
        message = (
            f"a field starting on this row is longer than {csv.field_size_limit()} "
            "characters; rows from here on were not read"
        )
        fix = "shorten the field; very long text usually means a quote was never closed"
    else:
        message = f"the row is not valid CSV ({detail}); rows from here on were not read"
        fix = (
            "check quoting on this row: a quoted field must end with a closing quote "
            "followed by a comma or the end of the line, and quotes inside a field are doubled (\"\")"
        )
    return Finding(Severity.ERROR, "malformed_csv", file, line, None, message, fix)


def _wrong_width(file: str, line: int, found: int, expected: int) -> Finding:
    more = found > expected
    return Finding(
        Severity.ERROR,
        "wrong_field_count",
        file,
        line,
        None,
        f"row has {found} fields but the header has {expected}; the row was not read",
        (
            "a value probably contains an unquoted comma (for example 10,000): remove the "
            "separator or wrap the value in double quotes"
            if more else
            "add the missing trailing commas so every row has one field per header column"
        ),
    )


def check_columns(
    table: RawTable,
    known: tuple[str, ...],
    required: tuple[str, ...],
    silent_optional: tuple[str, ...] = (),
) -> list[Finding]:
    findings: list[Finding] = []
    present = set(c for c in table.columns if c)
    for column in required:
        if column not in present:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "missing_required_column",
                    table.file,
                    1,
                    column,
                    f"required column '{column}' is missing from the header",
                    f"add a '{column}' column (header names are case-insensitive)",
                )
            )
    for column in known:
        if column not in present and column not in required and column not in silent_optional:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "missing_optional_column",
                    table.file,
                    1,
                    column,
                    f"column '{column}' is absent; it is treated as missing for every row",
                    f"add a '{column}' column if the data is available",
                )
            )
    seen: set[str] = set()
    for column in table.columns:
        if not column:
            continue
        if column in seen:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "duplicate_column",
                    table.file,
                    1,
                    column,
                    f"column '{column}' appears more than once in the header",
                    "remove or rename the duplicate column",
                )
            )
        seen.add(column)
        if column not in known:
            findings.append(
                Finding(
                    Severity.WARNING,
                    "unknown_column",
                    table.file,
                    1,
                    column,
                    f"column '{column}' is not recognized and is ignored",
                    f"remove it or rename it to one of: {', '.join(known)}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Cell parsers. Each returns (value, finding). value is None when missing or
# invalid; finding is None when the cell is acceptable.
# ---------------------------------------------------------------------------


def _cell(record: dict[str, str], column: str) -> str | None:
    raw = record.get(column)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


def _parse_decimal(
    text: str | None,
    *,
    file: str,
    row: int,
    field: str,
    vehicle_id: str | None,
    allow_negative: bool = False,
) -> tuple[Decimal | None, Finding | None]:
    if text is None:
        return None, None
    if not _NUMBER_RE.match(text):
        hint = "remove thousands separators and currency symbols; " if ("," in text or "$" in text) else ""
        shown = text if len(text) <= 40 else text[:37] + "..."
        return None, Finding(
            Severity.ERROR,
            "invalid_number",
            file,
            row,
            field,
            f"'{shown}' is not a number",
            f"{hint}enter a plain decimal number such as 12345 or 12345.5",
            vehicle_id,
        )
    whole, _, fraction = text.lstrip("+-").partition(".")
    whole = whole.lstrip("0")
    if len(whole) > MAX_INTEGER_DIGITS or len(fraction) > MAX_FRACTION_DIGITS:
        shown = text if len(text) <= 40 else text[:37] + "..."
        return None, Finding(
            Severity.ERROR,
            "number_out_of_range",
            file,
            row,
            field,
            f"'{shown}' has more than {MAX_INTEGER_DIGITS} digits before the decimal point "
            f"or more than {MAX_FRACTION_DIGITS} after it",
            f"enter the reading with at most {MAX_INTEGER_DIGITS} whole digits and "
            f"{MAX_FRACTION_DIGITS} decimal places",
            vehicle_id,
        )
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - guarded by the regex
        return None, Finding(
            Severity.ERROR, "invalid_number", file, row, field, f"'{text}' is not a number",
            "enter a plain decimal number", vehicle_id,
        )
    if value < 0 and not allow_negative:
        return None, Finding(
            Severity.ERROR,
            "negative_number",
            file,
            row,
            field,
            f"{field} is negative ({text})",
            "enter zero or a positive value; leave the cell blank if unknown",
            vehicle_id,
        )
    return value, None


def _parse_int(
    text: str | None, *, file: str, row: int, field: str, vehicle_id: str | None
) -> tuple[int | None, Finding | None]:
    if text is None:
        return None, None
    shown = text if len(text) <= 40 else text[:37] + "..."
    if not re.match(r"^[-+]?\d+$", text):
        return None, Finding(
            Severity.ERROR,
            "invalid_integer",
            file,
            row,
            field,
            f"'{shown}' is not a whole number",
            "enter a whole number such as 2019",
            vehicle_id,
        )
    # Only the model year is parsed as an integer; bounding the digit count
    # before int() also avoids Python's huge-integer conversion limit.
    if len(text.lstrip("+-").lstrip("0")) > MAX_YEAR_DIGITS:
        return None, Finding(
            Severity.ERROR,
            "number_out_of_range",
            file,
            row,
            field,
            f"'{shown}' has more than {MAX_YEAR_DIGITS} digits",
            "enter a four-digit model year such as 2019",
            vehicle_id,
        )
    return int(text), None


def _parse_date_cell(
    text: str | None, *, file: str, row: int, field: str, vehicle_id: str | None
) -> tuple:
    if text is None:
        return None, None
    try:
        return parse_date(text), None
    except DateParseError as exc:
        return None, Finding(
            Severity.ERROR,
            "invalid_date",
            file,
            row,
            field,
            str(exc),
            "use YYYY-MM-DD (preferred) or M/D/YYYY with a four-digit year",
            vehicle_id,
        )


# ---------------------------------------------------------------------------
# Table -> models
# ---------------------------------------------------------------------------


def parse_vehicles(table: RawTable) -> tuple[list[Vehicle], list[Finding]]:
    findings = check_columns(table, VEHICLE_COLUMNS, VEHICLE_REQUIRED_COLUMNS)
    if any(f.severity is Severity.ERROR for f in findings):
        return [], findings
    findings.extend(table.problems)
    if not table.rows and not table.problems:
        findings.append(_no_data_rows(table.file, "vehicle"))

    vehicles: list[Vehicle] = []
    file = table.file
    for row, record in table.rows:
        vehicle_id = _cell(record, "vehicle_id")
        if vehicle_id is None:
            findings.append(
                Finding(
                    Severity.ERROR, "missing_required_field", file, row, "vehicle_id",
                    "vehicle_id is blank", "enter the vehicle's unique identifier",
                )
            )
            continue
        asset_class = _cell(record, "asset_class")
        row_findings: list[Finding] = []
        if asset_class is None:
            row_findings.append(
                Finding(
                    Severity.ERROR, "missing_required_field", file, row, "asset_class",
                    "asset_class is blank; maintenance rules are selected by asset class",
                    "enter an asset class that exists in the rules configuration", vehicle_id,
                )
            )

        year, finding = _parse_int(
            _cell(record, "year"), file=file, row=row, field="year", vehicle_id=vehicle_id
        )
        if finding:
            row_findings.append(finding)
        in_service, finding = _parse_date_cell(
            _cell(record, "in_service_date"), file=file, row=row, field="in_service_date",
            vehicle_id=vehicle_id,
        )
        if finding:
            row_findings.append(finding)
        odometer, finding = _parse_decimal(
            _cell(record, "current_odometer"), file=file, row=row, field="current_odometer",
            vehicle_id=vehicle_id,
        )
        if finding:
            row_findings.append(finding)
        hours, finding = _parse_decimal(
            _cell(record, "current_engine_hours"), file=file, row=row,
            field="current_engine_hours", vehicle_id=vehicle_id,
        )
        if finding:
            row_findings.append(finding)

        findings.extend(row_findings)
        if any(f.severity is Severity.ERROR for f in row_findings):
            continue
        vehicles.append(
            Vehicle(
                vehicle_id=vehicle_id,
                row=row,
                asset_class=normalize_text(asset_class or ""),
                year=year,
                make=_cell(record, "make"),
                model=_cell(record, "model"),
                department=_cell(record, "department"),
                in_service_date=in_service,
                current_odometer=odometer,
                current_engine_hours=hours,
            )
        )
    return vehicles, findings


def parse_services(table: RawTable) -> tuple[list[ServiceRecord], list[Finding]]:
    findings = check_columns(
        table, SERVICE_COLUMNS, SERVICE_REQUIRED_COLUMNS, SERVICE_OPTIONAL_COLUMNS
    )
    if any(f.severity is Severity.ERROR for f in findings):
        return [], findings
    findings.extend(table.problems)
    if not table.rows and not table.problems:
        findings.append(_no_data_rows(table.file, "service"))

    services: list[ServiceRecord] = []
    file = table.file
    for row, record in table.rows:
        vehicle_id = _cell(record, "vehicle_id")
        row_findings: list[Finding] = []
        if vehicle_id is None:
            row_findings.append(
                Finding(
                    Severity.ERROR, "missing_required_field", file, row, "vehicle_id",
                    "vehicle_id is blank", "enter the vehicle identifier this service applies to",
                )
            )
        service_type = _cell(record, "service_type")
        if service_type is None:
            row_findings.append(
                Finding(
                    Severity.ERROR, "missing_required_field", file, row, "service_type",
                    "service_type is blank", "enter the service performed (e.g. 'Oil change')",
                    vehicle_id,
                )
            )
        date_text = _cell(record, "service_date")
        if date_text is None:
            row_findings.append(
                Finding(
                    Severity.ERROR, "missing_required_field", file, row, "service_date",
                    "service_date is blank", "enter the service date as YYYY-MM-DD", vehicle_id,
                )
            )
            service_date = None
        else:
            service_date, finding = _parse_date_cell(
                date_text, file=file, row=row, field="service_date", vehicle_id=vehicle_id
            )
            if finding:
                row_findings.append(finding)

        odometer, finding = _parse_decimal(
            _cell(record, "odometer"), file=file, row=row, field="odometer", vehicle_id=vehicle_id
        )
        if finding:
            row_findings.append(finding)
        hours, finding = _parse_decimal(
            _cell(record, "engine_hours"), file=file, row=row, field="engine_hours",
            vehicle_id=vehicle_id,
        )
        if finding:
            row_findings.append(finding)
        cost, finding = _parse_decimal(
            _cell(record, "cost"), file=file, row=row, field="cost", vehicle_id=vehicle_id
        )
        if finding:
            row_findings.append(finding)

        category_raw = _cell(record, "category")
        category: str | None = None
        if category_raw is not None:
            category = normalize_text(category_raw)
            if category not in SERVICE_CATEGORIES:
                row_findings.append(
                    Finding(
                        Severity.WARNING, "unknown_category", file, row, "category",
                        f"category '{category_raw}' is not 'preventive' or 'corrective'; "
                        "treated as missing",
                        "use 'preventive' or 'corrective', or leave blank", vehicle_id,
                    )
                )
                category = None

        findings.extend(row_findings)
        if any(f.severity is Severity.ERROR for f in row_findings):
            continue
        assert vehicle_id is not None and service_type is not None and service_date is not None
        services.append(
            ServiceRecord(
                vehicle_id=vehicle_id,
                row=row,
                service_date=service_date,
                service_type=service_type,
                odometer=odometer,
                engine_hours=hours,
                cost=cost,
                notes=_cell(record, "notes"),
                category=category,
            )
        )
    return services, findings


def _no_data_rows(file: str, kind: str) -> Finding:
    return Finding(
        Severity.WARNING, "no_data_rows", file, 1, None,
        f"the header is valid but the file has no {kind} rows",
        f"add {kind} rows below the header (a template from 'nbdf-fleet init' looks like this)",
    )


def template_header(columns: tuple[str, ...]) -> str:
    """Header line for a CSV template, from the same schema the parser uses."""
    return ",".join(columns) + "\r\n"


def load_vehicles(path: Path) -> tuple[list[Vehicle], list[Finding]]:
    return parse_vehicles(read_table(path))


def load_services(path: Path) -> tuple[list[ServiceRecord], list[Finding]]:
    return parse_services(read_table(path))
