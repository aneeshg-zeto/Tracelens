"""Dashboard aggregates computed with SQL over stored traces and spans.

Metric definitions (also shown in the UI):
* Trace counts, error rate, and latency percentiles are trace-based.
* Error rate = traces with status "error" / completed traces (ok + error).
  Incomplete traces are counted separately and excluded from the rate.
* Latency percentiles use completed traces' end-to-end duration.
* Token and cost totals sum LLM spans only (see services/ingest.py).
* Cost totals only include spans with a known price; spans with usage but no
  matching price are counted as "unpriced" so the gap is visible.
* Model breakdown and top errors are span-based.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def _bucket(start: datetime, end: datetime) -> tuple[str, timedelta]:
    span = end - start
    if span <= timedelta(hours=6):
        return "5 minutes", timedelta(minutes=5)
    if span <= timedelta(days=2):
        return "1 hour", timedelta(hours=1)
    return "1 day", timedelta(days=1)


def overview(db: Session, project_id: uuid.UUID, start: datetime, end: datetime) -> dict[str, Any]:
    params = {"pid": project_id, "start": start, "end": end}
    totals = (
        db.execute(
            text(
                """
            SELECT
              count(*) AS total,
              count(*) FILTER (WHERE status = 'ok') AS ok,
              count(*) FILTER (WHERE status = 'error') AS error,
              count(*) FILTER (WHERE status = 'incomplete') AS incomplete,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE status <> 'incomplete' AND duration_ms IS NOT NULL) AS p50,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE status <> 'incomplete' AND duration_ms IS NOT NULL) AS p95,
              percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE status <> 'incomplete' AND duration_ms IS NOT NULL) AS p99,
              sum(input_tokens) AS input_tokens,
              sum(output_tokens) AS output_tokens,
              sum(total_tokens) AS total_tokens,
              sum(cost_usd) AS cost_usd,
              count(*) FILTER (WHERE cost_status IN ('unavailable', 'partial')) AS unpriced_traces
            FROM traces
            WHERE project_id = :pid AND start_time >= :start AND start_time < :end
            """
            ),
            params,
        )
        .mappings()
        .one()
    )
    completed = (totals["ok"] or 0) + (totals["error"] or 0)

    trunc, _ = _bucket(start, end)
    series = (
        db.execute(
            text(
                """
            WITH buckets AS (
              SELECT generate_series(
                date_bin(CAST(:step AS interval), CAST(:start AS timestamptz), TIMESTAMPTZ '2000-01-01'),
                CAST(:end AS timestamptz),
                CAST(:step AS interval)
              ) AS bucket
            )
            SELECT b.bucket,
              count(t.id) AS total,
              count(t.id) FILTER (WHERE t.status = 'error') AS error,
              count(t.id) FILTER (WHERE t.status IN ('ok', 'error')) AS completed,
              percentile_cont(0.95) WITHIN GROUP (ORDER BY t.duration_ms)
                FILTER (WHERE t.status <> 'incomplete') AS p95,
              sum(t.cost_usd) AS cost_usd,
              sum(t.total_tokens) AS total_tokens
            FROM buckets b
            LEFT JOIN traces t
              ON t.project_id = :pid
             AND t.start_time >= b.bucket AND t.start_time < b.bucket + CAST(:step AS interval)
             AND t.start_time >= :start AND t.start_time < :end
            GROUP BY b.bucket ORDER BY b.bucket
            """
            ),
            {**params, "step": trunc},
        )
        .mappings()
        .all()
    )

    models = (
        db.execute(
            text(
                """
            SELECT provider, model, count(*) AS calls,
                   count(*) FILTER (WHERE status = 'error') AS errors,
                   sum(total_tokens) AS total_tokens, sum(cost_usd) AS cost_usd,
                   count(*) FILTER (WHERE cost_status = 'unavailable') AS unpriced_calls,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms
            FROM spans
            WHERE project_id = :pid AND kind = 'llm' AND model IS NOT NULL
              AND start_time >= :start AND start_time < :end
            GROUP BY provider, model ORDER BY calls DESC LIMIT 10
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    errors = (
        db.execute(
            text(
                """
            SELECT coalesce(error_type, 'Error') AS error_type,
                   left(coalesce(error_message, ''), 200) AS message,
                   kind, count(*) AS occurrences, max(start_time) AS last_seen,
                   (array_agg(trace_id ORDER BY start_time DESC))[1] AS example_trace_id
            FROM spans
            WHERE project_id = :pid AND status = 'error' AND start_time >= :start AND start_time < :end
            GROUP BY 1, 2, 3 ORDER BY occurrences DESC LIMIT 10
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    histogram = (
        db.execute(
            text(
                """
            SELECT width_bucket(log(greatest(duration_ms, 1)), 0, 6, 12) AS bucket, count(*) AS n
            FROM traces
            WHERE project_id = :pid AND status <> 'incomplete' AND duration_ms IS NOT NULL
              AND start_time >= :start AND start_time < :end
            GROUP BY 1 ORDER BY 1
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    recent_failed = (
        db.execute(
            text(
                """
            SELECT trace_id, name, start_time, duration_ms, error_type, error_message
            FROM traces
            WHERE project_id = :pid AND status = 'error' AND start_time >= :start AND start_time < :end
            ORDER BY start_time DESC LIMIT 8
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    slowest = (
        db.execute(
            text(
                """
            SELECT trace_id, name, start_time, duration_ms, status
            FROM traces
            WHERE project_id = :pid AND duration_ms IS NOT NULL AND start_time >= :start AND start_time < :end
            ORDER BY duration_ms DESC LIMIT 8
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    def f(v: Any) -> float | None:
        return float(v) if v is not None else None

    def i(v: Any) -> int | None:
        return int(v) if v is not None else None

    return {
        "range": {"start": start, "end": end, "bucket": trunc},
        "totals": {
            "traces": totals["total"],
            "ok": totals["ok"],
            "error": totals["error"],
            "incomplete": totals["incomplete"],
            "error_rate": (totals["error"] / completed) if completed else None,
            "p50_ms": f(totals["p50"]),
            "p95_ms": f(totals["p95"]),
            "p99_ms": f(totals["p99"]),
            "input_tokens": i(totals["input_tokens"]),
            "output_tokens": i(totals["output_tokens"]),
            "total_tokens": i(totals["total_tokens"]),
            "cost_usd": f(totals["cost_usd"]),
            "unpriced_traces": totals["unpriced_traces"],
        },
        "series": [
            {
                "bucket": r["bucket"],
                "traces": r["total"],
                "errors": r["error"],
                "error_rate": (r["error"] / r["completed"]) if r["completed"] else None,
                "p95_ms": f(r["p95"]),
                "cost_usd": f(r["cost_usd"]),
                "total_tokens": i(r["total_tokens"]),
            }
            for r in series
        ],
        "models": [
            {
                **dict(r),
                "cost_usd": f(r["cost_usd"]),
                "p50_ms": f(r["p50_ms"]),
                "total_tokens": i(r["total_tokens"]),
            }
            for r in models
        ],
        "top_errors": [dict(r) for r in errors],
        "latency_histogram": [
            {
                "lower_ms": round(10 ** ((r["bucket"] - 1) * 0.5)) if r["bucket"] > 0 else 0,
                "upper_ms": round(10 ** (r["bucket"] * 0.5)),
                "count": r["n"],
            }
            for r in histogram
        ],
        "recent_failed": [dict(r) for r in recent_failed],
        "slowest": [dict(r) for r in slowest],
    }
