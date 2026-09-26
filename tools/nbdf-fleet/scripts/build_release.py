# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0
"""Build the release artifacts OUTSIDE the repository and verify them.

Usage (from tools/nbdf-fleet, with a venv that has `build`, `setuptools>=77`
and `wheel`; this script must never run with the runtime venv's stdlib-only
constraint in mind - it is release tooling, not part of the package):

    python scripts/build_release.py --outdir C:\\Projects\\nbdf-fleet-dist\\0.1.0-rc2

`--outdir` is the exact release folder. It must be outside the git
repository. The script only ever writes or replaces its own three artifact
names (nbdf_fleet-*.whl, nbdf-fleet-*-source.zip, SHA256SUMS.txt):

  * if the folder holds ANY other file or folder, the script refuses to run;
  * if it already holds artifacts, the script refuses unless --replace is
    given, and then replaces only those named files, after a successful
    build and verification in a temporary folder.

It never deletes anything else.

Steps:
  1. Stage an explicit allowlist of project files into a temporary directory
     (never .venv, caches, egg-info, build outputs), so the build cannot pick
     up stray files and leaves nothing behind in the repository.
  2. Build the wheel from the staged copy with `python -m build --wheel`.
  3. Zip the staged copy as a Windows-friendly source archive.
  4. Verify: wheel contains bundled resources and LICENSE, METADATA declares
     MPL-2.0, no tests/venv/cache files; source zip contains LICENSE.
  5. Write SHA256SUMS.txt ("<hash>  <file name>").
  6. Copy the three verified files into --outdir.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))
from nbdf_fleet import __version__  # noqa: E402

# Explicit allowlist. Directories are copied recursively, minus EXCLUDED_DIRS.
ALLOWLIST_FILES = ("pyproject.toml", "README.md", "LICENSE", ".gitignore")
ALLOWLIST_DIRS = ("src", "tests", "docs", "examples", "config", "scripts")
EXCLUDED_DIRS = {".venv", "__pycache__", ".pytest_cache", "build", "dist"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".egg-info")


def is_excluded(path: Path) -> bool:
    if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in path.parts):
        return True
    return path.suffix in EXCLUDED_SUFFIXES


def staged_files() -> list[Path]:
    """Relative paths of every file the release may contain, sorted."""
    files: list[Path] = []
    for name in ALLOWLIST_FILES:
        if (PROJECT_DIR / name).is_file():
            files.append(Path(name))
    for name in ALLOWLIST_DIRS:
        root = PROJECT_DIR / name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(PROJECT_DIR)
                if not is_excluded(rel):
                    files.append(rel)
    return sorted(set(files), key=lambda p: p.as_posix())


def stage(target: Path) -> list[Path]:
    files = staged_files()
    for rel in files:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_DIR / rel, dest)
    return files


def build_wheel(staged: Path, outdir: Path) -> Path:
    if importlib.util.find_spec("build") is not None:
        command = [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(outdir), str(staged)]
    else:
        # Offline fallback: call the PEP 517 backend declared in pyproject.toml
        # directly, which is what `python -m build --no-isolation` does. Needs
        # setuptools>=77 in this interpreter; no download.
        print("note: 'build' is not installed; using setuptools.build_meta directly")
        command = [
            sys.executable, "-c",
            "import sys, setuptools.build_meta as b; print(b.build_wheel(sys.argv[1]))",
            str(outdir),
        ]
    subprocess.run(command, check=True, cwd=str(staged))
    wheels = sorted(outdir.glob(f"nbdf_fleet-{__version__}-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one wheel in {outdir}, found {wheels}")
    return wheels[0]


def build_source_zip(staged: Path, files: list[Path], outdir: Path) -> Path:
    top = f"nbdf-fleet-{__version__}"
    target = outdir / f"{top}-source.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(staged / rel, f"{top}/{rel.as_posix()}")
    return target


def verify_wheel(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        metadata = next(n for n in names if n.endswith(".dist-info/METADATA"))
        text = zf.read(metadata).decode("utf-8")
    problems = []
    for required in (
        "nbdf_fleet/resources/default_rules.toml",
        "nbdf_fleet/resources/demo_vehicles.csv",
        "nbdf_fleet/resources/demo_service_history.csv",
        "nbdf_fleet/cli.py",
    ):
        if required not in names:
            problems.append(f"missing {required}")
    if not any(n.endswith(".dist-info/licenses/LICENSE") for n in names):
        problems.append("LICENSE not in dist-info/licenses")
    if "License-Expression: MPL-2.0" not in text:
        problems.append("METADATA lacks 'License-Expression: MPL-2.0'")
    if "Author: North Bay Digital Foundry" not in text:
        problems.append("METADATA lacks author")
    if f"Version: {__version__}" not in text:
        problems.append("METADATA version mismatch")
    if "Requires-Dist:" in text.replace("Requires-Dist: pytest", "").replace("; extra ==", ""):
        # only the dev extra may declare requirements
        for line in text.splitlines():
            if line.startswith("Requires-Dist:") and "extra ==" not in line:
                problems.append(f"unexpected runtime requirement: {line}")
    bad = [n for n in names if n.startswith("tests/") or "/tests/" in n or ".venv" in n
           or "__pycache__" in n or n.endswith(".pyc") or "/.pytest_cache" in n]
    if bad:
        problems.append(f"unexpected files: {bad[:5]}")
    if problems:
        raise SystemExit("wheel verification failed: " + "; ".join(problems))
    print(f"wheel ok: {len(names)} entries, MPL-2.0 declared, LICENSE bundled")


def verify_zip(archive: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    top = f"nbdf-fleet-{__version__}/"
    problems = []
    for required in ("LICENSE", "pyproject.toml", "README.md", "src/nbdf_fleet/cli.py",
                     "config/default_rules.toml", "examples/demo_vehicles.csv"):
        if top + required not in names:
            problems.append(f"missing {required}")
    bad = [n for n in names if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in n.split("/"))]
    if bad:
        problems.append(f"unexpected files: {bad[:5]}")
    if problems:
        raise SystemExit("source zip verification failed: " + "; ".join(problems))
    print(f"source zip ok: {len(names)} entries, LICENSE included")


def write_checksums(outdir: Path, files: list[Path]) -> Path:
    lines = []
    for path in sorted(files, key=lambda p: p.name):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    target = outdir / "SHA256SUMS.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return target


ARTIFACT_PATTERNS = ("nbdf_fleet-*.whl", "nbdf-fleet-*-source.zip", "SHA256SUMS.txt")


def is_artifact(path: Path) -> bool:
    return path.is_file() and any(path.match(pattern) for pattern in ARTIFACT_PATTERNS)


def repository_root(start: Path) -> Path | None:
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def check_outdir(outdir: Path, replace: bool) -> None:
    """Refuse unsafe release folders. Never deletes anything."""
    outdir = outdir.resolve()
    guard = repository_root(PROJECT_DIR) or PROJECT_DIR
    if outdir == guard or guard in outdir.parents:
        raise SystemExit(f"--outdir must be outside the repository ({guard})")
    if not outdir.exists():
        return
    if not outdir.is_dir():
        raise SystemExit(f"--outdir '{outdir}' exists and is not a folder")
    entries = sorted(outdir.iterdir())
    foreign = [p.name for p in entries if not is_artifact(p)]
    if foreign:
        raise SystemExit(
            f"--outdir '{outdir}' contains files this script did not create: "
            f"{', '.join(foreign)}; use an empty or new folder (nothing was changed)"
        )
    if entries and not replace:
        raise SystemExit(
            f"--outdir '{outdir}' already holds release artifacts: "
            f"{', '.join(p.name for p in entries)}; pass --replace to overwrite them "
            "or choose a new folder (nothing was changed)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outdir", type=Path, required=True,
                        help="exact release folder, OUTSIDE the repository")
    parser.add_argument("--replace", action="store_true",
                        help="replace existing release artifacts in --outdir (only those files)")
    args = parser.parse_args(argv)
    outdir = args.outdir.resolve()
    check_outdir(outdir, args.replace)

    with tempfile.TemporaryDirectory(prefix="nbdf-fleet-release-") as tmp:
        work = Path(tmp)
        staged = work / f"nbdf-fleet-{__version__}"
        built = work / "out"
        staged.mkdir()
        built.mkdir()
        files = stage(staged)
        print(f"staged {len(files)} files")
        wheel = build_wheel(staged, built)
        archive = build_source_zip(staged, files, built)
        verify_wheel(wheel)
        verify_zip(archive)
        sums = write_checksums(built, [wheel, archive])
        # Only now touch the destination, and only with our own file names.
        outdir.mkdir(parents=True, exist_ok=True)
        written = []
        for artifact in (wheel, archive, sums):
            target = outdir / artifact.name
            shutil.copy2(artifact, target)
            written.append(target)
    for target in written:
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
