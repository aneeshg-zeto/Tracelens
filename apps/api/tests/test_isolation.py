"""Tenant isolation and role enforcement."""

from __future__ import annotations

from typing import Any

from .conftest import Actor, Factory, mint_token, sample_batch


def _ingest(client: Any, key: str, trace_id: str) -> None:
    r = client.post(
        "/api/v1/ingest/batch", json=sample_batch(trace_id), headers={"Authorization": f"Bearer {key}"}
    )
    assert r.status_code == 202, r.text


def test_cross_org_access_is_not_found(client: Any, factory: Factory) -> None:
    alice = factory.org()
    bob = factory.org()
    pa = factory.project(alice, "Alice project")
    pb = factory.project(bob, "Bob project")
    _ingest(client, factory.api_key(alice, pa["id"]), "alice-trace")
    _ingest(client, factory.api_key(bob, pb["id"]), "bob-trace")

    # Bob cannot see Alice's project, traces, keys, or org, even with valid ids.
    for path in (
        f"/api/v1/projects/{pa['id']}",
        f"/api/v1/projects/{pa['id']}/traces",
        f"/api/v1/projects/{pa['id']}/traces/alice-trace",
        f"/api/v1/projects/{pa['id']}/api-keys",
        f"/api/v1/projects/{pa['id']}/analytics/overview",
        f"/api/v1/orgs/{alice.org_id}/projects",
        f"/api/v1/orgs/{alice.org_id}/audit-events",
    ):
        r = client.get(path, headers=bob.headers)
        assert r.status_code == 404, (path, r.status_code)

    # Bob's own project never contains Alice's trace.
    ids = [
        t["trace_id"]
        for t in client.get(f"/api/v1/projects/{pb['id']}/traces", headers=bob.headers).json()["items"]
    ]
    assert ids == ["bob-trace"]
    assert (
        client.get(f"/api/v1/projects/{pb['id']}/traces/alice-trace", headers=bob.headers).status_code == 404
    )


def test_api_key_scoped_to_its_project(client: Any, factory: Factory, owner: Actor) -> None:
    p1 = factory.project(owner, "One")
    p2 = factory.project(owner, "Two")
    _ingest(client, factory.api_key(owner, p1["id"]), "only-in-one")
    assert (
        client.get(f"/api/v1/projects/{p2['id']}/traces/only-in-one", headers=owner.headers).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/projects/{p1['id']}/traces/only-in-one", headers=owner.headers).status_code
        == 200
    )


def test_token_org_must_match_path(client: Any, factory: Factory) -> None:
    alice = factory.org()
    other_org = factory.org()
    # Alice is also a member of the other org, but her token's active org is her own.
    factory.member(other_org.org_id, "owner", user_id=alice.user_id)
    p = factory.project(other_org)
    assert client.get(f"/api/v1/projects/{p['id']}", headers=alice.headers).status_code == 404
    switched = {"X-TraceLens-Internal-Token": mint_token(alice.user_id, other_org.org_id)}
    assert client.get(f"/api/v1/projects/{p['id']}", headers=switched).status_code == 200


def test_forged_org_claim_without_membership(client: Any, factory: Factory) -> None:
    alice = factory.org()
    mallory = factory.org()
    p = factory.project(alice)
    forged = {"X-TraceLens-Internal-Token": mint_token(mallory.user_id, alice.org_id)}
    assert client.get(f"/api/v1/projects/{p['id']}", headers=forged).status_code == 404
    assert client.get(f"/api/v1/orgs/{alice.org_id}/projects", headers=forged).status_code == 404


def test_missing_or_invalid_internal_token(client: Any, project: dict[str, Any]) -> None:
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 401
    bad = {"X-TraceLens-Internal-Token": mint_token("u", "o", secret="y" * 40)}
    assert client.get(f"/api/v1/projects/{project['id']}", headers=bad).status_code == 401


def test_role_matrix_enforced(client: Any, factory: Factory, owner: Actor, project: dict[str, Any]) -> None:
    pid = project["id"]
    admin = factory.member(owner.org_id, "admin")
    member = factory.member(owner.org_id, "member")
    viewer = factory.member(owner.org_id, "viewer")

    assert (
        client.post(
            f"/api/v1/orgs/{owner.org_id}/projects", json={"name": "v"}, headers=viewer.headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/orgs/{owner.org_id}/projects", json={"name": "m"}, headers=member.headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/orgs/{owner.org_id}/projects", json={"name": "a"}, headers=admin.headers
        ).status_code
        == 201
    )

    assert (
        client.patch(
            f"/api/v1/projects/{pid}", json={"retention_days": 7}, headers=member.headers
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/api/v1/projects/{pid}", json={"retention_days": 7}, headers=admin.headers).status_code
        == 200
    )

    assert (
        client.post(
            f"/api/v1/projects/{pid}/api-keys", json={"name": "k"}, headers=viewer.headers
        ).status_code
        == 403
    )
    assert (
        client.post(f"/api/v1/projects/{pid}/api-keys", json={"name": "k"}, headers=admin.headers).status_code
        == 201
    )

    assert client.get(f"/api/v1/orgs/{owner.org_id}/audit-events", headers=member.headers).status_code == 403
    assert client.get(f"/api/v1/orgs/{owner.org_id}/audit-events", headers=admin.headers).status_code == 200

    assert client.get(f"/api/v1/projects/{pid}/traces", headers=viewer.headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/projects/{pid}/evaluations/datasets", json={"name": "d"}, headers=viewer.headers
        ).status_code
        == 403
    )

    assert client.delete(f"/api/v1/projects/{pid}", headers=admin.headers).status_code == 403
    assert client.delete(f"/api/v1/projects/{pid}", headers=owner.headers).status_code == 204


def test_audit_log_records_sensitive_actions(
    client: Any, owner: Actor, project: dict[str, Any], api_key: str
) -> None:
    events = client.get(f"/api/v1/orgs/{owner.org_id}/audit-events", headers=owner.headers).json()["items"]
    actions = {e["action"] for e in events}
    assert {"project.created", "api_key.created"} <= actions
    assert all(api_key not in str(e) for e in events)
