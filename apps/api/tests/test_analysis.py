"""Diagnosis, analytics, evaluations, prompts, integrations, and retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.models import Project, Trace
from app.services.retention import purge_expired

from .conftest import Actor, iso, sample_batch


def _ingest(client: Any, key: str, batch: dict[str, Any]) -> None:
    r = client.post("/api/v1/ingest/batch", json=batch, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 202, r.text


def test_diagnosis_points_at_failing_tool(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    _ingest(client, api_key, sample_batch("bad", error=True))
    base = f"/api/v1/projects/{project['id']}/traces/bad"
    findings = client.get(f"{base}/diagnosis", headers=owner.headers).json()["findings"]
    rules = {f["rule"] for f in findings}
    assert "failed_span" in rules and "timeout" in rules
    failed = next(f for f in findings if f["rule"] == "failed_span")
    assert failed["span_ids"][0] == "bad-tool"

    inv = client.post(f"{base}/investigations", json={"mode": "deterministic"}, headers=owner.headers)
    assert inv.status_code == 201 and inv.json()["status"] == "completed"
    assert len(client.get(f"{base}/investigations", headers=owner.headers).json()) == 1


def test_ai_investigation_requires_configuration(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    _ingest(client, api_key, sample_batch("bad", error=True))
    r = client.post(
        f"/api/v1/projects/{project['id']}/traces/bad/investigations",
        json={"mode": "ai"},
        headers=owner.headers,
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "llm_not_configured"


def test_analytics_overview_from_real_data(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    empty = client.get(f"/api/v1/projects/{project['id']}/analytics/overview", headers=owner.headers).json()
    assert empty["totals"]["traces"] == 0

    _ingest(client, api_key, sample_batch("ok1"))
    _ingest(client, api_key, sample_batch("ok2"))
    _ingest(client, api_key, sample_batch("err", error=True))
    data = client.get(f"/api/v1/projects/{project['id']}/analytics/overview", headers=owner.headers).json()
    totals = data["totals"]
    assert totals["traces"] == 3 and totals["error"] == 1
    assert abs(totals["error_rate"] - 1 / 3) < 1e-9
    assert totals["total_tokens"] == 3600
    assert totals["p50_ms"] == 3000
    assert sum(b["traces"] for b in data["series"]) == 3
    assert data["models"][0]["model"] == "gpt-4o-mini" and data["models"][0]["calls"] == 3
    assert "TimeoutError" in {e["error_type"] for e in data["top_errors"]}
    assert [t["trace_id"] for t in data["recent_failed"]] == ["err"]
    assert sum(b["count"] for b in data["latency_histogram"]) == 3

    bad = client.get(
        f"/api/v1/projects/{project['id']}/analytics/overview",
        params={"start": iso(datetime.now(UTC)), "end": iso(datetime.now(UTC) - timedelta(hours=1))},
        headers=owner.headers,
    )
    assert bad.status_code == 400


def test_sdk_evaluation_run_and_compare(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    base = f"/api/v1/projects/{project['id']}/evaluations"
    ds = client.post(f"{base}/datasets", json={"name": "faq"}, headers=owner.headers).json()
    assert client.post(f"{base}/datasets", json={"name": "faq"}, headers=owner.headers).status_code == 409
    examples = client.post(
        f"{base}/datasets/{ds['id']}/examples",
        json={
            "examples": [
                {"input": "2+2", "expected_output": "4"},
                {"input": "capital of France", "expected_output": "Paris"},
            ]
        },
        headers=owner.headers,
    ).json()
    ex_ids = [e["id"] for e in examples]

    auth = {"Authorization": f"Bearer {api_key}"}
    fetched = client.get("/api/v1/ingest/evaluations/datasets/faq", headers=auth).json()
    assert [e["id"] for e in fetched["examples"]] == ex_ids

    evaluators = [{"type": "normalized_match"}]
    run_a = client.post(
        "/api/v1/ingest/evaluations/runs",
        headers=auth,
        json={
            "dataset": "faq",
            "name": "v1",
            "evaluators": evaluators,
            "results": [
                {"example_id": ex_ids[0], "output": "4", "latency_ms": 100},
                {"example_id": ex_ids[1], "output": "Lyon", "latency_ms": 200},
            ],
        },
    )
    assert run_a.status_code == 201, run_a.text
    a = run_a.json()
    assert a["status"] == "completed" and a["summary"]["passed"] == 1 and a["summary"]["failed"] == 1
    assert a["makes_external_calls"] is False

    b = client.post(
        "/api/v1/ingest/evaluations/runs",
        headers=auth,
        json={
            "dataset": "faq",
            "name": "v2",
            "evaluators": evaluators,
            "results": [
                {"example_id": ex_ids[0], "output": "five", "latency_ms": 90},
                {"example_id": ex_ids[1], "output": " paris. ", "latency_ms": 150},
            ],
        },
    ).json()

    detail = client.get(f"{base}/runs/{a['id']}", headers=owner.headers).json()
    assert len(detail["results"]) == 2

    cmp = client.get(
        f"{base}/compare", params={"base": a["id"], "candidate": b["id"]}, headers=owner.headers
    ).json()
    assert cmp["counts"]["regressed"] == 1 and cmp["counts"]["fixed"] == 1
    assert cmp["rows"][0]["change"] == "regressed"
    assert cmp["deltas"]["avg_latency_ms"] == -30


def test_model_run_requires_acknowledgement(client: Any, owner: Actor, project: dict[str, Any]) -> None:
    base = f"/api/v1/projects/{project['id']}/evaluations"
    ds = client.post(f"{base}/datasets", json={"name": "d"}, headers=owner.headers).json()
    client.post(
        f"{base}/datasets/{ds['id']}/examples", json={"examples": [{"input": "x"}]}, headers=owner.headers
    )
    body = {"name": "r", "target": {"type": "model"}, "evaluators": [{"type": "contains"}]}
    r = client.post(f"{base}/datasets/{ds['id']}/runs", json=body, headers=owner.headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "confirmation_required"
    r = client.post(
        f"{base}/datasets/{ds['id']}/runs",
        json={**body, "acknowledge_external_calls": True},
        headers=owner.headers,
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "llm_not_configured"


def test_invalid_evaluator_rejected(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    r = client.post(
        "/api/v1/ingest/evaluations/runs",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "dataset": "x",
            "name": "n",
            "evaluators": [{"type": "json_schema", "config": {"schema": "nope"}}],
            "results": [{"example_id": "00000000-0000-0000-0000-000000000000"}],
        },
    )
    assert r.status_code == 422


def test_prompt_versioning(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    base = f"/api/v1/projects/{project['id']}/prompts"
    p = client.post(
        base,
        json={"name": "support.system", "content": "Hello {{ name }}, about {{topic}}"},
        headers=owner.headers,
    ).json()
    assert p["versions"][0]["variables"] == ["name", "topic"] and p["active_version"] is None

    auth = {"Authorization": f"Bearer {api_key}"}
    assert client.get("/api/v1/ingest/prompts/support.system", headers=auth).status_code == 404

    assert (
        client.patch(
            f"{base}/{p['id']}/versions/1", json={"content": "Hi {{name}}"}, headers=owner.headers
        ).status_code
        == 200
    )
    p = client.post(f"{base}/{p['id']}/versions/1/publish", headers=owner.headers).json()
    assert p["active_version"] == 1
    r = client.patch(f"{base}/{p['id']}/versions/1", json={"content": "changed"}, headers=owner.headers)
    assert r.status_code == 409

    client.post(f"{base}/{p['id']}/versions", json={"content": "v2 {{name}}"}, headers=owner.headers)
    p = client.post(f"{base}/{p['id']}/versions/2/publish", headers=owner.headers).json()
    assert p["active_version"] == 2
    assert client.get("/api/v1/ingest/prompts/support.system", headers=auth).json()["version"] == 2

    p = client.post(f"{base}/{p['id']}/activate", json={"version": 1}, headers=owner.headers).json()
    assert p["active_version"] == 1
    fetched = client.get("/api/v1/ingest/prompts/support.system", headers=auth).json()
    assert fetched == {
        "name": "support.system",
        "version": 1,
        "content": "Hi {{name}}",
        "variables": ["name"],
    }

    batch = sample_batch("prompted")
    batch["spans"][1]["attributes"] = {
        "tracelens.prompt.name": "support.system",
        "tracelens.prompt.version": "1",
    }
    _ingest(client, api_key, batch)
    linked = client.get(f"{base}/{p['id']}/versions/1/traces", headers=owner.headers).json()
    assert [t["trace_id"] for t in linked] == ["prompted"]

    member_headers = owner.headers
    assert (
        client.post(base, json={"name": "support.system", "content": "x"}, headers=member_headers).status_code
        == 409
    )


def test_integrations_evidence_from_data(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    url = f"/api/v1/projects/{project['id']}/integrations"
    items = {i["id"]: i for i in client.get(url, headers=owner.headers).json()["items"]}
    assert not items["openai"]["receiving_data"] and items["langfuse"]["status"] == "not_implemented"

    batch = sample_batch()
    batch["spans"][1]["attributes"] = {"tracelens.integration": "openai"}
    _ingest(client, api_key, batch)
    items = {i["id"]: i for i in client.get(url, headers=owner.headers).json()["items"]}
    assert items["openai"]["receiving_data"] and items["openai"]["data"]["count"] == 1
    assert items["python-sdk"]["receiving_data"]
    assert not items["anthropic"]["receiving_data"]


def test_retention_purges_only_expired(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str, db: Any
) -> None:
    old = datetime.now(UTC) - timedelta(days=40)
    _ingest(client, api_key, sample_batch("old"))
    _ingest(client, api_key, sample_batch("new"))
    db.execute(update(Trace).where(Trace.trace_id == "old").values(start_time=old))
    db.commit()
    assert db.scalar(select(Project.retention_days)) == 30
    assert purge_expired(db) == 1
    remaining = db.scalars(select(Trace.trace_id)).all()
    assert remaining == ["new"]


def test_onboarding_tracks_first_trace(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    r = client.get("/api/v1/onboarding", headers=owner.headers)
    assert r.status_code == 200 and r.json()["project_id"] is None
    r = client.put(
        "/api/v1/onboarding",
        json={"organization_id": owner.org_id, "project_id": project["id"], "complete_step": "project"},
        headers=owner.headers,
    )
    assert r.status_code == 200 and r.json()["completed_steps"] == ["project"]
    assert r.json()["first_trace_received"] is False
    _ingest(client, api_key, sample_batch())
    assert client.get("/api/v1/onboarding", headers=owner.headers).json()["first_trace_received"] is True
