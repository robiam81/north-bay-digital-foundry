# Changelog and output schema history

The tool version (`0.1.0`) is single-sourced in `src/nbdf_fleet/__init__.py`.
The output **schema version** is a separate integer string bumped whenever
exported keys, columns, or their meaning change, so consumers of the JSON and
CSV files can detect a format change without parsing the tool version.

## 0.1.0 (prototype), release candidate 2, schema 2

Fixes from an independent peer review of release candidate 1. No scoring
weights, bands, classification boundaries, utilization formula, or month
arithmetic changed; no exported keys or columns changed, so the schema stays
`2`.

Safety fixes:

- **Outputs can no longer overwrite inputs.** Any destination that resolves
  to the vehicle CSV, the service CSV, or the config is refused with exit 2,
  with or without `--force` (equivalent spellings, case, and links included).
- **Malformed CSV is rejected.** Rows with more or fewer fields than the
  header are ERRORs (`wrong_field_count`) naming the file and row, and are
  never read. Quoting defects and oversized fields are ERRORs
  (`malformed_csv`). Previously an unquoted `10,000` shifted a row's values
  and extra fields were silently dropped.
- **Output writing is all-or-nothing.** All destinations are checked before
  any write; each file is written to a temporary name and swapped in only
  after the whole bundle succeeded, with rollback on failure.
- **Configuration is strict.** Unknown keys in any table are errors (a typo
  such as `interval_month` used to remove a criterion silently);
  `schema_version = true` and other booleans in whole-number fields are
  rejected; `nan`/`inf` and oversized numbers are rejected; month counts are
  capped at 1200.
- **Bad values are validation or configuration errors, not internal
  errors.** Oversized numbers in CSV (`number_out_of_range`: at most 12
  whole digits and 6 decimal places), service dates whose due date would
  pass 9999-12-31 (`date_out_of_range`), and an existing file used as an
  output folder now produce exit 1 or 2 with a message.
- The release builder never deletes files it did not create; see README.

Guidance fixes:

- `init` and `demo` print runnable commands, with paths containing spaces
  quoted; the demo points to `init` instead of a source-only `examples/`
  folder and labels its two warnings as intentional.
- The report's `explain` hint and `explain --help` show all three required
  arguments.
- The duplicate-service-record finding no longer suggests adding notes
  (notes are not part of the comparison).

Documentation fixes:

- The disclaimer, placeholder banner, and provenance metadata are documented
  as present in text, HTML, and JSON output and intentionally absent from
  the flat CSV tables.
- This changelog's release-candidate-1 entry is corrected (see below).

## 0.1.0 (prototype), release candidate 1, schema 2

Release-readiness pass over the pass-1 prototype. No scoring weights, bands,
classification semantics, or boundary rules changed.

Output schema changes (schema `1` -> `2`):

- `metadata.config_source` is now the config file's base name or
  `bundled-default`, never a directory path. Outputs are byte-identical
  regardless of where the inputs live.
- `metadata.placeholder_config` (bool) and `metadata.placeholder_banner`
  (string or null) added. The terminal and HTML reports show the banner when
  the config sets `[meta] placeholder_intervals = true`. CSV exports have no
  banner (flat table).
- `summary.service_records_analyzed` and
  `summary.service_records_excluded_future_dated` added; the terminal and
  HTML summaries show the same two numbers.
- `nbdf-fleet --version` prints `nbdf-fleet 0.1.0 (prototype)`.

Behavior changes:

- Time-based criteria now render through one shared helper, as elapsed days
  against "N days (M-month interval)". The ranked-table text already read
  that way in the pass-1 snapshot. What changed in this pass is the `explain`
  criterion line (previously "elapsed 272 days of 6 months = 182 days") and
  the HTML task-table interval cell (previously "6 mo (182 d)"). *Correction:*
  an earlier version of this entry said pass 1 printed "411 of 12 months" in
  the ranked table. That output existed only in an intermediate pass-1 build
  and was already fixed before the pass-1 snapshot was taken.
- Service records categorized `corrective` no longer raise the
  `unmapped_service_type` warning (unscheduled repairs are not expected to
  match a scheduled task). They are still listed as unmapped in results.
- Header-only CSV files produce a `no_data_rows` warning; `analyze`,
  `explain`, and `report` exit 1 with a clear message when the inventory has
  no rows.
- New `init` command writes a config copy and header-only CSV templates.
- MPL-2.0 applied: LICENSE file, source headers, PEP 639 metadata.

## 0.1.0 (pass 1), schema 1

Initial prototype: `demo`, `validate`, `analyze`, `explain`, `report`.
