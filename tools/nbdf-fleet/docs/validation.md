# Validation findings

Every finding carries: severity, a stable `code`, the file, the row (header
is row 1), the field, a message, a suggested fix, and the vehicle ID when
known. `validate` lists all of them; `analyze`, `explain`, and `report` list
warnings with the results and stop with exit code 1 when errors exist.

## Severity policy

**ERROR** blocks analysis. Used when a record's identity or a governing
quantity is unusable, so any analysis built on it would be misleading rather
than merely incomplete.

**WARNING** lets analysis proceed. Used when data is inconsistent or
incomplete in a way the tool can carry through and show: the affected
criterion becomes INSUFFICIENT DATA, the record is excluded, or the
inconsistency is simply reported. Warnings alone never change the exit code.

## Catalogue

| Code | Severity | Trigger | Why this severity |
|---|---|---|---|
| `missing_required_column` | ERROR | `vehicle_id`/`asset_class` (vehicles) or `vehicle_id`/`service_date`/`service_type` (services) absent from the header | Nothing can be matched or scheduled without them. |
| `duplicate_column` | ERROR | Same normalized header twice | Ambiguous which value is meant. |
| `missing_optional_column` | WARNING | A known non-required column is absent | Treated as missing for every row; user should know. |
| `unknown_column` | WARNING | Header not in the schema | Ignored; often a typo of a real column. |
| `missing_required_field` | ERROR | Required cell blank | The row cannot be attributed or scheduled. |
| `invalid_integer` / `invalid_number` | ERROR | Cell is not a plain number | Cannot be used; the fix explains separators and symbols. |
| `wrong_field_count` | ERROR | A data row has more or fewer fields than the header | The values would shift into the wrong columns (for example `10,000` splitting into odometer 10 and hours 0). The row is not read. |
| `malformed_csv` | ERROR | Broken quoting (unclosed quote, text after a closing quote) or a field over 131,072 characters | The parser cannot tell where rows start; nothing from that row on is read. |
| `negative_number` | ERROR | Reading or cost below zero | Physically impossible; likely a data-entry error. |
| `number_out_of_range` | ERROR | More than 12 whole digits or 6 decimal places in a reading or cost, or more than 4 digits in a model year | Outside exact decimal arithmetic and any real meter; almost always a paste or export error. |
| `invalid_date` | ERROR | Unparseable, ambiguous (two-digit year), or impossible date | Time-based rules depend on it. |
| `unknown_category` | WARNING | `category` is not preventive/corrective | Treated as missing; the repeat signal just loses that row. |
| `duplicate_vehicle_id` | ERROR | Same ID on two rows | Identity is ambiguous; service history cannot be attributed. |
| `duplicate_service_record` | ERROR | Same vehicle, date, service type, readings, and cost as an earlier row (notes and category are not compared) | Almost always an export defect; would double-count. Fix by removing the row, or by correcting the date, readings, or cost on the row entered wrong. |
| `date_out_of_range` | ERROR | A service date (or, with the baseline assumption on, an in-service date) plus the longest configured month interval would fall after 9999-12-31 | The due date cannot be represented; a year that far ahead is a typo. |
| `unknown_vehicle` | ERROR | Service references an ID not in the inventory | Likely an ID mismatch that would otherwise hide overdue work. |
| `future_service_date` | WARNING | Service dated after the as-of date | Excluded from this analysis; legitimate when analyzing a past as-of date. |
| `future_in_service_date` | WARNING | In-service date after as-of | Reported; vehicle is evaluated on whatever history exists. |
| `service_before_in_service` | WARNING | Service predates the in-service date | One of the two dates is wrong; the tool cannot tell which. |
| `implausible_year` | WARNING | Model year outside `[min_model_year, as-of year + max_model_years_ahead]` | Informational; year is not used by rules. |
| `unknown_asset_class` | WARNING | Class not in config | Vehicle gets INSUFFICIENT DATA and surfaces in the results. |
| `no_data_rows` | WARNING | The header is valid but the file has no data rows (for example a fresh `init` template) | Schema checks pass; `analyze`, `explain`, and `report` exit 1 with "nothing to analyze" when the *inventory* is empty. An empty service history with vehicles still analyzes (everything INSUFFICIENT DATA). |
| `unmapped_service_type` | WARNING | Service type matches no alias (one per distinct type), unless the record's `category` is `corrective` | Excluded from rules but listed in results; usually needs an alias added. Corrective repairs are unscheduled work and are not expected to match a task, so they do not warn. |
| `decreasing_odometer` / `decreasing_engine_hours` | WARNING | A later service has a lower reading than an earlier one | One reading is wrong; rules use the latest service by date and the gap is visible. |
| `current_below_last_service_odometer` / `..._engine_hours` | WARNING | Inventory reading below the latest service reading | The affected criterion becomes INSUFFICIENT DATA rather than "negative elapsed". |
| `implausible_odometer_jump` / `implausible_engine_hours_jump` | WARNING | Increase exceeds `max_*_per_day` x elapsed days (minimum 1 day), service-to-service or latest-service-to-current | Cannot prove which reading is wrong; flagged for review. |

## Ordering

Findings are sorted: errors first, then by file, row, field, code, and
message. This ordering is stable across runs.
