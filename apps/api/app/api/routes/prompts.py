from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, ProjectContext, project_permission
from app.core.errors import APIError, not_found
from app.models import Prompt, PromptVersion
from app.services import audit

router = APIRouter(prefix="/api/v1/projects/{project_id}/prompts", tags=["prompts"])

ReadCtx = Annotated[ProjectContext, Depends(project_permission("prompt", "read"))]
CreateCtx = Annotated[ProjectContext, Depends(project_permission("prompt", "create"))]
PublishCtx = Annotated[ProjectContext, Depends(project_permission("prompt", "publish"))]
VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,99}$"


def extract_variables(content: str) -> list[str]:
    return sorted(set(VARIABLE.findall(content)))


class PromptCreate(BaseModel):
    name: str = Field(pattern=NAME)
    description: str | None = Field(default=None, max_length=2000)
    content: str = Field(min_length=1, max_length=100_000)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class VersionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class VersionUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = Field(default=None, max_length=20)


class Activate(BaseModel):
    version: int = Field(ge=1)


def _v(v: PromptVersion) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "version": v.version,
        "content": v.content,
        "variables": v.variables,
        "notes": v.notes,
        "tags": v.tags,
        "status": v.status,
        "created_at": v.created_at,
        "published_at": v.published_at,
        "created_by": v.created_by,
    }


def _prompt(db: DB, project_id: uuid.UUID, prompt_id: uuid.UUID) -> Prompt:
    p = db.scalar(select(Prompt).where(Prompt.id == prompt_id, Prompt.project_id == project_id))
    if p is None:
        raise not_found("Prompt")
    return p


def _version(db: DB, prompt: Prompt, version: int) -> PromptVersion:
    v = db.scalar(
        select(PromptVersion).where(PromptVersion.prompt_id == prompt.id, PromptVersion.version == version)
    )
    if v is None:
        raise not_found("Prompt version")
    return v


def _detail(db: DB, p: Prompt) -> dict[str, Any]:
    versions = list(
        db.scalars(
            select(PromptVersion)
            .where(PromptVersion.prompt_id == p.id)
            .order_by(PromptVersion.version.desc())
        )
    )
    active = next((v.version for v in versions if v.id == p.active_version_id), None)
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "active_version": active,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "versions": [_v(v) for v in versions],
    }


@router.get("", summary="List prompts")
def list_prompts(ctx: ReadCtx, db: DB) -> list[dict[str, Any]]:
    latest = (
        select(PromptVersion.prompt_id, func.max(PromptVersion.version).label("latest"))
        .group_by(PromptVersion.prompt_id)
        .subquery()
    )
    rows = db.execute(
        select(Prompt, latest.c.latest, PromptVersion.version)
        .outerjoin(latest, latest.c.prompt_id == Prompt.id)
        .outerjoin(PromptVersion, PromptVersion.id == Prompt.active_version_id)
        .where(Prompt.project_id == ctx.project.id)
        .order_by(Prompt.updated_at.desc())
    ).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "latest_version": lv,
            "active_version": av,
            "updated_at": p.updated_at,
        }
        for p, lv, av in rows
    ]


@router.post("", status_code=201, summary="Create a prompt with a first draft version")
def create_prompt(body: PromptCreate, ctx: CreateCtx, db: DB) -> dict[str, Any]:
    p = Prompt(
        project_id=ctx.project.id, name=body.name, description=body.description, created_by=ctx.user_id
    )
    db.add(p)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "conflict", "A prompt with this name already exists") from exc
    db.add(
        PromptVersion(
            prompt_id=p.id,
            version=1,
            content=body.content,
            variables=extract_variables(body.content),
            notes=body.notes,
            tags=body.tags,
            status="draft",
            created_by=ctx.user_id,
        )
    )
    db.commit()
    return _detail(db, p)


@router.get("/{prompt_id}", summary="Prompt with version history")
def get_prompt(prompt_id: uuid.UUID, ctx: ReadCtx, db: DB) -> dict[str, Any]:
    return _detail(db, _prompt(db, ctx.project.id, prompt_id))


@router.post("/{prompt_id}/versions", status_code=201, summary="Create a new draft version")
def create_version(prompt_id: uuid.UUID, body: VersionCreate, ctx: CreateCtx, db: DB) -> dict[str, Any]:
    p = _prompt(db, ctx.project.id, prompt_id)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"prompt:{p.id}"})
    current = db.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.prompt_id == p.id)) or 0
    db.add(
        PromptVersion(
            prompt_id=p.id,
            version=current + 1,
            content=body.content,
            variables=extract_variables(body.content),
            notes=body.notes,
            tags=body.tags,
            status="draft",
            created_by=ctx.user_id,
        )
    )
    p.updated_at = datetime.now(UTC)
    db.commit()
    return _detail(db, p)


@router.patch("/{prompt_id}/versions/{version}", summary="Edit a draft (published versions are immutable)")
def update_version(
    prompt_id: uuid.UUID, version: int, body: VersionUpdate, ctx: CreateCtx, db: DB
) -> dict[str, Any]:
    p = _prompt(db, ctx.project.id, prompt_id)
    v = _version(db, p, version)
    if v.status == "published":
        raise APIError(409, "immutable", "Published versions cannot be edited; create a new version instead")
    if body.content is not None:
        v.content = body.content
        v.variables = extract_variables(body.content)
    if body.notes is not None:
        v.notes = body.notes
    if body.tags is not None:
        v.tags = body.tags
    db.commit()
    return _detail(db, p)


@router.post("/{prompt_id}/versions/{version}/publish", summary="Publish a draft (makes it immutable)")
def publish_version(
    prompt_id: uuid.UUID, version: int, ctx: PublishCtx, db: DB, activate: bool = True
) -> dict[str, Any]:
    p = _prompt(db, ctx.project.id, prompt_id)
    v = _version(db, p, version)
    if v.status != "published":
        v.status = "published"
        v.published_at = datetime.now(UTC)
    if activate:
        p.active_version_id = v.id
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="prompt.published",
        target_type="prompt",
        target_id=str(p.id),
        project_id=ctx.project.id,
        metadata={"name": p.name, "version": version, "activated": activate},
    )
    db.commit()
    return _detail(db, p)


@router.post("/{prompt_id}/activate", summary="Mark a published version active (rollback)")
def activate_version(prompt_id: uuid.UUID, body: Activate, ctx: PublishCtx, db: DB) -> dict[str, Any]:
    p = _prompt(db, ctx.project.id, prompt_id)
    v = _version(db, p, body.version)
    if v.status != "published":
        raise APIError(400, "not_published", "Only published versions can be activated")
    p.active_version_id = v.id
    audit.record(
        db,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        action="prompt.activated",
        target_type="prompt",
        target_id=str(p.id),
        project_id=ctx.project.id,
        metadata={"name": p.name, "version": body.version},
    )
    db.commit()
    return _detail(db, p)


@router.get(
    "/{prompt_id}/versions/{version}/traces", summary="Recent traces that reported using this version"
)
def version_traces(prompt_id: uuid.UUID, version: int, ctx: ReadCtx, db: DB) -> list[dict[str, Any]]:
    p = _prompt(db, ctx.project.id, prompt_id)
    rows = (
        db.execute(
            text(
                """
            SELECT DISTINCT ON (t.start_time, t.id) t.trace_id, t.name, t.status, t.start_time, t.duration_ms
            FROM spans s JOIN traces t ON t.id = s.trace_pk
            WHERE s.project_id = :pid
              AND s.attributes->>'tracelens.prompt.name' = :name
              AND s.attributes->>'tracelens.prompt.version' = :version
            ORDER BY t.start_time DESC, t.id DESC
            LIMIT 25
            """
            ),
            {"pid": ctx.project.id, "name": p.name, "version": str(version)},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]
