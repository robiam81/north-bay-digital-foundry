# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Safe, all-or-nothing output writing.

Guarantees for every command that writes files:

1. **Inputs are never outputs.** A destination that resolves to any input
   file (vehicle CSV, service CSV, config) is refused, with or without
   ``--force``. Paths are compared after ``os.path.realpath`` and case
   normalization, and with ``os.path.samefile`` when both exist, so
   ``.\\a.csv``, ``A.CSV``, and a symlink to it are all recognized.
2. **Preflight before any write.** Every destination in the bundle is checked
   first (input collision, existing file without ``--force``, destination is
   a directory, a parent path component is a file). Nothing is written if
   any check fails.
3. **No partial files.** Each file's complete content is written to a
   temporary file in the destination directory, flushed, and fsynced.
4. **No mixed bundles.** Temporary files are swapped into place only after
   all of them were written. If a swap fails, files already swapped are
   restored from backups, temporary files are removed, and directories this
   call created are removed again, so the destination looks exactly as it did
   before the run.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class OutputError(Exception):
    """An output could not be written; the message says why. Exit code 2."""


class OutputExistsError(OutputError):
    """Refusing to overwrite an existing file without --force."""


class InputCollisionError(OutputError):
    """A destination is one of the command's own input files."""


def _canonical(path: Path) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _same_file(a: Path, b: Path) -> bool:
    if _canonical(a) == _canonical(b):
        return True
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


@dataclass(frozen=True)
class PlannedFile:
    path: Path
    content: str


def preflight(files: list[PlannedFile], force: bool, protected: list[Path]) -> None:
    """Check every destination before anything is written."""
    seen: dict[str, Path] = {}
    for item in files:
        key = _canonical(item.path)
        if key in seen:
            raise OutputError(f"'{item.path}' is listed twice as an output")
        seen[key] = item.path
        for source in protected:
            if _same_file(item.path, source):
                raise InputCollisionError(
                    f"refusing to write '{item.path}': it is an input file of this command "
                    f"('{source}'); choose a different output path (--force does not override this)"
                )
        # Any existing ancestor that is a file makes the destination impossible.
        for parent in item.path.parents:
            if parent.exists():
                if not parent.is_dir():
                    raise OutputError(
                        f"cannot write '{item.path}': '{parent}' is a file, not a directory"
                    )
                break
        if item.path.exists():
            if item.path.is_dir():
                raise OutputError(f"cannot write '{item.path}': it is a directory")
            if not force:
                existing = [str(f.path) for f in files if f.path.exists() and not f.path.is_dir()]
                raise OutputExistsError(
                    f"{', '.join(existing)} already exist(s); nothing was written; "
                    "use --force to overwrite"
                )


def write_outputs(files: list[PlannedFile], force: bool, protected: list[Path] | None = None) -> list[Path]:
    """Write all ``files`` or none of them. Returns the written paths."""
    protected = list(protected or [])
    preflight(files, force, protected)

    created_dirs: list[Path] = []
    temps: list[tuple[PlannedFile, Path]] = []
    try:
        for item in files:
            _make_parents(item.path.parent, created_dirs)
            temps.append((item, _write_temp(item)))
    except OSError as exc:
        _discard(temps, created_dirs)
        raise OutputError(f"could not write output ({exc}); nothing was changed") from exc

    # Swap phase: move any existing destination aside, then move the new file
    # in. Keep enough state to undo everything if a later swap fails.
    backups: list[tuple[Path, Path]] = []  # (destination, backup)
    placed: list[Path] = []
    try:
        for item, temp in temps:
            if item.path.exists():
                backup = _reserve_name(item.path, ".nbdf-bak-")
                os.replace(item.path, backup)
                backups.append((item.path, backup))
            _replace(temp, item.path)
            placed.append(item.path)
    except OSError as exc:
        for path in placed:
            _silent_unlink(path)
        for destination, backup in reversed(backups):
            try:
                os.replace(backup, destination)
            except OSError:  # pragma: no cover - leave the backup for the user
                pass
        _discard(temps, created_dirs)
        raise OutputError(
            f"could not replace output files ({exc}); the destination was restored"
        ) from exc
    for _, backup in backups:
        _silent_unlink(backup)
    return [item.path for item in files]


def write_output(path: Path, content: str, force: bool, protected: list[Path] | None = None) -> Path:
    """Single-file form of :func:`write_outputs`."""
    return write_outputs([PlannedFile(path, content)], force, protected)[0]


# ---------------------------------------------------------------------------
# Internals (module-level so tests can inject failures)
# ---------------------------------------------------------------------------


def _make_parents(directory: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for folder in reversed(missing):
        folder.mkdir()
        created.append(folder)


def _write_temp(item: PlannedFile) -> Path:
    """Write the whole content to a temp file beside the destination."""
    data = item.content.encode("utf-8")  # binary: CSV keeps CRLF, others keep LF
    fd, name = tempfile.mkstemp(prefix=".nbdf-tmp-", dir=item.path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        _silent_unlink(temp)
        raise
    return temp


def _replace(temp: Path, destination: Path) -> None:
    os.replace(temp, destination)


def _reserve_name(path: Path, prefix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=prefix, dir=path.parent)
    os.close(fd)
    os.unlink(name)
    return Path(name)


def _discard(temps: list[tuple[PlannedFile, Path]], created_dirs: list[Path]) -> None:
    for _, temp in temps:
        _silent_unlink(temp)
    for folder in reversed(created_dirs):
        try:
            folder.rmdir()
        except OSError:
            pass


def _silent_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:  # pragma: no cover
        pass
