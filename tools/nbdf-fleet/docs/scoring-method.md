# Classification and scoring method

This document is the specification of the rules-based MVP. Everything here
is deterministic and reproducible: the same inputs, configuration, and as-of
date give byte-identical CSV and JSON.

**This is a planning heuristic.** It orders vehicles for human review. It
has not been validated against maintenance outcomes and produces no
probabilities, forecasts, or cost estimates.

## 1. Per-criterion classification

A task's schedule for a vehicle's asset class defines up to three criteria:
miles, engine hours, and calendar months. For each criterion:

```
utilization = elapsed / interval
```

| Criterion | elapsed | interval |
|---|---|---|
| miles | current odometer minus odometer at last service | `interval_miles` |
| hours | current engine hours minus hours at last service | `interval_hours` |
| months | days from last service date to the as-of date | days from last service date to (last service date + `interval_months` calendar months, day clamped to month end) |

Classification, with `T = thresholds.due_soon_utilization` (default 0.85):

| Utilization | Status |
|---|---|
| `u < T` | CURRENT |
| `T <= u < 1` | DUE SOON |
| `u >= 1` | OVERDUE |

**Exact boundaries.** A utilization exactly equal to `T` is DUE SOON. A
utilization exactly equal to 1.0 is OVERDUE. Arithmetic uses Python
`Fraction` over `Decimal` inputs, so 4250/5000 against 0.85 is an exact
equality, not a floating-point coincidence. For the months criterion, an
as-of date equal to the calendar due date is exactly 1.0.

**Last service** for a task is the matching record with the latest date;
ties are broken by the highest odometer, then the later row.

### Month arithmetic, precisely

- The due date is `last service date + interval_months` calendar months with
  the day of month clamped to the end of the target month:
  2026-01-31 + 1 month = 2026-02-28; 2024-01-31 + 1 month = 2024-02-29;
  2024-02-29 + 12 months = 2025-02-28; 2025-08-31 + 6 months = 2026-02-28.
- `interval_basis` is the number of calendar days from the last service date
  to that due date, so a "6-month" interval is 181 to 184 days depending on
  the start date, and leap days count when they fall inside it.
- `elapsed` is calendar days from the last service date to the as-of date.
  Partial months are therefore fractional: 45 days into a 181-day interval
  is 0.2486, never "1 month of 6".
- Exact boundaries: as-of equal to the due date is exactly 1.0 (OVERDUE);
  the day before is below 1.0 (DUE SOON when above the threshold); as-of
  equal to the last service date is 0.0 (CURRENT).
- Every output format shows the same numbers and units for a time criterion:
  elapsed days against "N days (M-month interval)". `interval` in JSON is the
  configured month count and `interval_basis` is the day count.

## 2. Insufficient data

A criterion is INSUFFICIENT DATA, with a stated reason, when:

- no service record matches the task (and the baseline assumption is off);
- the reading needed was not recorded at the last service;
- the current reading is missing from the inventory;
- the current reading is below the last-service reading.

Missing data is never treated as CURRENT. The severity order used to roll
criteria up to a task, and tasks up to a vehicle, is:

```
OVERDUE > DUE SOON > INSUFFICIENT DATA > CURRENT
```

So evidence that something is due takes precedence over a data gap, and a
data gap takes precedence over evidence that other criteria are current.
Every gap is still listed in the results and raises the score through the
data-completeness component.

**Baseline assumption.** With `baseline.assume_in_service_baseline = true`,
a task with no history uses the in-service date and zero readings as its
last service. The task result is flagged `assumed_baseline` and the
explanation says ASSUMED BASELINE. It is off by default.

## 3. Vehicle status and governing task

The vehicle status is the most severe task status. The governing task is the
task with that status and the highest utilization (ties: earlier task in the
configuration). Its governing criterion, the meter that triggered it, and the
exact elapsed/interval values are reported everywhere the status appears.

## 4. Score

```
score = 100 x sum(weight_i x component_i)      each component in [0, 1]
```

Weights come from `[scoring.weights]` and must sum to 1.0. Defaults in
parentheses.

| Component | Value | What it captures |
|---|---|---|
| `governing_utilization` (0.30) | `min(1, u_max)` where `u_max` is the highest utilization across all evaluated criteria; 0 if none | How close the most-due task is |
| `overdue_magnitude` (0.25) | `min(1, (u_max - 1) / overdue_saturation)` if `u_max > 1`, else 0 | How far past due |
| `additional_pressure` (0.10) | share of the *other* evaluated criteria that are DUE SOON or OVERDUE; 0 if there are none | Stacking of due work |
| `repeat_maintenance` (0.10) | `min(1, corrective records in lookback window / repeat_saturation_count)`; 0 and noted when the history has no category data | Repeated corrective work |
| `data_completeness` (0.25) | share of the vehicle's criteria that are INSUFFICIENT DATA; 1.0 when no rules apply at all | Incomplete records surface rather than sink |

Priority bands from `[scoring.bands]` use the score rounded to one decimal:
`>= high` is HIGH, `>= medium` is MEDIUM, otherwise LOW (defaults 50 / 25).

**What data gaps can and cannot do.** The data-completeness component adds
at most its configured weight: 25 points with the defaults. A vehicle with
no usable history at all scores exactly 25.0, lands in the MEDIUM band, and
is reported as INSUFFICIENT DATA, but data gaps alone can never reach the
HIGH band. That is deliberate: a gap is a reason to review the record, not
evidence of a due condition. Reviewers should work the "vehicles with data
gaps" count and the per-vehicle gap list directly rather than relying on the
score to promote them.

Ranking is by score descending, then vehicle ID ascending. Rank numbers are
assigned after that sort.

### Worked reference points (default weights)

| Situation | Score |
|---|---|
| Every criterion current at utilization 0.5 | 15.0 |
| One task at exactly its interval, nothing else due | 30.0 |
| One task at twice its interval, nothing else due | 55.0 |
| No usable data at all | 25.0 |
| Unconfigured asset class | 25.0 |

The explanation output lists every component's weight, value, points, the
inputs behind it, and a sentence saying why.

## 5. Safeguards against overstating

- No component is described as a probability, risk, or prediction anywhere
  in code, output, or docs.
- The heuristic disclaimer, the placeholder banner (when the config sets the
  flag), and the provenance metadata (as-of date, tool and schema versions,
  scoring method id, config source and hash) appear in the terminal report,
  the HTML report, and the JSON export, so those results can be traced to the
  exact rules that produced them.
- They are deliberately **not in the flat CSV tables** (`fleet_analysis.csv`,
  `findings.csv`). The CSV files are one row per vehicle or finding so they
  load cleanly into a spreadsheet or database; adding a disclaimer row or
  repeating metadata on every row would break that. This is an intentional
  design choice, not an oversight. A CSV file on its own therefore does not
  say which rules, date, or version produced it: keep it with the
  `fleet_analysis.json` written beside it by `analyze --output-dir` (or the
  terminal or HTML report) whenever that context matters, and do not
  circulate the CSV alone as a finished result.
- The scorer is selected by `scoring.method`; only `"rules"` exists.
  Requesting anything else is a configuration error, not a fallback.
- Weights must sum to 1.0 exactly so a score cannot exceed 100 or be
  silently rescaled.

## 6. Limitations

- Intervals, thresholds, weights, and bands are placeholders until replaced
  with a real maintenance program. Their calibration is a human task.
- Utilization is linear in elapsed use; the method has no notion of usage
  rate, duty cycle, age, or environment.
- Ranking sorts on the exact (unrounded) score, then vehicle ID. Two
  vehicles can both display 15.0 while one ranks above the other because
  its exact score is 15.003; vehicle ID only breaks exact ties. Bands use
  the score rounded to one decimal.
- A wrong-but-plausible reading passes validation and drives the result.
- The repeat signal counts corrective records only; it cannot see repeated
  failures described only in notes.
