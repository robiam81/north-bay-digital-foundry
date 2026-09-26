# Architecture and the pathway to a validated predictive model

## Layout

```
tools/nbdf-fleet/
  LICENSE                   MPL-2.0 text (applies to this directory only)
  pyproject.toml            setuptools src-layout, dynamic version, PEP 639 license, console script
  config/default_rules.toml documented default rules (canonical copy)
  examples/                 synthetic data (canonical copy) + invalid set
  docs/                     this documentation
  scripts/build_release.py  release builder: allowlist staging, wheel, source zip, checks, SHA256SUMS
  tests/                    pytest suite (184 tests at 0.1.0-rc2; run pytest for the current count)
  src/nbdf_fleet/
    __init__.py             version (single source), schema version, disclaimer and banner text
    __main__.py             python -m nbdf_fleet
    cli.py                  argparse commands (incl. init), exit codes, error presentation
    dates.py                date parsing and calendar month arithmetic
    models.py               frozen dataclasses; None == missing
    ingest.py               CSV reading, header normalization, cell parsing -> models + findings
    validation.py           cross-record checks -> findings, usable records
    config.py               TOML loading, validation, config hash
    rules.py                task matching, utilization, classification, governing task
    scoring.py              MaintenanceScorer Protocol, RulesBasedScorer, SCORERS registry
    analysis.py             orchestration: ingest -> validate -> assess -> score -> rank
    output.py               never-overwrite file writer
    reports/                common serialization, text, csv, json, html renderers
    resources/              bundled copies of the default config and demo data
```

Data flows one way: `ingest` -> `validation` -> `rules` -> `scoring` ->
`reports`. `analysis.run_analysis` is the only place that wires them
together, and `cli.py` only parses arguments and picks a renderer.

## Conventions

- The domain layer (`dates`, `models`, `rules`, `scoring`) is pure: no I/O,
  no clock, no randomness. The as-of date is a parameter everywhere.
- Readings are `Decimal`, utilization and weights are `Fraction`, so
  comparisons at boundaries are exact and output is reproducible.
- Missing is `None`, never 0, never an empty string.
- Every sort has an explicit key; ranking is score desc then vehicle ID.
- Renderers build plain dicts through `reports/common.py` so CSV, JSON, and
  HTML agree on names and order. Add a column in `VEHICLE_COLUMNS` and
  `vehicle_row` together, then bump `SCHEMA_VERSION`.

## The scoring seam

```python
class MaintenanceScorer(Protocol):
    method_id: str
    def score(self, assessment: VehicleAssessment) -> ScoreResult: ...
```

`VehicleAssessment` is the complete, already-validated picture of one
vehicle: every task, every criterion with elapsed/interval/utilization,
data gaps, the corrective-record count, and the vehicle record itself.
`ScoreResult` is a 0-100 score, a band, the `method_id`, and a list of
components each carrying weight, value, inputs, and an explanation sentence.
Reports render whatever components a scorer returns; they do not assume the
five rules-based names.

To add a scorer:

1. Implement a class with `method_id` and `score()` in a new module (for
   example `scoring_model.py`). It may load model parameters from a file
   named in the config; add the key under `[scoring]` in `config.py`.
2. Register it in `scoring.SCORERS`.
3. Select it with `[scoring] method = "<method_id>"`.

Ingestion, validation, rules, reporting, and commands do not change. Both
scorers can coexist so results can be compared on the same inputs.

## What "validated" has to mean before that scorer ships

A predictive scorer is only appropriate once all of the following exist and
are documented in this directory:

- a representative, de-identified training and evaluation dataset with
  outcomes actually observed (breakdowns, road calls, unscheduled repairs),
  not synthetic data;
- a written definition of the target and the prediction horizon;
- out-of-sample evaluation with reported calibration and discrimination, and
  a comparison against this rules baseline on the same vehicles;
- review by fleet maintenance subject-matter staff of both the features and
  the failure modes of the model;
- a plan for continued human oversight, periodic re-validation, and rollback
  to the rules scorer.

Until then, the `method_id` stays `"rules"`, the output stays labeled a
heuristic, and no output may be described as a failure probability.

## Packaging notes

- Bundled resources (default config, demo CSVs) are read through
  `importlib.resources`, never `__file__`, so a frozen executable or a
  zipped install can still find them. A test enforces this.
- The version lives only in `nbdf_fleet.__version__`; `pyproject.toml`
  declares it `dynamic`. Bump it there and nowhere else.
- `scripts/build_release.py` builds from a staged allowlist so nothing under
  `.venv`, caches, or egg-info can reach the wheel or the source zip, and the
  repository is left untouched. It verifies the artifacts and writes
  `SHA256SUMS.txt`. `--outdir` is the exact release folder, outside the git
  repository; the script refuses a folder holding anything but its own three
  artifact names, needs `--replace` to overwrite those, and never deletes
  other files.
- `nbdf_fleet.output.write_outputs` is the only way the CLI writes files.
  New commands that write output must pass their input paths as
  `protected` so an output can never replace an input.
- If a compiled executable is ever produced, MPL-2.0 requires telling
  recipients how to get the corresponding source (see README, License).

## Other likely extensions

- More validation checks: add a function in `validation.py` that appends
  `Finding` objects; document the code and severity in
  [validation.md](validation.md).
- Additional meters (for example kilometers or cycles): extend `Meter`,
  `Schedule.intervals()`, and `rules._assess_task`.
- Additional output formats: add a renderer under `reports/` that consumes
  `AnalysisResult`, and register it in `reports.FORMATS` and `cli.cmd_report`.
