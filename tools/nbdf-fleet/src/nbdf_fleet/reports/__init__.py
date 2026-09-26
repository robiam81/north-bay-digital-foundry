# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Report generators: text, CSV, JSON, and self-contained HTML."""

from .csv_out import render_csv
from .html_out import render_html
from .json_out import render_json
from .text import render_explanation, render_findings, render_text

FORMATS: tuple[str, ...] = ("text", "html", "csv", "json")

__all__ = [
    "FORMATS",
    "render_csv",
    "render_explanation",
    "render_findings",
    "render_html",
    "render_json",
    "render_text",
]
