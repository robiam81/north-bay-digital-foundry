# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""NBDF Fleet Maintenance CLI.

A local, explainable, rules-based maintenance priority tool for municipal and
public-works fleets. The score it produces is a planning heuristic derived from
configurable maintenance intervals. It is NOT a validated failure-prediction
model and must not be presented as one.

Authored by North Bay Digital Foundry.
"""

# Single source of truth for the package version. pyproject.toml reads it
# dynamically and the CLI, JSON, and HTML metadata all import it from here.
__version__ = "0.1.0"
RELEASE_STAGE = "prototype"

# Version of the CSV/JSON/HTML output schema produced by this tool. Bump when
# exported keys, columns, or their meaning change. History: docs/changelog.md.
SCHEMA_VERSION = "2"

# Version of the TOML rules-configuration schema this tool understands.
CONFIG_SCHEMA_VERSION = 1

PLACEHOLDER_BANNER = (
    "PLACEHOLDER CONFIG: Placeholder maintenance intervals in use - not agency "
    "or manufacturer schedules. Results are illustrative only."
)

HEURISTIC_DISCLAIMER = (
    "Planning heuristic only. Scores are derived from configured maintenance "
    "intervals and data completeness. They are not failure probabilities, "
    "not a validated prediction of breakdown, and not a substitute for "
    "inspection, manufacturer guidance, or fleet-manager judgment. "
    "Operational use requires calibration and validation on representative "
    "fleet data, subject-matter review, and continued human oversight."
)
