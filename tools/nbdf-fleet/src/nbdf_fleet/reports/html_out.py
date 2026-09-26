# Copyright (c) 2026 North Bay Digital Foundry
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# SPDX-License-Identifier: MPL-2.0

"""Self-contained HTML report: inline CSS, no JavaScript, no external assets.

Every user-provided string (vehicle IDs, makes, notes, service types,
validation messages) passes through :func:`html.escape` with quotes escaped.
"""

from __future__ import annotations

import html

from .. import HEURISTIC_DISCLAIMER, PLACEHOLDER_BANNER
from ..models import AnalysisResult
from .common import (
    BAND_ORDER,
    STATUS_ORDER,
    criterion_interval_text,
    governing_threshold_text,
    number,
    score_value,
    summary_dict,
    utilization_value,
    warning_counts,
)

_CSS = """
:root { --ink: #1a1a18; --muted: #6b675c; --line: #e5e2d9; --paper: #f4f2ea; --surface: #fcfbf7; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
       color: var(--ink); background: var(--paper); }
main { max-width: 1100px; margin: 0 auto; background: var(--surface); border: 2px solid var(--ink);
       border-radius: 12px; padding: 24px 28px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 16px; margin: 28px 0 8px; text-transform: uppercase; letter-spacing: 0.06em; }
h3 { font-size: 15px; margin: 18px 0 6px; }
.meta { color: var(--muted); font-size: 13px; }
.disclaimer { border: 1px dashed var(--ink); padding: 10px 14px; margin: 16px 0; background: var(--paper); }
.banner { border: 3px double var(--ink); padding: 10px 14px; margin: 16px 0; background: var(--paper); }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0 16px; }
th, td { border-bottom: 1px solid var(--line); padding: 5px 8px; text-align: left; vertical-align: top; }
th { border-bottom: 2px solid var(--ink); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.status-OVERDUE { font-weight: 700; }
.status-DUE_SOON { font-weight: 600; }
.status-INSUFFICIENT_DATA { font-style: italic; }
.band-HIGH { font-weight: 700; }
details { margin: 6px 0 10px; }
summary { cursor: pointer; font-weight: 600; }
.small { font-size: 12px; color: var(--muted); }
.gap { color: var(--ink); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; }
dt { color: var(--muted); }
dd { margin: 0; }
@media print { body { background: #fff; padding: 0; } main { border: none; } }
"""


def _e(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _num(value) -> str:
    n = number(value)
    return "MISSING" if n is None else _e(n)


def render_html(result: AnalysisResult) -> str:
    m = result.metadata
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>Fleet maintenance analysis - as of {_e(m.as_of.isoformat())}</title>")
    parts.append(f"<style>{_CSS}</style></head><body><main>")
    parts.append("<h1>NBDF Fleet Maintenance CLI - fleet analysis</h1>")
    parts.append(
        '<p class="meta">'
        f"As-of date <strong>{_e(m.as_of.isoformat())}</strong> &middot; "
        f"tool v{_e(m.tool_version)} &middot; schema {_e(m.schema_version)} &middot; "
        f"config {_e(m.config_source)} (hash {_e(m.config_hash)}) &middot; "
        f"scoring method {_e(m.scoring_method)} &middot; "
        f"inputs {_e(m.vehicle_file)}, {_e(m.service_file)}"
        "</p>"
    )
    parts.append(f'<p class="disclaimer"><strong>Disclaimer.</strong> {_e(HEURISTIC_DISCLAIMER)}</p>')
    if m.placeholder_config:
        parts.append(f'<p class="banner" role="note"><strong>{_e(PLACEHOLDER_BANNER)}</strong></p>')

    if result.blocked:
        parts.append("<h2>Validation errors</h2><p>Analysis is blocked until these are fixed.</p>")
        parts.append(_findings_table(result.errors))
        parts.append(f"<p>{len(result.warnings)} warning(s) not shown.</p>")
        parts.append("</main></body></html>")
        return "\n".join(parts) + "\n"

    summary = summary_dict(result)
    parts.append("<h2>Fleet summary</h2>")
    parts.append("<table><tbody>")
    parts.append(f'<tr><th>Vehicles analyzed</th><td class="num">{summary["vehicles"]}</td></tr>')
    for status in STATUS_ORDER:
        parts.append(f'<tr><th>{_e(status.label)}</th><td class="num">{summary["by_status"][status.value]}</td></tr>')
    for band in BAND_ORDER:
        parts.append(f'<tr><th>Priority band {_e(band)}</th><td class="num">{summary["by_priority_band"][band]}</td></tr>')
    parts.append(f'<tr><th>Vehicles with data gaps</th><td class="num">{summary["vehicles_with_data_gaps"]}</td></tr>')
    parts.append(f'<tr><th>Service records analyzed</th><td class="num">{summary["service_records_analyzed"]}</td></tr>')
    parts.append(f'<tr><th>Service records excluded (future-dated)</th><td class="num">{summary["service_records_excluded_future_dated"]}</td></tr>')
    parts.append(f'<tr><th>Validation warnings</th><td class="num">{summary["warnings"]}</td></tr>')
    parts.append("</tbody></table>")

    counts = warning_counts(result)
    parts.append("<h2>Vehicles</h2>")
    parts.append('<p class="small">Ranked by score (descending), then vehicle ID.</p>')
    parts.append("<table><thead><tr>")
    for head, cls in (
        ("#", "num"), ("Vehicle", ""), ("Department", ""), ("Class", ""), ("Status", ""),
        ("Score", "num"), ("Band", ""), ("Gaps", "num"), ("Warnings", "num"),
        ("Governing task / threshold", ""),
    ):
        parts.append(f'<th class="{cls}">{head}</th>' if cls else f"<th>{head}</th>")
    parts.append("</tr></thead><tbody>")
    for item in result.results:
        a = item.assessment
        v = a.vehicle
        parts.append(
            "<tr>"
            f'<td class="num">{item.rank}</td>'
            f"<td>{_e(v.vehicle_id)}</td>"
            f"<td>{_e(v.department) or '-'}</td>"
            f"<td>{_e(v.asset_class)}</td>"
            f'<td class="status-{_e(a.status.value)}">{_e(a.status.label)}</td>'
            f'<td class="num">{score_value(item.score.score):.1f}</td>'
            f'<td class="band-{_e(item.score.band)}">{_e(item.score.band)}</td>'
            f'<td class="num">{len(a.data_gaps)}</td>'
            f'<td class="num">{counts.get(v.vehicle_id, 0)}</td>'
            f"<td>{_e(governing_threshold_text(item))}</td>"
            "</tr>"
        )
    parts.append("</tbody></table>")

    parts.append("<h2>Vehicle details</h2>")
    for item in result.results:
        a = item.assessment
        v = a.vehicle
        desc = " ".join(str(x) for x in (v.year, v.make, v.model) if x is not None)
        parts.append("<details>")
        parts.append(
            f"<summary>{item.rank}. {_e(v.vehicle_id)} {_e(desc)} &mdash; {_e(a.status.label)}, "
            f"score {score_value(item.score.score):.1f} ({_e(item.score.band)})</summary>"
        )
        parts.append("<dl>")
        parts.append(f"<dt>Asset class</dt><dd>{_e(v.asset_class)}</dd>")
        parts.append(f"<dt>Department</dt><dd>{_e(v.department) or '-'}</dd>")
        parts.append(f"<dt>In service</dt><dd>{_e(v.in_service_date.isoformat()) if v.in_service_date else 'MISSING'}</dd>")
        parts.append(f"<dt>Current odometer</dt><dd>{_num(v.current_odometer)}</dd>")
        parts.append(f"<dt>Current engine hours</dt><dd>{_num(v.current_engine_hours)}</dd>")
        parts.append(f"<dt>Service records</dt><dd>{a.service_record_count}</dd>")
        if a.corrective_in_window is not None:
            parts.append(
                f"<dt>Corrective records (last {a.repeat_window_months} months)</dt>"
                f"<dd>{a.corrective_in_window}</dd>"
            )
        if a.unmapped_service_types:
            parts.append(f"<dt>Unmapped service types</dt><dd>{_e('; '.join(a.unmapped_service_types))}</dd>")
        parts.append("</dl>")
        for note in a.notes:
            parts.append(f"<p>{_e(note)}</p>")

        if a.tasks:
            parts.append("<h3>Tasks</h3>")
            parts.append("<table><thead><tr><th>Task</th><th>Status</th><th>Last service</th><th>Meter</th>"
                         '<th class="num">Elapsed</th><th class="num">Interval</th><th class="num">Utilization</th>'
                         "<th>Note</th></tr></thead><tbody>")
            for t in a.tasks:
                last = t.last_service_date.isoformat() if t.last_service_date else "none"
                if t.assumed_baseline:
                    last += " (ASSUMED BASELINE)"
                for c in t.criteria:
                    util = utilization_value(c.utilization)
                    interval = _e(criterion_interval_text(c))
                    parts.append(
                        "<tr>"
                        f"<td>{_e(t.task_name)}</td>"
                        f'<td class="status-{_e(c.status.value)}">{_e(c.status.label)}</td>'
                        f"<td>{_e(last)}</td>"
                        f"<td>{_e(c.meter.value)}</td>"
                        f'<td class="num">{_num(c.elapsed) if c.elapsed is not None else "-"}</td>'
                        f'<td class="num">{interval}</td>'
                        f'<td class="num">{f"{util:.4f}" if util is not None else "-"}</td>'
                        f"<td>{_e(c.note)}</td>"
                        "</tr>"
                    )
                for note in t.notes:
                    parts.append(f'<tr><td colspan="8" class="small">{_e(note)}</td></tr>')
            parts.append("</tbody></table>")

        if a.data_gaps:
            parts.append("<h3>Data gaps</h3><ul>")
            for gap in a.data_gaps:
                parts.append(f'<li class="gap">{_e(gap)}</li>')
            parts.append("</ul>")

        parts.append("<h3>Score components</h3>")
        parts.append('<table><thead><tr><th>Component</th><th class="num">Weight</th><th class="num">Value</th>'
                     '<th class="num">Points</th><th>Explanation</th></tr></thead><tbody>')
        for c in item.score.components:
            inputs = "; ".join(f"{k}: {val}" for k, val in c.inputs)
            parts.append(
                "<tr>"
                f"<td>{_e(c.name)}</td>"
                f'<td class="num">{float(c.weight):.2f}</td>'
                f'<td class="num">{float(round(c.value, 4)):.4f}</td>'
                f'<td class="num">{float(round(c.contribution, 2)):.2f}</td>'
                f'<td>{_e(c.explanation)}<br><span class="small">{_e(inputs)}</span></td>'
                "</tr>"
            )
        parts.append(
            f'<tr><th>Total</th><td></td><td></td><td class="num">{score_value(item.score.score):.1f}</td>'
            f"<td>Band {_e(item.score.band)}</td></tr>"
        )
        parts.append("</tbody></table></details>")

    if result.warnings:
        parts.append(f"<h2>Validation warnings ({len(result.warnings)})</h2>")
        parts.append(_findings_table(result.warnings))

    parts.append(
        '<p class="small">Generated by NBDF Fleet Maintenance CLI (North Bay Digital Foundry). '
        "Deterministic rules-based planning heuristic; not a failure prediction.</p>"
    )
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def _findings_table(findings) -> str:
    rows = ["<table><thead><tr><th>Severity</th><th>Code</th><th>File</th><th class=\"num\">Row</th>"
            "<th>Field</th><th>Vehicle</th><th>Message</th><th>Suggested fix</th></tr></thead><tbody>"]
    for f in findings:
        rows.append(
            "<tr>"
            f"<td>{_e(f.severity.value)}</td><td>{_e(f.code)}</td><td>{_e(f.file)}</td>"
            f'<td class="num">{_e(f.row) if f.row is not None else ""}</td>'
            f"<td>{_e(f.field)}</td><td>{_e(f.vehicle_id)}</td>"
            f"<td>{_e(f.message)}</td><td>{_e(f.fix)}</td></tr>"
        )
    rows.append("</tbody></table>")
    return "\n".join(rows)
