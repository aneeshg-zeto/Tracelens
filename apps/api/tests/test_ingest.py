from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.models import ApiKey, Span

from .conftest import Actor, Factory, iso, sample_batch


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_requires_api_key(client: Any) -> None:
    r = client.post("/api/v1/ingest/batch", json=sample_batch())
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_rejects_unknown_key(client: Any) -> None:
    r = client.post("/api/v1/ingest/batch", json=sample_batch(), headers=_auth("tl_live_" + "x" * 43))
    assert r.status_code == 401


def test_x_api_key_header_supported(client: Any, api_key: str) -> None:
    r = client.get("/api/v1/ingest/whoami", headers={"X-TraceLens-Api-Key": api_key})
    assert r.status_code == 200
    assert r.json()["key_prefix"] == api_key[:14]


def test_ingest_and_read_back(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    r = client.post("/api/v1/ingest/batch", json=sample_batch(), headers=_auth(api_key))
    assert r.status_code == 202, r.text
    assert r.json() == {"accepted_traces": 1, "accepted_spans": 3, "trace_ids": ["trace-1"]}
    assert "X-RateLimit-Remaining" in r.headers

    detail = client.get(f"/api/v1/projects/{project['id']}/traces/trace-1", headers=owner.headers).json()
    trace = detail["trace"]
    assert trace["status"] == "ok"
    assert trace["span_count"] == 3
    assert trace["duration_ms"] == 3000
    assert trace["input_tokens"] == 1000 and trace["output_tokens"] == 200 and trace["total_tokens"] == 1200
    assert trace["models"] == ["gpt-4o-mini"] and trace["providers"] == ["openai"]
    # gpt-4o-mini list price: $0.15 / 1M input, $0.60 / 1M output.
    assert trace["cost_usd"] == pytest.approx(1000 * 0.15e-6 + 200 * 0.60e-6)
    assert trace["cost_status"] == "calculated"
    assert trace["root_span_id"] == "trace-1-root"
    # Payload capture is off by default: only a shape summary is stored.
    assert trace["input"] == {"_captured": False, "type": "object", "keys": 1}

    by_id = {s["span_id"]: s for s in detail["spans"]}
    assert by_id["trace-1-llm"]["parent_span_id"] == "trace-1-root"
    assert by_id["trace-1-tool"]["parent_span_id"] == "trace-1-root"
    assert by_id["trace-1-root"]["parent_span_id"] is None
    assert "input" not in by_id["trace-1-llm"]  # skeletons carry no payloads


def test_payload_capture_redacts(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"capture_payloads": True}, headers=owner.headers
    )
    assert r.status_code == 200 and r.json()["capture_payloads"] is True
    batch = sample_batch()
    batch["spans"][1]["input"] = [{"role": "user", "content": "key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWX"}]
    batch["spans"][1]["attributes"] = {"api_key": "plain", "temperature": 0.2}
    client.post("/api/v1/ingest/batch", json=batch, headers=_auth(api_key))
    span = client.get(
        f"/api/v1/projects/{project['id']}/traces/trace-1/spans/trace-1-llm", headers=owner.headers
    ).json()
    assert "sk-proj" not in span["input"][0]["content"]
    assert span["attributes"] == {"api_key": "[REDACTED]", "temperature": 0.2}


def test_duplicate_batches_are_idempotent(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str, db: Any
) -> None:
    for _ in range(3):
        assert (
            client.post("/api/v1/ingest/batch", json=sample_batch(), headers=_auth(api_key)).status_code
            == 202
        )
    trace = client.get(f"/api/v1/projects/{project['id']}/traces/trace-1", headers=owner.headers).json()[
        "trace"
    ]
    assert trace["span_count"] == 3 and trace["total_tokens"] == 1200
    assert len(db.scalars(select(Span.id)).all()) == 3


def test_spans_before_trace_create_incomplete_placeholder(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    batch = sample_batch("late")
    spans_only = {"spans": [batch["spans"][2], batch["spans"][1]]}  # children first, no root yet
    assert client.post("/api/v1/ingest/batch", json=spans_only, headers=_auth(api_key)).status_code == 202
    t = client.get(f"/api/v1/projects/{project['id']}/traces/late", headers=owner.headers).json()["trace"]
    assert t["status"] == "incomplete" and t["span_count"] == 2

    assert client.post("/api/v1/ingest/batch", json=batch, headers=_auth(api_key)).status_code == 202
    t = client.get(f"/api/v1/projects/{project['id']}/traces/late", headers=owner.headers).json()["trace"]
    assert t["status"] == "ok" and t["span_count"] == 3 and t["name"] == "answer-question"


def test_unknown_model_cost_unavailable(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    batch = sample_batch()
    batch["spans"][1]["model"] = "my-private-model"
    batch["spans"][1]["provider"] = "self-hosted"
    client.post("/api/v1/ingest/batch", json=batch, headers=_auth(api_key))
    t = client.get(f"/api/v1/projects/{project['id']}/traces/trace-1", headers=owner.headers).json()["trace"]
    assert t["cost_usd"] is None and t["cost_status"] == "unavailable"
    assert t["total_tokens"] == 1200


def test_reported_cost_is_used(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    batch = sample_batch()
    batch["spans"][1]["cost_usd"] = 0.5
    client.post("/api/v1/ingest/batch", json=batch, headers=_auth(api_key))
    span = client.get(
        f"/api/v1/projects/{project['id']}/traces/trace-1/spans/trace-1-llm", headers=owner.headers
    ).json()
    assert span["cost_usd"] == 0.5 and span["cost_status"] == "reported"


def _ts(minutes: int = 0) -> str:
    return iso(datetime.now(UTC) + timedelta(minutes=minutes))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"traces": [], "spans": []},
        {"traces": [{"trace_id": "a", "name": "x"}]},  # missing start_time
        {"traces": [{"trace_id": "bad id with spaces", "name": "x", "start_time": _ts()}]},
        {"traces": [{"trace_id": "a", "name": "x", "start_time": _ts(), "end_time": _ts(-10)}]},
        {"traces": [{"trace_id": "a", "name": "x", "start_time": _ts(24 * 60)}]},
        {"spans": [{"trace_id": "a", "span_id": "s", "name": "x", "kind": "weird", "start_time": _ts()}]},
        {
            "spans": [
                {"trace_id": "a", "span_id": "s", "parent_span_id": "s", "name": "x", "start_time": _ts()}
            ]
        },
        {
            "spans": [
                {
                    "trace_id": "a",
                    "span_id": "s",
                    "name": "x",
                    "start_time": _ts(),
                    "usage": {"input_tokens": -1},
                }
            ]
        },
        {"traces": [], "unexpected": True},
    ],
)
def test_invalid_payloads_rejected(client: Any, api_key: str, payload: dict[str, Any]) -> None:
    r = client.post("/api/v1/ingest/batch", json=payload, headers=_auth(api_key))
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"


def test_oversized_body_rejected(client: Any, api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'{"traces": [], "pad": "' + b"x" * (6 * 1024 * 1024) + b'"}'
    r = client.post(
        "/api/v1/ingest/batch", content=body, headers={**_auth(api_key), "Content-Type": "application/json"}
    )
    assert r.status_code == 413


def test_revoked_key_rejected(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str, db: Any
) -> None:
    key_id = db.scalar(select(ApiKey.id))
    r = client.post(f"/api/v1/projects/{project['id']}/api-keys/{key_id}/revoke", headers=owner.headers)
    assert r.status_code == 200 and r.json()["revoked_at"]
    r = client.post("/api/v1/ingest/batch", json=sample_batch(), headers=_auth(api_key))
    assert r.status_code == 401 and "revoked" in r.json()["error"]["message"]


def test_expired_key_rejected(client: Any, api_key: str, db: Any) -> None:
    db.execute(update(ApiKey).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    db.commit()
    r = client.post("/api/v1/ingest/batch", json=sample_batch(), headers=_auth(api_key))
    assert r.status_code == 401 and "expired" in r.json()["error"]["message"]


def test_key_listing_never_returns_secret(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    keys = client.get(f"/api/v1/projects/{project['id']}/api-keys", headers=owner.headers).json()
    assert len(keys) == 1 and "secret" not in keys[0] and keys[0]["key_prefix"] == api_key[:14]


def test_rate_limit(client: Any, api_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ingest_rate_limit_per_minute", 3)
    codes = [client.get("/api/v1/ingest/whoami", headers=_auth(api_key)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = client.get("/api/v1/ingest/whoami", headers=_auth(api_key))
    assert r.headers["Retry-After"] and r.json()["error"]["code"] == "rate_limited"


def test_trace_list_filters_and_pagination(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    traces, spans = [], []
    for i in range(7):
        b = sample_batch(f"t{i}", error=(i % 3 == 0), base=base + timedelta(minutes=i))
        traces += b["traces"]
        spans += b["spans"]
    client.post("/api/v1/ingest/batch", json={"traces": traces, "spans": spans}, headers=_auth(api_key))
    url = f"/api/v1/projects/{project['id']}/traces"

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = client.get(url, params=params, headers=owner.headers).json()
        seen += [t["trace_id"] for t in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [f"t{i}" for i in reversed(range(7))]
    assert page["total"] == 7

    errors = client.get(url, params={"status": "error"}, headers=owner.headers).json()
    assert sorted(t["trace_id"] for t in errors["items"]) == ["t0", "t3", "t6"]
    assert client.get(url, params={"q": "t4"}, headers=owner.headers).json()["items"][0]["trace_id"] == "t4"
    assert client.get(url, params={"model": "gpt-4o-mini"}, headers=owner.headers).json()["total"] == 7
    assert client.get(url, params={"model": "other"}, headers=owner.headers).json()["total"] == 0

    by_dur = client.get(url, params={"sort": "duration_ms", "limit": 4}, headers=owner.headers).json()
    nxt = client.get(
        url,
        params={"sort": "duration_ms", "limit": 4, "cursor": by_dur["next_cursor"]},
        headers=owner.headers,
    ).json()
    assert len({t["trace_id"] for t in by_dur["items"] + nxt["items"]}) == 7

    assert client.get(url, params={"cursor": "garbage"}, headers=owner.headers).status_code == 400


def test_single_trace_endpoint(client: Any, owner: Actor, project: dict[str, Any], api_key: str) -> None:
    trace = sample_batch()["traces"][0]
    r = client.post("/api/v1/traces", json=trace, headers=_auth(api_key))
    assert r.status_code == 202 and r.json()["accepted_traces"] == 1


def test_member_role_can_view_but_not_manage_keys(
    client: Any, factory: Factory, owner: Actor, project: dict[str, Any]
) -> None:
    member = factory.member(owner.org_id, "member")
    url = f"/api/v1/projects/{project['id']}/api-keys"
    assert client.post(url, json={"name": "nope"}, headers=member.headers).status_code == 403
    assert client.get(f"/api/v1/projects/{project['id']}/traces", headers=member.headers).status_code == 200
