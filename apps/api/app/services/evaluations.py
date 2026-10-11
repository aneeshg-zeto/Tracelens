from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.redaction import bound_payload
from app.models import EvaluationExample, EvaluationResult, EvaluationRun, Project
from app.services.evaluators import (
    JUDGE_SYSTEM,
    PROBABILISTIC,
    EvaluatorSpec,
    evaluate_deterministic,
    judge_prompt,
)
from app.services.llm import (
    LLMCallError,
    LLMConfig,
    LLMNotConfiguredError,
    complete,
    parse_json,
    resolve_config,
)
from app.services.pricing import compute_cost

logger = logging.getLogger("tracelens.evaluations")
TEMPLATE_VAR = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def render_template(template: str, input_value: Any) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key == "input":
            return input_value if isinstance(input_value, str) else json.dumps(input_value, default=str)
        cur: Any = input_value
        for part in key.removeprefix("input.").split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return "" if cur is None else (cur if isinstance(cur, str) else json.dumps(cur, default=str))

    return TEMPLATE_VAR.sub(repl, template)


def score_example(
    specs: list[EvaluatorSpec],
    input_value: Any,
    output: Any,
    expected: Any,
    judge: LLMConfig | None,
) -> tuple[bool | None, list[dict[str, Any]]]:
    scores: list[dict[str, Any]] = []
    for spec in specs:
        if spec.type in PROBABILISTIC:
            if judge is None:
                scores.append(
                    {
                        "evaluator": spec.type,
                        "probabilistic": True,
                        "passed": None,
                        "score": None,
                        "detail": "LLM judge not configured",
                    }
                )
                continue
            try:
                resp = complete(
                    judge,
                    system=JUDGE_SYSTEM,
                    user=judge_prompt(spec.config["criteria"], input_value, output, expected),
                    json_mode=True,
                    max_tokens=300,
                )
                parsed = parse_json(resp.text)
                score = max(0.0, min(1.0, float(parsed.get("score", 0))))
                threshold = float(spec.config.get("threshold", 0.7))
                scores.append(
                    {
                        "evaluator": spec.type,
                        "probabilistic": True,
                        "passed": score >= threshold,
                        "score": round(score, 4),
                        "detail": str(parsed.get("reason", ""))[:500],
                        "judge_model": judge.model,
                    }
                )
            except (LLMCallError, ValueError, TypeError) as exc:
                scores.append(
                    {
                        "evaluator": spec.type,
                        "probabilistic": True,
                        "passed": None,
                        "score": None,
                        "detail": f"judge failed: {str(exc)[:300]}",
                    }
                )
        else:
            scores.append(evaluate_deterministic(spec, output, expected))
    verdicts = [s["passed"] for s in scores if s["passed"] is not None]
    return (all(verdicts) if verdicts else None), scores


def summarize(db: Session, run: EvaluationRun) -> dict[str, Any]:
    results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id)))
    total = len(results)
    errored = sum(1 for r in results if r.error)
    passed = sum(1 for r in results if r.passed is True)
    failed = sum(1 for r in results if r.passed is False)
    graded = passed + failed
    latencies = sorted(r.latency_ms for r in results if r.latency_ms is not None)
    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    p95 = latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))] if latencies else None
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "ungraded": total - graded - errored if total - graded - errored > 0 else 0,
        "pass_rate": (passed / graded) if graded else None,
        "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "p95_latency_ms": p95,
        "total_cost_usd": float(sum(costs, Decimal(0))) if costs else None,
        "cost_complete": bool(costs) and len(costs) == total,
        "input_tokens": sum(r.input_tokens or 0 for r in results) or None,
        "output_tokens": sum(r.output_tokens or 0 for r in results) or None,
        "has_probabilistic": any(e.get("type") in PROBABILISTIC for e in run.evaluators),
    }


def upsert_result(db: Session, row: dict[str, Any]) -> None:
    stmt = insert(EvaluationResult.__table__).values(row)
    db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_evaluation_results_run_example",
            set_={k: stmt.excluded[k] for k in row if k not in ("run_id", "example_id")},
        )
    )


def record_submitted_results(
    db: Session, run: EvaluationRun, project: Project, items: list[dict[str, Any]]
) -> None:
    """Score outputs produced by the user's own code (SDK target)."""
    specs = [EvaluatorSpec(**e) for e in run.evaluators]
    examples = {
        e.id: e
        for e in db.scalars(select(EvaluationExample).where(EvaluationExample.dataset_id == run.dataset_id))
    }
    judge = None
    if any(s.type in PROBABILISTIC for s in specs):
        try:
            judge = resolve_config(db, project.id)
        except LLMNotConfiguredError:
            judge = None
    for item in items:
        ex = examples.get(item["example_id"])
        if ex is None:
            continue
        passed, scores = (
            (None, [])
            if item.get("error")
            else score_example(specs, ex.input, item.get("output"), ex.expected_output, judge)
        )
        upsert_result(
            db,
            {
                "run_id": run.id,
                "example_id": ex.id,
                "output": bound_payload(item.get("output")),
                "passed": passed,
                "scores": scores,
                "latency_ms": item.get("latency_ms"),
                "input_tokens": item.get("input_tokens"),
                "output_tokens": item.get("output_tokens"),
                "cost_usd": item.get("cost_usd"),
                "error": (str(item["error"])[:2000] if item.get("error") else None),
                "trace_id": item.get("trace_id"),
            },
        )
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    db.flush()
    run.summary = summarize(db, run)
    db.commit()


def execute_model_run(db: Session, run_id: uuid.UUID) -> None:
    """Background job: call the configured model for every example, then score."""
    run = db.get(EvaluationRun, run_id)
    if run is None or run.status not in ("queued", "running"):
        return
    run.status = "running"
    run.started_at = datetime.now(UTC)
    db.commit()
    try:
        cfg = run.target_config
        config = resolve_config(db, run.project_id, cfg.get("provider"), cfg.get("model"))
        specs = [EvaluatorSpec(**e) for e in run.evaluators]
        judge = config if any(s.type in PROBABILISTIC for s in specs) else None
        examples = list(
            db.scalars(
                select(EvaluationExample)
                .where(EvaluationExample.dataset_id == run.dataset_id)
                .order_by(EvaluationExample.created_at)
                .limit(500)
            )
        )
        system = cfg.get("system_prompt") or "You are a helpful assistant."
        for ex in examples:
            prompt = render_template(cfg.get("prompt_template") or "{{input}}", ex.input)
            row: dict[str, Any] = {"run_id": run.id, "example_id": ex.id}
            try:
                resp = complete(
                    config,
                    system=system,
                    user=prompt,
                    json_mode=bool(cfg.get("json_output")),
                    max_tokens=int(cfg.get("max_tokens", 800)),
                )
                output: Any = resp.text
                if cfg.get("json_output"):
                    try:
                        output = json.loads(resp.text)
                    except json.JSONDecodeError:
                        output = resp.text
                cost = compute_cost(
                    provider=config.provider,
                    model=config.model,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cached_tokens=resp.cached_tokens,
                    reported_cost=None,
                )
                passed, scores = score_example(specs, ex.input, output, ex.expected_output, judge)
                row.update(
                    output=bound_payload(output),
                    passed=passed,
                    scores=scores,
                    latency_ms=resp.latency_ms,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cost_usd=cost.cost_usd,
                    error=None,
                )
            except LLMCallError as exc:
                row.update(output=None, passed=None, scores=[], error=str(exc)[:2000])
            upsert_result(db, row)
            db.commit()
        run.status = "completed"
    except LLMNotConfiguredError as exc:
        run.status = "failed"
        run.error = str(exc)
    run.completed_at = datetime.now(UTC)
    db.flush()
    run.summary = summarize(db, run)
    db.commit()


def compare_runs(db: Session, base: EvaluationRun, candidate: EvaluationRun) -> dict[str, Any]:
    def by_example(run: EvaluationRun) -> dict[uuid.UUID, EvaluationResult]:
        return {
            r.example_id: r
            for r in db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run.id))
        }

    a, b = by_example(base), by_example(candidate)
    examples = {
        e.id: e
        for e in db.scalars(select(EvaluationExample).where(EvaluationExample.dataset_id == base.dataset_id))
    }
    rows = []
    counts = {"regressed": 0, "fixed": 0, "unchanged_pass": 0, "unchanged_fail": 0, "other": 0}
    for ex_id in sorted(set(a) | set(b), key=str):
        ra, rb = a.get(ex_id), b.get(ex_id)
        pa = ra.passed if ra else None
        pb = rb.passed if rb else None
        if pa is True and pb is False:
            change = "regressed"
        elif pa is False and pb is True:
            change = "fixed"
        elif pa is True and pb is True:
            change = "unchanged_pass"
        elif pa is False and pb is False:
            change = "unchanged_fail"
        else:
            change = "other"
        counts[change] += 1
        ex = examples.get(ex_id)
        rows.append(
            {
                "example_id": str(ex_id),
                "input": ex.input if ex else None,
                "expected_output": ex.expected_output if ex else None,
                "base": {
                    "passed": pa,
                    "output": ra.output if ra else None,
                    "latency_ms": ra.latency_ms if ra else None,
                    "error": ra.error if ra else None,
                },
                "candidate": {
                    "passed": pb,
                    "output": rb.output if rb else None,
                    "latency_ms": rb.latency_ms if rb else None,
                    "error": rb.error if rb else None,
                },
                "change": change,
            }
        )

    def delta(key: str) -> float | None:
        x, y = base.summary.get(key), candidate.summary.get(key)
        return (y - x) if isinstance(x, int | float) and isinstance(y, int | float) else None

    return {
        "base": {"id": str(base.id), "name": base.name, "summary": base.summary},
        "candidate": {"id": str(candidate.id), "name": candidate.name, "summary": candidate.summary},
        "deltas": {
            "pass_rate": delta("pass_rate"),
            "avg_latency_ms": delta("avg_latency_ms"),
            "p95_latency_ms": delta("p95_latency_ms"),
            "total_cost_usd": delta("total_cost_usd"),
        },
        "counts": counts,
        "rows": sorted(
            rows,
            key=lambda r: ["regressed", "fixed", "unchanged_fail", "other", "unchanged_pass"].index(
                r["change"]
            ),
        ),
    }
