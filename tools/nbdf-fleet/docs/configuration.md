# Configuration (TOML)

The rules file is read with the standard-library `tomllib`. The bundled
default is [`config/default_rules.toml`](../config/default_rules.toml); copy
it and pass your copy with `--config`. Every setting is validated at load
time and an invalid file stops the run with exit code 2 and a message naming
the offending key.

Validation is strict:

- **Unknown keys are errors** in every table, including the top level, each
  `[[asset_classes]]` and `[[tasks]]` entry, and each `[[tasks.schedules]]`
  block. A misspelled key (for example `interval_month` or
  `placeholder_interval`) stops the run and lists the allowed keys; it is
  never silently ignored, because an ignored interval or flag would change
  results without warning.
- **Types are exact.** Whole-number fields (`schema_version`,
  `interval_months`, `min_model_year`, the repeat settings) reject `true` and
  `false` and decimals such as `6.0`; number fields reject booleans.
- **Numbers must be finite and sane.** `nan` and `inf` (legal TOML) are
  rejected, integers above about 10^15 are rejected, and month counts
  (`interval_months`, `repeat_lookback_months`) are capped at 1200 (100
  years) so calendar arithmetic cannot leave the supported date range.

The terminal report, the HTML report, and the JSON metadata record a
**config hash**: a SHA-256 prefix of the parsed configuration (whitespace
and comments do not change it; any value does). The flat CSV tables do not
carry it; see [scoring-method.md](scoring-method.md), section 5.

## Sections

### `schema_version = 1`
Must be exactly `1` for this tool version.

### `[meta]`
| Key | Meaning |
|---|---|
| `placeholder_intervals` | `true` in the bundled default and in every config written by `nbdf-fleet init`. While true, the terminal and HTML reports show the banner "PLACEHOLDER CONFIG: Placeholder maintenance intervals in use - not agency or manufacturer schedules. Results are illustrative only." and JSON metadata carries `"placeholder_config": true` plus the banner text. CSV exports are flat tables and carry no banner. Set it to `false`, or delete the `[meta]` table, once the intervals are your own and have been reviewed. The flag never affects scores. |

### `[thresholds]`
| Key | Meaning |
|---|---|
| `due_soon_utilization` | Utilization at or above which a criterion is DUE SOON (below 1.0). Must be between 0 and 1. Default 0.85. |

### `[validation]`
| Key | Meaning |
|---|---|
| `max_miles_per_day` | Implausible-jump limit for odometers. |
| `max_engine_hours_per_day` | Implausible-jump limit for engine hours. |
| `min_model_year` | Earliest plausible model year. |
| `max_model_years_ahead` | Latest plausible model year is as-of year plus this. |

### `[baseline]`
| Key | Meaning |
|---|---|
| `assume_in_service_baseline` | `false` (default): a task with no service record is INSUFFICIENT DATA. `true`: the in-service date with zero miles and hours is used as the last service, and every dependent result is labeled ASSUMED BASELINE. |

### `[scoring]`
| Key | Meaning |
|---|---|
| `method` | Scorer to use. Only `"rules"` exists. |
| `overdue_saturation` | Excess utilization (utilization minus 1) at which the overdue component reaches 1.0. |
| `repeat_lookback_months` | Window for counting corrective records. |
| `repeat_saturation_count` | Corrective count at which the repeat component reaches 1.0. |

### `[scoring.weights]`
Five keys, all required, must sum to exactly 1.0:
`governing_utilization`, `overdue_magnitude`, `additional_pressure`,
`repeat_maintenance`, `data_completeness`. See
[scoring-method.md](scoring-method.md).

### `[scoring.bands]`
`high` and `medium` score thresholds, `0 < medium < high <= 100`. Bands are
assigned from the score rounded to one decimal place.

### `[[asset_classes]]`
| Key | Meaning |
|---|---|
| `name` | Class name vehicles use (matched case-insensitively). |
| `description` | Free text. |
| `primary_meter` | `"miles"` or `"hours"`, informational only. |

### `[[tasks]]`
| Key | Meaning |
|---|---|
| `name` | Display name; also matched as a service type. Unique. |
| `aliases` | Other `service_type` spellings meaning this task. Matching is case- and whitespace-insensitive. An alias may belong to only one task. |
| `[[tasks.schedules]]` | One or more. Each names `asset_classes` (must be defined above; a class may appear in only one schedule per task) and any subset of `interval_miles`, `interval_hours` (decimal), `interval_months` (whole number). At least one interval is required. |

## Example: adding an hour-based task

```toml
[[tasks]]
name = "Air filter"
aliases = ["air filter", "air cleaner"]

  [[tasks.schedules]]
  asset_classes = ["off-road-equipment"]
  interval_hours = 500

  [[tasks.schedules]]
  asset_classes = ["heavy-duty"]
  interval_miles = 15000
  interval_months = 12
```

No source change is needed.
