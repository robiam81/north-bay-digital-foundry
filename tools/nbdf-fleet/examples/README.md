# Synthetic example data

**Everything in this directory is synthetic.** The vehicles, makes, models,
departments, dates, readings, and costs are invented by North Bay Digital
Foundry to exercise the tool. They do not describe any real fleet, agency, or
person and are unsuitable for any operational fleet decision.

All files are UTF-8 CSV. The demo as-of date is **2026-06-30**; use
`--as-of 2026-06-30` to reproduce the `demo` command's output exactly.

| File | Purpose |
|---|---|
| `demo_vehicles.csv` | 13 vehicles across four configured asset classes plus one unconfigured class (`trailer`). |
| `demo_service_history.csv` | Matching service history with preventive/corrective categories, one M/D/YYYY date, and one unmapped service type. |
| `invalid/vehicles_invalid.csv` | Header spacing/casing variants, an unknown column, a duplicate ID, bad numbers, a two-digit year, a blank ID, an unknown asset class. |
| `invalid/service_history_invalid.csv` | Duplicate record, unknown vehicle, decreasing odometer, implausible jump, future date, blank type, impossible date, bad category, unmapped type, negative reading. |

## Intentional warnings in the clean set

The demo runs with **no errors and exactly two warnings**, both deliberate
demonstrations of warning behavior:

- `unknown_asset_class` for TR-501 (`trailer` has no rules in the default
  config), and
- `unmapped_service_type` for "Track tension check" on OR-303 (a preventive
  record whose type matches no task alias).

The seven corrective repairs in the history (starter, alternator, hydraulic
and broom-motor replacements, and so on) are listed as unmapped in the
results but do not warn, because records categorized `corrective` are
unscheduled work and are not expected to match a scheduled task.

## Boundary values are deliberate

Several readings were chosen to land exactly on classification boundaries
so the semantics can be verified by eye: MD-401's engine oil is exactly
4250 of 5000 miles (utilization 0.85, the DUE SOON boundary) and LD-103's
tire rotation is exactly 7500 of 7500 miles (utilization 1.0, the OVERDUE
boundary). See `docs/scoring-method.md` for the boundary rules.

## What the clean set demonstrates (as of 2026-06-30)

| Vehicle | Designed to show |
|---|---|
| LD-101 | Everything CURRENT. |
| LD-102 | DUE SOON on engine-oil miles (4400 of 5000 = 0.88). |
| LD-103 | OVERDUE on several tasks; tire rotation at exactly 1.0 utilization (7500 of 7500) is OVERDUE; one corrective record. |
| LD-104 | No service history at all: INSUFFICIENT DATA, no baseline assumed. |
| LD-105 | Current odometer missing: mileage criteria are INSUFFICIENT DATA while time criteria still evaluate. |
| HD-201 | Heavy-duty, miles and engine hours, CURRENT. |
| HD-202 | OVERDUE by engine hours only (miles are fine); two corrective repairs whose service types are unmapped. |
| HD-203 | Repeated corrective maintenance (four corrective records in twelve months) while every scheduled task is CURRENT. |
| OR-301 | Hour-based equipment with no odometer, CURRENT. |
| OR-302 | OVERDUE by calendar time even though engine hours are low. |
| OR-303 | Hydraulic service never recorded (INSUFFICIENT DATA for that task) and an unmapped service type. |
| MD-401 | Engine oil at exactly 0.85 utilization (4250 of 5000): the boundary is DUE SOON. |
| TR-501 | Asset class with no configured rules: WARNING and INSUFFICIENT DATA. |

## Running the invalid set

```powershell
.\.venv\Scripts\nbdf-fleet.exe validate examples\invalid\vehicles_invalid.csv examples\invalid\service_history_invalid.csv --as-of 2026-06-30
```

Exit code 1 with a list of ERROR and WARNING findings, each with file, row,
field, and a suggested fix.
