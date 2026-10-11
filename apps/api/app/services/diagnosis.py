"""Deterministic, rule-based trace diagnostics.

Every finding cites the span ids it is derived from. These rules never call an
LLM and are always available; the UI labels them separately from AI analysis.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Project, Span, Trace

TIMEOUT_PATTERN = re.compile(
    r"time(d)?[\s_-]?out|deadline exceeded|ReadTimeout|ConnectTimeout|\b504\b|\b408\b", re.IGNORECASE
)
RETRY_THRESHOLD = 3
BASELINE_MIN_SAMPLES = 20
BASELINE_FACTOR = 2.0
BASELINE_WINDOW = timedelta(days=7)


def _f(
    rule: str, severity: str, title: str, detail: str, span_ids: list[str], **evidence: Any
) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "title": title,
        "detail": detail,
        "span_ids": span_ids,
        "evidence": evidence,
    }


def _baselines(db: Session, project_id: Any, names: list[str], exclude_trace: Any) -> dict[str, float]:
    if not names:
        return {}
    since = datetime.now(UTC) - BASELINE_WINDOW
    rows = db.execute(
        select(
            Span.name,
            func.percentile_cont(0.95).within_group(Span.duration_ms.asc()),
            func.count(),
        )
        .where(
            Span.project_id == project_id,
            Span.name.in_(names),
            Span.start_time >= since,
            Span.duration_ms.is_not(None),
            Span.trace_pk != exclude_trace,
        )
        .group_by(Span.name)
    ).all()
    return {name: float(p95) for name, p95, n in rows if n >= BASELINE_MIN_SAMPLES and p95 is not None}


def diagnose(db: Session, project: Project, trace: Trace, spans: list[Span]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    by_id = {s.span_id: s for s in spans}
    children: dict[str | None, list[Span]] = defaultdict(list)
    for s in spans:
        children[s.parent_span_id].append(s)
    errors = [s for s in spans if s.status == "error"]

    if trace.status == "incomplete":
        findings.append(
            _f(
                "incomplete_trace",
                "medium",
                "Trace never completed",
                "No end event was received for this trace. The process may have crashed, been killed, or exited "
                "before the SDK flushed. Spans that finished before that point are shown.",
                [s.span_id for s in spans if s.parent_span_id is None][:5],
            )
        )

    # Deepest failing spans: errors without failing descendants are the most likely origin.
    def has_error_descendant(span: Span) -> bool:
        stack = list(children.get(span.span_id, []))
        while stack:
            c = stack.pop()
            if c.status == "error":
                return True
            stack.extend(children.get(c.span_id, []))
        return False

    origins = sorted((s for s in errors if not has_error_descendant(s)), key=lambda s: s.start_time)
    for s in origins[:10]:
        chain = []
        cur = by_id.get(s.parent_span_id or "")
        while cur is not None and len(chain) < 20:
            chain.append(cur.span_id)
            cur = by_id.get(cur.parent_span_id or "")
        findings.append(
            _f(
                "failed_span",
                "high",
                f"{s.kind.upper()} span '{s.name}' failed",
                f"{s.error_type or 'Error'}: {(s.error_message or 'no message recorded')[:400]}",
                [s.span_id, *chain],
                error_type=s.error_type,
                propagated_through=len([c for c in chain if by_id[c].status == "error"]),
            )
        )

    if trace.status == "error" and not errors:
        findings.append(
            _f(
                "trace_error_without_span",
                "medium",
                "Trace failed but no span recorded an error",
                f"The trace reported {trace.error_type or 'an error'}"
                f"{': ' + trace.error_message[:300] if trace.error_message else ''}. The failure happened outside "
                "any instrumented span, so instrument the surrounding code to locate it.",
                [trace.root_span_id] if trace.root_span_id else [],
            )
        )

    timeouts = [s for s in errors if TIMEOUT_PATTERN.search(f"{s.error_type or ''} {s.error_message or ''}")]
    if timeouts:
        findings.append(
            _f(
                "timeout",
                "high",
                f"{len(timeouts)} span(s) timed out",
                "Error type or message indicates a timeout: "
                + "; ".join(f"'{s.name}' after {round(s.duration_ms or 0)} ms" for s in timeouts[:5]),
                [s.span_id for s in timeouts],
            )
        )

    tool_errors: dict[str, list[Span]] = defaultdict(list)
    for s in errors:
        if s.kind == "tool":
            tool_errors[s.name].append(s)
    for name, group in tool_errors.items():
        if len(group) >= 2:
            findings.append(
                _f(
                    "repeated_tool_errors",
                    "high",
                    f"Tool '{name}' failed {len(group)} times",
                    "The same tool failed repeatedly within one trace. Error types: "
                    + ", ".join(sorted({g.error_type or "Error" for g in group})),
                    [g.span_id for g in group],
                )
            )

    explicit_retries = [s for s in spans if (s.retry_count or 0) >= RETRY_THRESHOLD]
    if explicit_retries:
        findings.append(
            _f(
                "excessive_retries",
                "medium",
                "Spans reported excessive retries",
                ", ".join(f"'{s.name}' retried {s.retry_count}x" for s in explicit_retries[:5]),
                [s.span_id for s in explicit_retries],
            )
        )
    for parent_id, siblings in children.items():
        by_name: dict[str, list[Span]] = defaultdict(list)
        for s in siblings:
            by_name[s.name].append(s)
        for name, group in by_name.items():
            failed_before_last = [
                g for g in sorted(group, key=lambda g: g.start_time)[:-1] if g.status == "error"
            ]
            if len(group) >= RETRY_THRESHOLD and len(failed_before_last) >= RETRY_THRESHOLD - 1:
                findings.append(
                    _f(
                        "retry_pattern",
                        "medium",
                        f"'{name}' was attempted {len(group)} times",
                        f"{len(failed_before_last)} attempt(s) failed before the last one under the same parent.",
                        [g.span_id for g in group],
                        parent_span_id=parent_id,
                    )
                )

    threshold = project.slow_span_threshold_ms
    baselines = _baselines(db, project.id, sorted({s.name for s in spans if s.duration_ms}), trace.id)
    for s in spans:
        if s.duration_ms is None:
            continue
        p95 = baselines.get(s.name)
        if p95 is not None and s.duration_ms > BASELINE_FACTOR * p95 and s.duration_ms > 250:
            findings.append(
                _f(
                    "slow_vs_baseline",
                    "medium",
                    f"'{s.name}' was {s.duration_ms / p95:.1f}x slower than its 7-day p95",
                    f"{round(s.duration_ms)} ms vs p95 {round(p95)} ms over the last 7 days.",
                    [s.span_id],
                    p95_ms=round(p95, 1),
                )
            )
        elif s.duration_ms > threshold:
            findings.append(
                _f(
                    "slow_span",
                    "low",
                    f"'{s.name}' exceeded the slow-span threshold",
                    f"{round(s.duration_ms)} ms exceeds the project threshold of {threshold} ms.",
                    [s.span_id],
                )
            )

    if trace.duration_ms and trace.duration_ms > 1000:
        leaf_spans = [s for s in spans if not children.get(s.span_id) and s.duration_ms]
        if leaf_spans:
            top = max(leaf_spans, key=lambda s: s.duration_ms or 0)
            share = (top.duration_ms or 0) / trace.duration_ms
            if share >= 0.5:
                findings.append(
                    _f(
                        "dominant_span",
                        "low",
                        f"'{top.name}' accounts for {share:.0%} of trace latency",
                        f"{round(top.duration_ms or 0)} ms of {round(trace.duration_ms)} ms end-to-end.",
                        [top.span_id],
                    )
                )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank[f["severity"]])
    return findings
