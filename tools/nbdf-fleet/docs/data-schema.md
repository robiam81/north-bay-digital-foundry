# Input data schema

Two CSV files, UTF-8 (a BOM is tolerated), LF or CRLF line endings. U.S.
customary units: miles, engine hours as decimals, USD.

Header names are matched case-insensitively after trimming whitespace and
turning spaces or hyphens into underscores, so `Vehicle ID`, `vehicle_id`,
and `VEHICLE-ID` are all the same column. Unknown columns produce a WARNING
and are ignored. Row numbers in findings count the header as row 1, matching
what a spreadsheet shows.

`nbdf-fleet init` writes header-only templates for both files. The headers
are generated from the same column tuples the parser uses, so they always
list every known column in canonical order. A header-only file validates
with a `no_data_rows` warning.

## Vehicle inventory

| Column | Required | Type | Notes |
|---|---|---|---|
| `vehicle_id` | yes | text | Unique. Duplicates are an ERROR. |
| `year` | no | whole number | Model year; implausible values warn. |
| `make` | no | text | |
| `model` | no | text | |
| `asset_class` | yes | text | Must match a class in the rules config (case-insensitive). Unknown classes warn and get INSUFFICIENT DATA. |
| `department` | no | text | Operating group. |
| `in_service_date` | no | date | Used only when the in-service baseline assumption is enabled. |
| `current_odometer` | no | decimal >= 0 | Miles as of the as-of date. Blank means unknown. |
| `current_engine_hours` | no | decimal >= 0 | Hours as of the as-of date. Blank means unknown. |

## Service history

| Column | Required | Type | Notes |
|---|---|---|---|
| `vehicle_id` | yes | text | Must exist in the inventory (ERROR otherwise). |
| `service_date` | yes | date | Records after the as-of date warn and are excluded. |
| `service_type` | yes | text | Matched to a task through configured aliases (case- and space-insensitive). Unmatched types warn and are excluded from rules but listed in results. |
| `odometer` | no | decimal >= 0 | Reading at service. |
| `engine_hours` | no | decimal >= 0 | Reading at service. |
| `cost` | no | decimal >= 0 | USD. Not used by the rules; carried for completeness. |
| `category` | no | `preventive` or `corrective` | Optional. Enables the repeated-maintenance signal. Other values warn and are treated as missing. Absence of the column is silent. |
| `notes` | no | text | Free text. Absence of the column is silent. |

### Why `category` exists

The task asked for repeated-maintenance signals "where the data supports
them". Service types alone cannot distinguish a scheduled brake service from
an unscheduled brake repair, and inferring intent from free-text notes would
be guesswork. An explicit optional `preventive`/`corrective` flag is the
smallest honest addition: when it is present the tool counts corrective
records in a lookback window; when it is absent the signal is reported as
not computed rather than silently zero.

## Parsing rules

- **Missing vs zero.** An empty or whitespace-only cell is MISSING and is
  represented as `None` in the domain model. `0` is a real zero. Missing is
  never coerced to zero and never treated as evidence that a task is current.
- **CSV structure is strict.** Every data row must have exactly as many
  fields as the header. A row with more or fewer fields is an ERROR
  (`wrong_field_count`) naming the file and row, and none of its values are
  used; the usual cause is an unquoted comma inside a value such as
  `10,000`. Quoting defects (a quote that is never closed, or text after a
  closing quote) and fields longer than 131,072 characters are an ERROR
  (`malformed_csv`), and nothing after that row is read, because the parser
  cannot reliably tell where the next row starts. Legitimate quoting still
  works: `"Smith, Jones"`, doubled quotes (`""`), and quoted values that
  span lines (reported at the row where they start).
- **Numbers.** Plain decimals only: `12345`, `12345.5`, `0`. Thousands
  separators (`12,345`), currency symbols, and text are ERRORs with a fix that
  says so. Negative readings and costs are ERRORs. Readings and costs may
  have at most 12 digits before the decimal point and 6 after it; model
  years at most 4 digits. Longer values are an ERROR
  (`number_out_of_range`). The limits keep every value exact in the tool's
  decimal arithmetic (so a boundary like 0.85 is never crossed by rounding)
  and are far beyond any real meter reading.
- **Dates.** `YYYY-MM-DD` (preferred) or `M/D/YYYY` / `MM/DD/YYYY`. Two-digit
  years (`3/5/24`), `YYYY/MM/DD`, day-first forms, and date-times are rejected
  with a message naming the accepted forms. Impossible calendar dates are
  rejected.
- **Text.** Trimmed. Vehicle IDs are compared exactly (case-sensitive) for
  identity; service types and asset classes are normalized to lower case with
  collapsed whitespace for matching.
- **Blank lines** are skipped silently.

## Duplicate service records

Two service rows are duplicates when vehicle, date, normalized service type,
odometer, engine hours, and cost are all equal. That is an ERROR: it is
almost always an export defect, and keeping both would double-count
corrective work. Notes and category are not part of the comparison, so two
rows that differ only in their notes are still duplicates. If both services
really happened, correct the date, readings, or cost on the row that was
entered wrong.
