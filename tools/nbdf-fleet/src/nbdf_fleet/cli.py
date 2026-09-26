# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Command-line interface for ``nbdf-fleet``.

Exit codes:
  0  success (warnings alone do not change the exit code)
  1  validation errors found (analysis blocked), or nothing to analyze
  2  usage, argument, or output error (bad flags, unreadable file, bad
     config, refusing to overwrite an output or an input file, an output
     that cannot be written)
  3  unexpected internal error (use --debug for the traceback)
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import date
from importlib import resources
from pathlib import Path

from . import HEURISTIC_DISCLAIMER, RELEASE_STAGE, __version__
from .analysis import find_vehicle, run_analysis
from .config import ConfigError, default_config_bytes, load_config
from .dates import DateParseError, parse_date
from .ingest import SERVICE_COLUMNS, VEHICLE_COLUMNS, IngestError, template_header
from .models import AnalysisResult
from .output import OutputError, PlannedFile, write_output, write_outputs
from .reports import FORMATS, render_csv, render_explanation, render_html, render_json, render_text
from .reports.csv_out import render_findings_csv
from .reports.text import render_validation

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

# The demo always uses this as-of date so its output is stable.
DEMO_AS_OF = date(2026, 6, 30)

VERSION_TEXT = f"nbdf-fleet {__version__} ({RELEASE_STAGE})"

# Files written by `nbdf-fleet init`.
INIT_DEFAULT_DIR = "nbdf-fleet-data"
INIT_CONFIG_NAME = "rules.toml"
INIT_VEHICLES_NAME = "vehicles.csv"
INIT_SERVICES_NAME = "service_history.csv"


class UsageError(Exception):
    """A problem the user can fix by changing arguments or inputs."""


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D401 - argparse hook
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="nbdf-fleet",
        description=(
            "NBDF Fleet Maintenance CLI - explainable, rules-based maintenance priority "
            "scoring for public-works fleets. Planning heuristic only; not a failure prediction."
        ),
        epilog="Exit codes: 0 ok, 1 validation errors, 2 usage error, 3 internal error.",
    )
    parser.add_argument("--version", action="version", version=VERSION_TEXT)
    parser.add_argument("--debug", action="store_true", help="show a traceback on internal errors")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    def add_common(p: argparse.ArgumentParser, with_files: bool = True) -> None:
        if with_files:
            p.add_argument("vehicle_file", type=Path, metavar="vehicle-file", help="vehicle inventory CSV")
            p.add_argument("service_file", type=Path, metavar="service-file", help="service history CSV")
        p.add_argument("--config", type=Path, metavar="TOML", help="rules configuration (default: bundled)")
        if with_files:
            p.add_argument(
                "--as-of", dest="as_of", metavar="YYYY-MM-DD",
                help="analysis date for all time calculations (default: today)",
            )

    p = sub.add_parser("demo", help="run the bundled synthetic dataset end to end (fixed as-of date)")
    add_common(p, with_files=False)
    p.add_argument("--output-dir", type=Path, metavar="DIR", help="also write CSV, JSON, and HTML here")
    p.add_argument("--force", action="store_true", help="overwrite existing output files")

    p = sub.add_parser(
        "init",
        help=f"create a rules config and header-only CSV templates (default: .\\{INIT_DEFAULT_DIR})",
    )
    p.add_argument("directory", nargs="?", type=Path, default=Path(INIT_DEFAULT_DIR),
                   help=f"target directory (default: {INIT_DEFAULT_DIR} under the current directory)")
    p.add_argument("--force", action="store_true", help="overwrite existing files")

    p = sub.add_parser("validate", help="check both CSV files and list every finding")
    add_common(p)

    p = sub.add_parser("analyze", help="terminal report; --output-dir also writes CSV and JSON")
    add_common(p)
    p.add_argument("--output-dir", type=Path, metavar="DIR", help="write fleet_analysis.csv/.json and findings.csv")
    p.add_argument("--force", action="store_true", help="overwrite existing output files")

    p = sub.add_parser(
        "explain",
        help="plain-language classification and score breakdown for one vehicle "
             "(explain <vehicle-file> <service-file> <vehicle-id>)",
    )
    add_common(p)
    p.add_argument("vehicle_id", metavar="vehicle-id", help="vehicle ID to explain")

    p = sub.add_parser("report", help="render the analysis in one format")
    add_common(p)
    p.add_argument("--format", choices=FORMATS, required=True, help="output format")
    p.add_argument("--output", type=Path, metavar="PATH", help="write to this file instead of stdout")
    p.add_argument("--force", action="store_true", help="overwrite an existing output file")
    return parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_of(text: str | None) -> date:
    if text is None:
        return date.today()
    try:
        return parse_date(text)
    except DateParseError as exc:
        raise UsageError(f"--as-of: {exc}") from exc


def _check_file(path: Path, label: str) -> None:
    if not path.exists():
        raise UsageError(f"{label} '{path}' does not exist")
    if not path.is_file():
        raise UsageError(f"{label} '{path}' is not a file")


def _emit(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _configure_streams() -> None:
    # Never crash on a legacy Windows console code page: characters the
    # console cannot show are replaced instead of raising.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - closed/odd streams
                pass


def _analyze(args: argparse.Namespace, vehicle_file: Path, service_file: Path, as_of: date) -> AnalysisResult:
    _check_file(vehicle_file, "vehicle file")
    _check_file(service_file, "service file")
    config = load_config(args.config)
    return run_analysis(vehicle_file, service_file, config, as_of)


def _inputs(args: argparse.Namespace) -> list[Path]:
    """Every input path of this command; outputs may never resolve to one."""
    paths = [getattr(args, "vehicle_file", None), getattr(args, "service_file", None),
             getattr(args, "config", None)]
    return [p for p in paths if p is not None]


def _write_bundle(result: AnalysisResult, output_dir: Path, force: bool, include_html: bool,
                  protected: list[Path]) -> list[Path]:
    files = [
        PlannedFile(output_dir / "fleet_analysis.csv", render_csv(result)),
        PlannedFile(output_dir / "fleet_analysis.json", render_json(result)),
        PlannedFile(output_dir / "findings.csv", render_findings_csv(result)),
    ]
    if include_html:
        files.append(PlannedFile(output_dir / "fleet_analysis.html", render_html(result)))
    return write_outputs(files, force, protected)


def _q(path: Path | str) -> str:
    """Quote a path for a printed PowerShell/cmd command when it needs it."""
    text = str(path)
    if any(ch in text for ch in " \t&;()'`$,"):
        return '"' + text.replace('"', '""') + '"'
    return text


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _no_vehicles(result: AnalysisResult) -> bool:
    """A header-only inventory validates but cannot be analyzed."""
    return not result.blocked and not result.results


NO_VEHICLES_MESSAGE = (
    "nothing to analyze: the vehicle file has a valid header but no vehicle rows "
    "(validate reports this as the 'no_data_rows' warning)\n"
)


def _next_step_commands(target: Path) -> str:
    vehicles = _q(target / INIT_VEHICLES_NAME)
    services = _q(target / INIT_SERVICES_NAME)
    config = _q(target / INIT_CONFIG_NAME)
    return (
        f"  nbdf-fleet validate {vehicles} {services} --config {config}\n"
        f"  nbdf-fleet analyze  {vehicles} {services} --config {config} --as-of YYYY-MM-DD\n"
        f"  nbdf-fleet explain  {vehicles} {services} <vehicle-id> --config {config} --as-of YYYY-MM-DD\n"
    )


def cmd_init(args: argparse.Namespace) -> int:
    target: Path = args.directory
    files = [
        PlannedFile(target / INIT_CONFIG_NAME, default_config_bytes().decode("utf-8")),
        PlannedFile(target / INIT_VEHICLES_NAME, template_header(VEHICLE_COLUMNS)),
        PlannedFile(target / INIT_SERVICES_NAME, template_header(SERVICE_COLUMNS)),
    ]
    # init has no input files, so nothing needs protecting beyond the
    # never-overwrite-without---force rule the writer always applies.
    for path in write_outputs(files, args.force, []):
        _emit(f"wrote {path}\n")
    _emit(
        "\nNext steps:\n"
        f"  1. Fill {INIT_VEHICLES_NAME} and {INIT_SERVICES_NAME} (one row per vehicle / service;\n"
        "     dates as YYYY-MM-DD; leave unknown cells blank, never 0). Keep real fleet data\n"
        "     outside any published repository.\n"
        f"  2. Edit {INIT_CONFIG_NAME}: replace the PLACEHOLDER intervals with your maintenance\n"
        "     program, then set [meta] placeholder_intervals = false to clear the banner.\n"
        "  3. Run:\n"
        + _next_step_commands(target)
    )
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    result = _analyze(args, args.vehicle_file, args.service_file, _as_of(args.as_of))
    _emit(render_validation(result))
    return EXIT_VALIDATION if result.blocked else EXIT_OK


def cmd_analyze(args: argparse.Namespace) -> int:
    result = _analyze(args, args.vehicle_file, args.service_file, _as_of(args.as_of))
    if _no_vehicles(result):
        _emit(NO_VEHICLES_MESSAGE)
        return EXIT_VALIDATION
    _emit(render_text(result))
    if result.blocked:
        return EXIT_VALIDATION
    if args.output_dir is not None:
        for path in _write_bundle(result, args.output_dir, args.force, False, _inputs(args)):
            _emit(f"wrote {path}\n")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    result = _analyze(args, args.vehicle_file, args.service_file, _as_of(args.as_of))
    if _no_vehicles(result):
        _emit(NO_VEHICLES_MESSAGE)
        return EXIT_VALIDATION
    if result.blocked:
        _emit(render_text(result))
        return EXIT_VALIDATION
    item = find_vehicle(result, args.vehicle_id)
    if item is None:
        raise UsageError(f"vehicle '{args.vehicle_id}' is not in {args.vehicle_file.name}")
    _emit(render_explanation(result, item))
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    result = _analyze(args, args.vehicle_file, args.service_file, _as_of(args.as_of))
    if _no_vehicles(result):
        _emit(NO_VEHICLES_MESSAGE)
        return EXIT_VALIDATION
    if result.blocked:
        _emit(render_text(result))
        return EXIT_VALIDATION
    renderers = {"text": render_text, "html": render_html, "csv": render_csv, "json": render_json}
    content = renderers[args.format](result)
    if args.output is None:
        _emit(content)
    else:
        path = write_output(args.output, content, args.force, _inputs(args))
        _emit(f"wrote {path}\n")
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    package = resources.files("nbdf_fleet.resources")
    with resources.as_file(package.joinpath("demo_vehicles.csv")) as vehicle_file, \
            resources.as_file(package.joinpath("demo_service_history.csv")) as service_file:
        result = run_analysis(vehicle_file, service_file, config, DEMO_AS_OF)
    _emit(
        "SYNTHETIC DEMO DATA - fictional vehicles and departments, unsuitable for any "
        f"operational fleet decision. As-of date is fixed at {DEMO_AS_OF.isoformat()}.\n"
        "The two validation warnings in this demo are intentional examples of warning output.\n\n"
    )
    _emit(render_text(result))
    if result.blocked:  # pragma: no cover - the bundled data is kept clean
        return EXIT_VALIDATION
    top = result.results[0]
    _emit("\n")
    _emit(render_explanation(result, top))
    if args.output_dir is not None:
        protected = [args.config] if args.config is not None else []
        for path in _write_bundle(result, args.output_dir, args.force, True, protected):
            _emit(f"wrote {path}\n")
    _emit(
        "\nNext: create a workspace with your own data and run the same analysis:\n"
        f"  nbdf-fleet init {INIT_DEFAULT_DIR}\n"
        + _next_step_commands(Path(INIT_DEFAULT_DIR))
    )
    return EXIT_OK


COMMANDS = {
    "demo": cmd_demo,
    "init": cmd_init,
    "validate": cmd_validate,
    "analyze": cmd_analyze,
    "explain": cmd_explain,
    "report": cmd_report,
}


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    debug = False
    try:
        args = parser.parse_args(argv)
        debug = args.debug
        return COMMANDS[args.command](args)
    except UsageError as exc:
        sys.stderr.write(f"nbdf-fleet: error: {exc}\n")
        sys.stderr.write("run 'nbdf-fleet --help' for usage\n")
        return EXIT_USAGE
    except (ConfigError, IngestError, OutputError) as exc:
        sys.stderr.write(f"nbdf-fleet: error: {exc}\n")
        return EXIT_USAGE
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("nbdf-fleet: interrupted\n")
        return EXIT_INTERNAL
    except BrokenPipeError:
        # The reader closed the pipe early (e.g. `| more`, `| head`). That is
        # the consumer's choice, not an internal error: exit quietly. Redirect
        # stdout to devnull so the interpreter does not complain on shutdown.
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        except OSError:  # pragma: no cover
            pass
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - last-resort handler by design
        if debug:
            traceback.print_exc()
        else:
            sys.stderr.write(
                f"nbdf-fleet: internal error: {type(exc).__name__}: {exc} "
                "(re-run with --debug for details)\n"
            )
        return EXIT_INTERNAL


def run() -> None:  # console-script entry point
    sys.exit(main())


# Keep the disclaimer importable from the CLI module for docs/tests.
DISCLAIMER = HEURISTIC_DISCLAIMER

if __name__ == "__main__":  # pragma: no cover
    run()
