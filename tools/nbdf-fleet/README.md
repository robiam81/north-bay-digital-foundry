# NBDF Fleet Maintenance CLI

A local, Windows-friendly command-line tool for municipal and public-works
fleet maintenance planning. It reads a vehicle inventory and a service
history (CSV), validates them, applies configurable maintenance-interval
rules, and produces an **explainable maintenance priority score** for every
vehicle.

Status: **prototype (0.1.0), deterministic rules only.** Authored by North
Bay Digital Foundry. Licensed under MPL-2.0 (see [License](#license)).

## What it does, and what it does not claim

It does:

- classify every configured maintenance task per vehicle as CURRENT, DUE SOON,
  OVERDUE, or INSUFFICIENT DATA, by miles, engine hours, and calendar months;
- rank vehicles with a 0-100 score built from five documented components, and
  show every component's inputs and contribution;
- validate the input data thoroughly and report each finding with file, row,
  field, and a suggested fix;
- export CSV, JSON, and a self-contained HTML report, byte-for-byte
  reproducible for the same inputs, configuration, and as-of date, from any
  directory on any machine.

It does **not**:

- predict failures, estimate failure probabilities, or forecast costs;
- contain any statistical or machine-learning model (the architecture leaves a
  seam for a validated one later; see [docs/extending.md](docs/extending.md));
- know your fleet's real maintenance program. The bundled intervals are
  placeholders, and the terminal, HTML, and JSON outputs say so until you
  replace them.

The score is a **planning heuristic** that orders vehicles for human review.
Operational use requires calibration and validation on representative fleet
data, subject-matter review, and continued human oversight. The terminal
report, the HTML report, and the JSON export carry this disclaimer and the
run's provenance (as-of date, versions, config hash). The flat CSV tables
deliberately do not: use them together with the JSON file written beside
them, not on their own.

## Quickstart from a wheel download (Windows PowerShell)

Requires Python 3.12 (tested on 3.12.10). No `Activate.ps1` is needed, so the
execution policy does not matter. Three steps, in the folder where you saved
the download:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\nbdf_fleet-0.1.0-py3-none-any.whl
.\.venv\Scripts\nbdf-fleet.exe demo
```

The wheel has no dependencies, so the install works offline
(`pip install --no-index --no-deps .\nbdf_fleet-0.1.0-py3-none-any.whl` is
equivalent). `python -m nbdf_fleet` runs the same program:

```powershell
.\.venv\Scripts\python.exe -m nbdf_fleet --version
```

prints `nbdf-fleet 0.1.0 (prototype)`.

### Verifying the download

`SHA256SUMS.txt` ships next to the wheel and the source zip. Compare the
hash before installing:

```powershell
Get-FileHash .\nbdf_fleet-0.1.0-py3-none-any.whl -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

The two hex strings must match (case does not matter).

## Using your own data: the `init` workflow

```powershell
# 1. Create a workspace with a rules config and two header-only CSV templates
.\.venv\Scripts\nbdf-fleet.exe init my-fleet

# 2. Fill my-fleet\vehicles.csv and my-fleet\service_history.csv
#    (Excel is fine: save as "CSV UTF-8"; dates YYYY-MM-DD; unknown cells blank)

# 3. Replace the placeholder intervals in my-fleet\rules.toml with your
#    maintenance program, then set  [meta] placeholder_intervals = false

# 4. Check the data, then analyze
.\.venv\Scripts\nbdf-fleet.exe validate my-fleet\vehicles.csv my-fleet\service_history.csv --config my-fleet\rules.toml
.\.venv\Scripts\nbdf-fleet.exe analyze  my-fleet\vehicles.csv my-fleet\service_history.csv --config my-fleet\rules.toml --as-of 2026-06-30 --output-dir my-fleet\out
.\.venv\Scripts\nbdf-fleet.exe explain  my-fleet\vehicles.csv my-fleet\service_history.csv LD-103 --config my-fleet\rules.toml --as-of 2026-06-30
.\.venv\Scripts\nbdf-fleet.exe report   my-fleet\vehicles.csv my-fleet\service_history.csv --config my-fleet\rules.toml --as-of 2026-06-30 --format html --output my-fleet\report.html
```

`init` never overwrites existing files without `--force`. With no directory
argument it creates `.\nbdf-fleet-data`. The template headers come from the
same schema definition the parser uses, so they cannot drift. Header-only
files pass `validate` with a `no_data_rows` warning; `analyze` needs at least
one vehicle row and exits 1 with a clear message otherwise.

### The placeholder banner

The bundled config (and the copy `init` writes) carries
`[meta] placeholder_intervals = true`. While it is true, every terminal and
HTML report shows a banner:

> PLACEHOLDER CONFIG: Placeholder maintenance intervals in use - not agency
> or manufacturer schedules. Results are illustrative only.

and JSON metadata has `"placeholder_config": true`. CSV exports are flat
tables and deliberately carry no banner, disclaimer, or metadata; keep them
with the JSON file written beside them. Once the
intervals have been replaced and reviewed, set the flag to `false` (or delete
the `[meta]` table) and the banner disappears. The flag never changes any
score.

## Working from the source tree

```powershell
cd tools\nbdf-fleet
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\nbdf-fleet.exe demo
```

Sample invocations against the synthetic data:

```powershell
.\.venv\Scripts\nbdf-fleet.exe validate examples\demo_vehicles.csv examples\demo_service_history.csv --as-of 2026-06-30
.\.venv\Scripts\nbdf-fleet.exe validate examples\invalid\vehicles_invalid.csv examples\invalid\service_history_invalid.csv --as-of 2026-06-30
```

## Commands

| Command | Purpose |
|---|---|
| `demo [--output-dir DIR] [--force]` | Runs the bundled synthetic dataset with the as-of date fixed at 2026-06-30. Prints the fleet report and the explanation for the top-ranked vehicle. |
| `init [directory] [--force]` | Writes `rules.toml`, `vehicles.csv`, `service_history.csv` templates and prints next steps. |
| `validate <vehicles> <services>` | Lists every ERROR and WARNING. Exit 1 when errors exist. |
| `analyze <vehicles> <services> [--output-dir DIR] [--force]` | Terminal report. With `--output-dir`, writes `fleet_analysis.csv`, `fleet_analysis.json`, `findings.csv`. |
| `explain <vehicle-file> <service-file> <vehicle-id>` | Plain-language classification per task and criterion plus the score breakdown. |
| `report <vehicles> <services> --format text\|html\|csv\|json [--output PATH] [--force]` | One format to stdout or a file. |

Every data command accepts `--config <toml>` (default: the bundled rules)
and `--as-of YYYY-MM-DD` (default: today; always printed). `--debug` before
the command shows tracebacks on internal errors. Nothing is written to disk
unless an output location is given, and writing is all-or-nothing:

- An output path that resolves to one of the command's own input files (the
  vehicle CSV, the service CSV, or the config) is always refused, even with
  `--force`.
- Existing files are never overwritten without `--force`. Every destination
  is checked before anything is written, so a refused bundle writes nothing.
- Each file is written to a temporary name and moved into place only after
  every file in the bundle was written completely. If anything fails, the
  destination is left exactly as it was.

The terminal, HTML, and JSON outputs record the config's file name (or
`bundled-default`), the input file names, the tool and schema versions, and
a config hash; never a directory path.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. Warnings alone do not change the exit code. |
| 1 | Validation errors found (including malformed CSV rows and out-of-range values), or nothing to analyze (header-only inventory). |
| 2 | Usage, argument, or output error: bad flags, missing file, invalid config, refusing to overwrite an output or any input file, an output that cannot be written. |
| 3 | Unexpected internal error (re-run with `--debug`). |

## Documentation

- [docs/data-schema.md](docs/data-schema.md) - input CSV columns, parsing rules, missing vs zero
- [docs/validation.md](docs/validation.md) - every finding, its severity, and why
- [docs/configuration.md](docs/configuration.md) - the TOML rules file, including the placeholder flag
- [docs/scoring-method.md](docs/scoring-method.md) - classification boundaries, month arithmetic, score components, bands, limitations
- [docs/sample-output.md](docs/sample-output.md) - what the demo prints
- [docs/extending.md](docs/extending.md) - architecture, packaging, and the pathway for a validated predictive model
- [docs/changelog.md](docs/changelog.md) - output schema history
- [examples/README.md](examples/README.md) - the synthetic datasets

## Tests

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
.\.venv\Scripts\python.exe -m pytest
```

`pyproject.toml` disables the pytest cache provider, and the environment
variable prevents `__pycache__` directories, so a test run leaves no
artifacts in the repository. All generated output goes to pytest temporary
directories.

## Building a release

`scripts/build_release.py` stages an explicit allowlist of files into a
temporary directory, builds the wheel there, zips the same files as a source
archive, verifies both (bundled resources, LICENSE, MPL-2.0 metadata, no test
or cache files), and writes `SHA256SUMS.txt`. Run it from a separate venv
that has `build`, `setuptools>=77`, and `wheel`:

```powershell
python scripts\build_release.py --outdir C:\Projects\nbdf-fleet-dist\0.1.0-rc2
```

`--outdir` is the exact release folder and must be outside the git
repository. The script refuses a folder that contains anything other than
its own three artifact names, refuses existing artifacts unless `--replace`
is given, and copies the files in only after a successful build and
verification. It never deletes other files. Release tooling is never a
runtime dependency.

## Privacy and data handling

- Everything runs locally. There are no network calls, telemetry, accounts,
  or services. The tool reads the two CSV files and the config you name, and
  writes only where you tell it to.
- **Do not commit real fleet data to this repository.** The repository root is
  published as a static website, so anything committed here is public. Keep
  real inventories and service histories outside the repository and point the
  CLI at them.
- The bundled and example datasets are synthetic and labeled as such.
- CSV exports neutralize spreadsheet-formula characters in text fields only
  (numeric columns are written unchanged) so a crafted vehicle ID or note
  cannot execute when opened in a spreadsheet; HTML reports escape all
  user-provided text and contain no JavaScript.

## Limitations

- Rules are interval-based only. There is no usage forecasting, no
  seasonality, no parts or labor modeling, and no cost analysis.
- The default intervals, thresholds, weights, and bands are placeholders.
  They must be replaced with your maintenance program before any real use;
  the banner stays until you say so in the config.
- The data-completeness component adds at most its configured weight (25
  points by default). A vehicle with no usable history is surfaced as
  INSUFFICIENT DATA in the MEDIUM band; data gaps alone cannot reach the HIGH
  band, so gaps must be reviewed on their own list, not only by score.
- Odometer and engine-hour readings are trusted as entered after plausibility
  checks; the tool cannot detect a wrong-but-plausible reading.
- Time-based intervals are evaluated in calendar days between the last
  service and its calendar due date (day-of-month clamped at month end), so
  "6 months" is 181 to 184 days depending on the start date.
- The repeated-maintenance signal depends on an optional
  `preventive`/`corrective` category column; without it the signal is
  reported as not computed.
- A task with no service history is INSUFFICIENT DATA, never "current". An
  in-service baseline can be enabled explicitly and is always labeled as an
  assumption.
- Score bands are ordinal buckets of a heuristic, not risk levels.

## License

This project (everything under `tools/nbdf-fleet/`) is licensed under the
Mozilla Public License, version 2.0. The full text is in
[LICENSE](LICENSE); each source and config file carries the MPL-2.0 notice
and an `SPDX-License-Identifier: MPL-2.0` line. The license applies to this
directory only and not to other parts of the surrounding repository.

Note for redistributors: MPL-2.0 is a file-level copyleft. If you ever
distribute a compiled or frozen executable built from this code, you must
tell recipients how to obtain the corresponding source of the MPL-covered
files (for example, a link to the source zip for the same version).

The heuristic disclaimer above is not a license term, but it is part of the
program's output and documentation and should stay with any redistribution.
