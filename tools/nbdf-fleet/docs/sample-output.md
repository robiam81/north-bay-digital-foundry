# Sample output

All of this comes from the synthetic demo (`nbdf-fleet demo`, as-of
2026-06-30, tool 0.1.0, schema 2). The data is fictional; see
[examples/README.md](../examples/README.md). The wheel-installed and
source-tree runs produce these bytes identically.

## Terminal report (`demo` / `analyze`)

```
====================================================================================================
NBDF Fleet Maintenance CLI v0.1.0 - fleet analysis
====================================================================================================
As-of date:      2026-06-30
Inputs:          demo_vehicles.csv, demo_service_history.csv
Config:          bundled-default (hash e457e7d68d59f399)
Scoring method:  rules (deterministic planning heuristic)
Schema version:  2

DISCLAIMER: Planning heuristic only. Scores are derived from configured maintenance intervals and
data completeness. They are not failure probabilities, not a validated prediction of breakdown, and
not a substitute for inspection, manufacturer guidance, or fleet-manager judgment. Operational use
requires calibration and validation on representative fleet data, subject-matter review, and
continued human oversight.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
PLACEHOLDER CONFIG: Placeholder maintenance intervals in use - not agency or manufacturer schedules.
Results are illustrative only.
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

FLEET SUMMARY
----------------------------------------------------------------------------------------------------
Vehicles analyzed:        13
  OVERDUE                 3
  DUE SOON                2
  INSUFFICIENT DATA       4
  CURRENT                 4
Priority bands:
  HIGH                    1
  MEDIUM                  9
  LOW                     3
Vehicles with data gaps:  4
Service records analyzed: 46
Excluded (future-dated):  0
Validation warnings:      2

VEHICLES (ranked by score, then vehicle ID)
----------------------------------------------------------------------------------------------------
 #  VEHICLE  DEPARTMENT         CLASS               STATUS             SCORE  BAND    GAPS  WARN  GOVERNING TASK / THRESHOLD
--  -------  -----------------  ------------------  -----------------  -----  ------  ----  ----  -----------------------------------------------------------------------------
 1  LD-103   Streets Division   light-duty          OVERDUE             55.8  HIGH       0     0  Engine oil and filter: 7500 of 5000 miles (150%)
 2  HD-202   Water Utility      heavy-duty          OVERDUE             43.7  MEDIUM     0     0  Engine oil and filter: 360 of 300 hours (120%)
 3  OR-302   Parks Maintenance  off-road-equipment  OVERDUE             38.2  MEDIUM     0     0  Engine oil and filter: 411 of 365 days (12-month interval) (113%)
 4  MD-401   Water Utility      medium-duty         DUE SOON            32.2  MEDIUM     0     0  Brake inspection: 343 of 365 days (12-month interval) (94%)
 5  LD-105   Water Utility      light-duty          INSUFFICIENT DATA   29.8  MEDIUM     3     0  Engine oil and filter: miles - current odometer is missing from the inventory
 6  OR-303   Streets Division   off-road-equipment  INSUFFICIENT DATA   28.7  MEDIUM     2     1  Hydraulic system service: hours - no service record matches this task
 7  LD-102   Parks Maintenance  light-duty          DUE SOON            26.4  MEDIUM     0     0  Engine oil and filter: 4400 of 5000 miles (88%)
 8  HD-203   Streets Division   heavy-duty          CURRENT             26.2  MEDIUM     0     0  Brake inspection: 197 of 365 days (12-month interval) (54%)
 9  LD-104   Fleet Pool         light-duty          INSUFFICIENT DATA   25.0  MEDIUM     6     0  Engine oil and filter: miles - no service record matches this task
10  TR-501   Parks Maintenance  trailer             INSUFFICIENT DATA   25.0  MEDIUM     1     1  asset class 'trailer' is not defined in the configuration
11  HD-201   Streets Division   heavy-duty          CURRENT             24.1  LOW        0     0  Brake inspection: 293 of 365 days (12-month interval) (80%)
12  OR-301   Water Utility      off-road-equipment  CURRENT             21.8  LOW        0     0  Annual safety inspection: 265 of 365 days (12-month interval) (73%)
13  LD-101   Streets Division   light-duty          CURRENT             19.7  LOW        0     0  Brake inspection: 240 of 365 days (12-month interval) (66%)

Unmapped service types (excluded from rule evaluation):
  - Alternator replacement
  - Brake air line repair
  - Broom motor replacement
  - Conveyor belt repair
  - Hydraulic leak repair
  - Hydraulic pump replacement
  - Starter replacement
  - Track tension check

Validation warnings (2)
----------------------------------------------------------------------------------------------------
WARNING unmapped_service_type  demo_service_history.csv row 42 [service_type] vehicle OR-303
        ...
WARNING unknown_asset_class  demo_vehicles.csv row 14 [asset_class] vehicle TR-501
        ...
```

Time-based criteria are shown as elapsed days against the calendar-day
length of the interval in the text, HTML, and JSON outputs. The CSV row
carries the governing meter and utilization only.

## Explanation (`explain ... LD-105`)

```
CLASSIFICATION
----------------------------------------------------------------------------------------------------
Vehicle status: INSUFFICIENT DATA
Governing: Engine oil and filter: miles - current odometer is missing from the inventory

  Engine oil and filter: INSUFFICIENT DATA  (last service 2026-04-15, row 17)
    * miles  INSUFFICIENT DATA - current odometer is missing from the inventory
      months CURRENT           elapsed 76 days of 183 days (6-month interval); utilization 0.4153
  Tire rotation and inspection: INSUFFICIENT DATA  (last service 2026-04-15, row 18)
    * miles  INSUFFICIENT DATA - current odometer is missing from the inventory
  Brake inspection: INSUFFICIENT DATA  (last service 2025-12-01, row 15)
    * miles  INSUFFICIENT DATA - current odometer is missing from the inventory
      months CURRENT           elapsed 211 days of 365 days (12-month interval); utilization 0.5781
  Annual safety inspection: CURRENT  (last service 2025-12-01, row 16)
    * months CURRENT           elapsed 211 days of 365 days (12-month interval); utilization 0.5781
  (* = governing criterion within the task)

DATA GAPS (missing data is never treated as low risk)
----------------------------------------------------------------------------------------------------
  - Engine oil and filter / miles: current odometer is missing from the inventory
  - Tire rotation and inspection / miles: current odometer is missing from the inventory
  - Brake inspection / miles: current odometer is missing from the inventory

SCORE
----------------------------------------------------------------------------------------------------
COMPONENT              WEIGHT   VALUE  POINTS
---------------------  ------  ------  ------
governing_utilization    0.30  0.5781   17.34
overdue_magnitude        0.25  0.0000    0.00
additional_pressure      0.10  0.0000    0.00
repeat_maintenance       0.10  0.0000    0.00
data_completeness        0.25  0.5000   12.50
TOTAL                                     29.8   band MEDIUM
```

Each component is then explained in a sentence with its inputs listed.

## Validation (`validate` on the invalid set, exit code 1)

```
Errors:   10
Warnings: 8

Errors (analysis is blocked until these are fixed)
----------------------------------------------------------------------------------------------------
ERROR   duplicate_service_record  service_history_invalid.csv row 3 vehicle LD-101
        exact duplicate of the service record on row 2 (same vehicle, date, type, readings, and
        cost)
        fix: remove the duplicate row; if two services really occurred, add distinguishing notes or
        readings
ERROR   unknown_vehicle  service_history_invalid.csv row 4 [vehicle_id] vehicle ZZ-999
        vehicle_id 'ZZ-999' does not exist in vehicles_invalid.csv
        fix: correct the vehicle_id or add the vehicle to the inventory
...
ERROR   invalid_date  vehicles_invalid.csv row 6 [in_service_date] vehicle LD-902
        '3/5/24' uses a two-digit year, which is ambiguous; use a four-digit year (YYYY-MM-DD or
        M/D/YYYY)
        fix: use YYYY-MM-DD (preferred) or M/D/YYYY with a four-digit year
```

## `init` then `validate` on the empty templates

```
wrote my-fleet\rules.toml
wrote my-fleet\vehicles.csv
wrote my-fleet\service_history.csv

Next steps:
  1. Fill vehicles.csv and service_history.csv ...
  2. Edit rules.toml: replace the PLACEHOLDER intervals with your maintenance
     program, then set [meta] placeholder_intervals = false to clear the banner.
  ...
```

`validate` on the fresh templates exits 0 with two `no_data_rows` warnings;
`analyze` exits 1 with "nothing to analyze: the vehicle file has a valid
header but no vehicle rows".

## CSV export (`fleet_analysis.csv`, first rows)

```
rank,vehicle_id,department,asset_class,year,make,model,status,priority_band,score,governing_task,governing_meter,governing_utilization,current_odometer,current_engine_hours,tasks_overdue,tasks_due_soon,tasks_insufficient_data,tasks_current,data_gap_count,corrective_in_window,unmapped_service_types,service_record_count,warning_count
1,LD-103,Streets Division,light-duty,2017,Northwind,Hauler 150,OVERDUE,HIGH,55.8,Engine oil and filter,miles,1.5,37500,,4,0,0,0,0,1,Starter replacement,5,0
2,HD-202,Water Utility,heavy-duty,2016,Ironpeak,Titan 10-yd Dump,OVERDUE,MEDIUM,43.7,Engine oil and filter,hours,1.2,74900,6120,1,1,0,1,0,2,Alternator replacement; Hydraulic leak repair,5,0
```

`findings.csv` holds every validation finding with the same columns as the
terminal listing. Text fields beginning with `=`, `+`, `-`, or `@` are
prefixed with an apostrophe in CSV exports; numeric columns are written
unchanged. CSV files carry no banner row: check the JSON metadata or the
terminal output for the placeholder flag.

## JSON export (`fleet_analysis.json`, top of the document)

```json
{
  "metadata": {
    "tool": "nbdf-fleet",
    "tool_version": "0.1.0",
    "schema_version": "2",
    "as_of": "2026-06-30",
    "config_hash": "e457e7d68d59f399",
    "config_source": "bundled-default",
    "scoring_method": "rules",
    "vehicle_file": "demo_vehicles.csv",
    "service_file": "demo_service_history.csv",
    "placeholder_config": true,
    "placeholder_banner": "PLACEHOLDER CONFIG: Placeholder maintenance intervals in use - not agency or manufacturer schedules. Results are illustrative only.",
    "disclaimer": "Planning heuristic only. ..."
  },
  "summary": {
    "vehicles": 13,
    "by_status": { "OVERDUE": 3, "DUE_SOON": 2, "INSUFFICIENT_DATA": 4, "CURRENT": 4 },
    "by_priority_band": { "HIGH": 1, "MEDIUM": 9, "LOW": 3 },
    "vehicles_with_data_gaps": 4,
    "service_records_analyzed": 46,
    "service_records_excluded_future_dated": 0,
    "errors": 0,
    "warnings": 2
  },
  "vehicles": [ { "rank": 1, "vehicle_id": "LD-103", ..., "tasks": [...], "score_components": [...] } ],
  "findings": [ ... ]
}
```

The HTML report (`report --format html`) contains the same banner, summary
(including the excluded-record count), ranked table, per-vehicle task and
score tables, and warnings, with inline CSS and no JavaScript.
