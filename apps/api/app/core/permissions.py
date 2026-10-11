"""Role permission matrix. Mirrors apps/web/lib/auth/permissions.ts; keep both in sync."""

from __future__ import annotations

from typing import Literal

Role = Literal["owner", "admin", "member", "viewer"]

PERMISSIONS: dict[str, dict[str, frozenset[str]]] = {
    "owner": {
        "project": frozenset({"create", "update", "delete"}),
        "apiKey": frozenset({"create", "revoke"}),
        "trace": frozenset({"read", "ingest", "delete"}),
        "evaluation": frozenset({"read", "create", "run"}),
        "prompt": frozenset({"read", "create", "publish"}),
        "integration": frozenset({"read", "update"}),
        "audit": frozenset({"read"}),
        "investigation": frozenset({"read", "run"}),
    },
    "admin": {
        "project": frozenset({"create", "update"}),
        "apiKey": frozenset({"create", "revoke"}),
        "trace": frozenset({"read", "ingest", "delete"}),
        "evaluation": frozenset({"read", "create", "run"}),
        "prompt": frozenset({"read", "create", "publish"}),
        "integration": frozenset({"read", "update"}),
        "audit": frozenset({"read"}),
        "investigation": frozenset({"read", "run"}),
    },
    "member": {
        "trace": frozenset({"read", "ingest"}),
        "evaluation": frozenset({"read", "create", "run"}),
        "prompt": frozenset({"read", "create"}),
        "integration": frozenset({"read"}),
        "investigation": frozenset({"read", "run"}),
    },
    "viewer": {
        "trace": frozenset({"read"}),
        "evaluation": frozenset({"read"}),
        "prompt": frozenset({"read"}),
        "integration": frozenset({"read"}),
        "investigation": frozenset({"read"}),
    },
}


def has_permission(role: str | None, resource: str, action: str) -> bool:
    if not role:
        return False
    # Better Auth stores multiple roles as a comma-separated string.
    for r in (part.strip() for part in role.split(",")):
        if action in PERMISSIONS.get(r, {}).get(resource, frozenset()):
            return True
    return False


def role_permissions(role: str | None) -> dict[str, list[str]]:
    result: dict[str, set[str]] = {}
    for r in (part.strip() for part in (role or "").split(",") if part.strip()):
        for resource, actions in PERMISSIONS.get(r, {}).items():
            result.setdefault(resource, set()).update(actions)
    return {k: sorted(v) for k, v in result.items()}
