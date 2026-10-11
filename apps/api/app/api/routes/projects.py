from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, OrgCtx, ProjectContext, ProjectCtx, project_permission
from app.core.config import get_settings
from app.core.crypto import EncryptionUnavailableError, encrypt_secret, encryption_available
from app.core.errors import APIError, not_found
from app.core.permissions import role_permissions
from app.core.security import generate_api_key
from app.models import ApiKey, AuditEvent, Project, ProviderCredential, Trace
from app.schemas.dashboard import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProviderCredentialIn,
    ProviderCredentialOut,
    slugify,
)
from app.services import audit

router = APIRouter(prefix="/api/v1", tags=["projects"])


def project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=str(p.id),
        organization_id=p.organization_id,
        name=p.name,
        slug=p.slug,
        capture_payloads=p.capture_payloads,
        retention_days=p.retention_days,
        slow_span_threshold_ms=p.slow_span_threshold_ms,
        created_at=p.created_at,
    )


def key_out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=str(k.id),
        name=k.name,
        key_prefix=k.key_prefix,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        expires_at=k.expires_at,
        revoked_at=k.revoked_at,
    )


@router.get("/orgs/{org_id}/projects", summary="List projects in an organization")
def list_projects(ctx: OrgCtx, db: DB) -> dict[str, Any]:
    last_trace = (
        select(
            Trace.project_id, func.max(Trace.start_time).label("last_trace_at"), func.count().label("traces")
        )
        .group_by(Trace.project_id)
        .subquery()
    )
    rows = db.execute(
        select(Project, last_trace.c.last_trace_at, last_trace.c.traces)
        .outerjoin(last_trace, last_trace.c.project_id == Project.id)
        .where(Project.organization_id == ctx.organization_id)
        .order_by(Project.created_at)
    ).all()
    return {
        "role": ctx.role,
        "permissions": role_permissions(ctx.role),
        "items": [
            {**project_out(p).model_dump(), "last_trace_at": last, "trace_count": count or 0}
            for p, last, count in rows
        ],
    }


@router.post(
    "/orgs/{org_id}/projects", status_code=201, response_model=ProjectOut, summary="Create a project"
)
def create_project(body: ProjectCreate, ctx: OrgCtx, db: DB) -> ProjectOut:
    ctx.require("project", "create")
    settings = get_settings()
    base = slugify(body.name)
    slug = base
    for i in range(2, 50):
        exists = db.scalar(
            select(Project.id).where(Project.organization_id == ctx.organization_id, Project.slug == slug)
        )
        if exists is None:
            break
        slug = f"{base}-{i}"
    project = Project(
        organization_id=ctx.organization_id,
        name=body.name,
        slug=slug,
        capture_payloads=settings.default_capture_payloads,
        retention_days=settings.default_retention_days,
        created_by=ctx.user_id,
    )
    db.add(project)
    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="project.created",
        target_type="project",
        target_id=str(project.id),
        project_id=project.id,
        metadata={"name": project.name},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "conflict", "A project with this name already exists") from exc
    db.refresh(project)
    return project_out(project)


@router.get("/projects/{project_id}", summary="Get a project and the caller's role")
def get_project(ctx: ProjectCtx) -> dict[str, Any]:
    return {
        "project": project_out(ctx.project).model_dump(),
        "role": ctx.role,
        "permissions": role_permissions(ctx.role),
    }


@router.patch("/projects/{project_id}", response_model=ProjectOut, summary="Update project settings")
def update_project(
    body: ProjectUpdate,
    ctx: Annotated[ProjectContext, Depends(project_permission("project", "update"))],
    db: DB,
) -> ProjectOut:
    project = ctx.project
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    before = {k: getattr(project, k) for k in changes}
    for key, value in changes.items():
        setattr(project, key, value)
    if changes:
        audit.record(
            db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="project.settings_changed",
            target_type="project",
            target_id=str(project.id),
            project_id=project.id,
            metadata={"before": before, "after": changes},
        )
    db.commit()
    db.refresh(project)
    return project_out(project)


@router.delete("/projects/{project_id}", status_code=204, summary="Delete a project and all its data")
def delete_project(
    ctx: Annotated[ProjectContext, Depends(project_permission("project", "delete"))], db: DB
) -> Response:
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="project.deleted",
        target_type="project",
        target_id=str(ctx.project.id),
        metadata={"name": ctx.project.name},
    )
    db.delete(ctx.project)
    db.commit()
    return Response(status_code=204)


# --- API keys ------------------------------------------------------------------


@router.get("/projects/{project_id}/api-keys", response_model=list[ApiKeyOut], summary="List API keys")
def list_keys(ctx: Annotated[ProjectContext, Depends(project_permission("apiKey", "create"))], db: DB) -> Any:
    keys = db.scalars(
        select(ApiKey).where(ApiKey.project_id == ctx.project.id).order_by(ApiKey.created_at.desc())
    )
    return [key_out(k) for k in keys]


@router.post(
    "/projects/{project_id}/api-keys",
    status_code=201,
    response_model=ApiKeyCreated,
    summary="Create an API key (secret returned once)",
)
def create_key(
    body: ApiKeyCreate,
    ctx: Annotated[ProjectContext, Depends(project_permission("apiKey", "create"))],
    db: DB,
) -> ApiKeyCreated:
    active = db.scalar(
        select(func.count()).where(ApiKey.project_id == ctx.project.id, ApiKey.revoked_at.is_(None))
    )
    if (active or 0) >= 25:
        raise APIError(
            400, "limit_reached", "A project can have at most 25 active keys; revoke unused keys first"
        )
    generated = generate_api_key()
    key = ApiKey(
        project_id=ctx.project.id,
        name=body.name.strip(),
        key_prefix=generated.prefix,
        key_hash=generated.hash,
        created_by=ctx.user_id,
        expires_at=(datetime.now(UTC) + timedelta(days=body.expires_in_days))
        if body.expires_in_days
        else None,
    )
    db.add(key)
    db.flush()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="api_key.created",
        target_type="api_key",
        target_id=str(key.id),
        project_id=ctx.project.id,
        metadata={"name": key.name, "prefix": key.key_prefix},
    )
    db.commit()
    db.refresh(key)
    return ApiKeyCreated(**key_out(key).model_dump(), secret=generated.raw)


@router.post(
    "/projects/{project_id}/api-keys/{key_id}/revoke", response_model=ApiKeyOut, summary="Revoke a key"
)
def revoke_key(
    key_id: uuid.UUID,
    ctx: Annotated[ProjectContext, Depends(project_permission("apiKey", "revoke"))],
    db: DB,
) -> ApiKeyOut:
    key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.project_id == ctx.project.id))
    if key is None:
        raise not_found("API key")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        key.revoked_by = ctx.user_id
        audit.record(
            db,
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            action="api_key.revoked",
            target_type="api_key",
            target_id=str(key.id),
            project_id=ctx.project.id,
            metadata={"name": key.name, "prefix": key.key_prefix},
        )
        db.commit()
        db.refresh(key)
    return key_out(key)


# --- Provider credentials --------------------------------------------------------


Provider = Literal["openai", "anthropic"]


@router.get(
    "/projects/{project_id}/provider-credentials", summary="List stored provider credentials (masked)"
)
def list_credentials(
    ctx: Annotated[ProjectContext, Depends(project_permission("integration", "read"))], db: DB
) -> dict[str, Any]:
    creds = db.scalars(select(ProviderCredential).where(ProviderCredential.project_id == ctx.project.id))
    settings = get_settings()
    return {
        "encryption_available": encryption_available(),
        "items": [
            ProviderCredentialOut(
                provider=c.provider,  # type: ignore[arg-type]
                secret_last4=c.secret_last4,
                default_model=c.default_model,
                updated_at=c.updated_at,
            ).model_dump()
            for c in creds
        ],
        "server_fallback": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "configured": bool(
                settings.llm_provider
                and settings.llm_model
                and (
                    settings.openai_api_key
                    if settings.llm_provider == "openai"
                    else settings.anthropic_api_key
                )
            ),
        },
    }


@router.put(
    "/projects/{project_id}/provider-credentials/{provider}",
    response_model=ProviderCredentialOut,
    summary="Store a provider credential (encrypted at rest)",
)
def put_credential(
    provider: Provider,
    body: ProviderCredentialIn,
    ctx: Annotated[ProjectContext, Depends(project_permission("integration", "update"))],
    db: DB,
) -> ProviderCredentialOut:
    try:
        encrypted = encrypt_secret(body.api_key.strip())
    except EncryptionUnavailableError as exc:
        raise APIError(503, "encryption_unavailable", str(exc)) from exc
    cred = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.project_id == ctx.project.id, ProviderCredential.provider == provider
        )
    )
    if cred is None:
        cred = ProviderCredential(project_id=ctx.project.id, provider=provider, created_by=ctx.user_id)
        db.add(cred)
    cred.encrypted_secret = encrypted
    cred.secret_last4 = body.api_key.strip()[-4:]
    cred.default_model = body.default_model.strip()
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="provider_credential.saved",
        target_type="provider_credential",
        target_id=provider,
        project_id=ctx.project.id,
    )
    db.commit()
    db.refresh(cred)
    return ProviderCredentialOut(
        provider=provider,
        secret_last4=cred.secret_last4,
        default_model=cred.default_model,
        updated_at=cred.updated_at,
    )


@router.delete("/projects/{project_id}/provider-credentials/{provider}", status_code=204)
def delete_credential(
    provider: Provider,
    ctx: Annotated[ProjectContext, Depends(project_permission("integration", "update"))],
    db: DB,
) -> Response:
    cred = db.scalar(
        select(ProviderCredential).where(
            ProviderCredential.project_id == ctx.project.id, ProviderCredential.provider == provider
        )
    )
    if cred is None:
        raise not_found("Credential")
    db.delete(cred)
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="provider_credential.deleted",
        target_type="provider_credential",
        target_id=provider,
        project_id=ctx.project.id,
    )
    db.commit()
    return Response(status_code=204)


# --- Audit log -------------------------------------------------------------------


@router.get("/orgs/{org_id}/audit-events", summary="Organization audit log")
def audit_events(
    ctx: OrgCtx,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: datetime | None = None,
) -> dict[str, Any]:
    ctx.require("audit", "read")
    stmt = select(AuditEvent).where(AuditEvent.organization_id == ctx.organization_id)
    if before is not None:
        stmt = stmt.where(AuditEvent.created_at < before)
    rows = list(db.scalars(stmt.order_by(AuditEvent.created_at.desc()).limit(limit + 1)))
    return {
        "items": [
            {
                "id": str(e.id),
                "action": e.action,
                "actor_user_id": e.actor_user_id,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "project_id": str(e.project_id) if e.project_id else None,
                "metadata": e.metadata_,
                "created_at": e.created_at,
            }
            for e in rows[:limit]
        ],
        "next_before": rows[limit - 1].created_at.isoformat() if len(rows) > limit else None,
    }
