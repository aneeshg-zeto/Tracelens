from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, Path, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, forbidden, not_found, unauthorized
from app.core.permissions import has_permission
from app.core.rate_limit import RateLimiter, get_rate_limiter
from app.core.security import (
    InternalPrincipal,
    InternalTokenError,
    hash_api_key,
    hashes_match,
    looks_like_api_key,
    verify_internal_token,
)
from app.db.session import get_db
from app.models import ApiKey, Member, Project

DB = Annotated[Session, Depends(get_db)]

INTERNAL_TOKEN_HEADER = "X-TraceLens-Internal-Token"  # noqa: S105 - header name
LAST_USED_RESOLUTION = timedelta(minutes=1)


# --- Ingestion (project API keys) --------------------------------------------


@dataclass(frozen=True)
class IngestContext:
    project: Project
    api_key: ApiKey


def _extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(
    db: DB,
    request: Request,
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
    x_tracelens_api_key: Annotated[str | None, Header()] = None,
) -> IngestContext:
    raw = _extract_api_key(authorization, x_tracelens_api_key)
    if not raw or not looks_like_api_key(raw):
        raise unauthorized("A valid TraceLens project API key is required")
    digest = hash_api_key(raw)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == digest))
    if key is None or not hashes_match(key.key_hash, digest):
        raise unauthorized("Invalid API key")
    now = datetime.now(UTC)
    if key.revoked_at is not None:
        raise unauthorized("API key has been revoked")
    if key.expires_at is not None and key.expires_at <= now:
        raise unauthorized("API key has expired")

    limit = get_settings().ingest_rate_limit_per_minute
    result = limiter.hit(f"key:{key.id}", limit)
    request.state.rate_limit = result
    if not result.allowed:
        raise APIError(
            429,
            "rate_limited",
            "Rate limit exceeded for this API key",
            headers={
                "Retry-After": str(result.reset_seconds),
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    project = db.get(Project, key.project_id)
    if project is None:
        raise unauthorized("Invalid API key")

    if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
        db.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=now))
        db.commit()
    return IngestContext(project=project, api_key=key)


IngestAuth = Annotated[IngestContext, Depends(require_api_key)]


# --- Dashboard (internal signed tokens) --------------------------------------


def get_principal(
    x_tracelens_internal_token: Annotated[str | None, Header(alias=INTERNAL_TOKEN_HEADER)] = None,
) -> InternalPrincipal:
    if not x_tracelens_internal_token:
        raise unauthorized("Missing internal service token")
    try:
        return verify_internal_token(x_tracelens_internal_token)
    except InternalTokenError as exc:
        raise unauthorized("Invalid internal service token") from exc


Principal = Annotated[InternalPrincipal, Depends(get_principal)]


@dataclass(frozen=True)
class OrgContext:
    user_id: str
    organization_id: str
    role: str

    def require(self, resource: str, action: str) -> None:
        if not has_permission(self.role, resource, action):
            raise forbidden()


@dataclass(frozen=True)
class ProjectContext(OrgContext):
    project: Project


def _membership(db: Session, user_id: str, organization_id: str) -> Member | None:
    return db.scalar(
        select(Member).where(Member.user_id == user_id, Member.organization_id == organization_id)
    )


def get_org_context(
    db: DB,
    principal: Principal,
    org_id: Annotated[str, Path(min_length=1, max_length=128)],
) -> OrgContext:
    # The token's active organization must match the path, and membership is
    # re-verified in the database: a guessed org id from another tenant fails.
    if principal.organization_id != org_id:
        raise not_found("Organization")
    member = _membership(db, principal.user_id, org_id)
    if member is None:
        raise not_found("Organization")
    return OrgContext(user_id=principal.user_id, organization_id=org_id, role=member.role)


def get_project_context(
    db: DB,
    principal: Principal,
    project_id: Annotated[uuid.UUID, Path()],
) -> ProjectContext:
    project = db.get(Project, project_id)
    if project is None or principal.organization_id != project.organization_id:
        raise not_found("Project")
    member = _membership(db, principal.user_id, project.organization_id)
    if member is None:
        raise not_found("Project")
    return ProjectContext(
        user_id=principal.user_id,
        organization_id=project.organization_id,
        role=member.role,
        project=project,
    )


OrgCtx = Annotated[OrgContext, Depends(get_org_context)]
ProjectCtx = Annotated[ProjectContext, Depends(get_project_context)]


def project_permission(resource: str, action: str) -> Callable[[ProjectContext], ProjectContext]:
    def checker(ctx: ProjectCtx) -> ProjectContext:
        ctx.require(resource, action)
        return ctx

    return checker
