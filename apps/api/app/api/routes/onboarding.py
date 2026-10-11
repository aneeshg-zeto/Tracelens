from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import exists, select

from app.api.deps import DB, Principal
from app.core.errors import not_found
from app.models import Member, OnboardingState, Project, Trace
from app.schemas.dashboard import OnboardingUpdate

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

STEPS = ["organization", "project", "integration", "api-key", "install", "test-trace"]


def _serialize(db: DB, state: OnboardingState | None) -> dict[str, Any]:
    if state is None:
        return {
            "organization_id": None,
            "project_id": None,
            "integration": None,
            "completed_steps": [],
            "first_trace_received": False,
            "steps": STEPS,
        }
    first_trace = False
    if state.project_id is not None:
        first_trace = bool(db.scalar(select(exists().where(Trace.project_id == state.project_id))))
    return {
        "organization_id": state.organization_id,
        "project_id": str(state.project_id) if state.project_id else None,
        "integration": state.integration,
        "completed_steps": state.completed_steps,
        "first_trace_received": first_trace,
        "steps": STEPS,
    }


@router.get("", summary="Get the caller's onboarding progress")
def get_onboarding(principal: Principal, db: DB) -> dict[str, Any]:
    return _serialize(db, db.get(OnboardingState, principal.user_id))


@router.put("", summary="Update onboarding progress")
def update_onboarding(body: OnboardingUpdate, principal: Principal, db: DB) -> dict[str, Any]:
    state = db.get(OnboardingState, principal.user_id)
    if state is None:
        state = OnboardingState(user_id=principal.user_id, completed_steps=[])
        db.add(state)

    if body.organization_id is not None:
        member = db.scalar(
            select(Member.id).where(
                Member.user_id == principal.user_id, Member.organization_id == body.organization_id
            )
        )
        if member is None:
            raise not_found("Organization")
        state.organization_id = body.organization_id
    if body.project_id is not None:
        try:
            pid = uuid.UUID(body.project_id)
        except ValueError as exc:
            raise not_found("Project") from exc
        project = db.get(Project, pid)
        member = (
            db.scalar(
                select(Member.id).where(
                    Member.user_id == principal.user_id, Member.organization_id == project.organization_id
                )
            )
            if project
            else None
        )
        if project is None or member is None:
            raise not_found("Project")
        state.project_id = pid
    if body.integration is not None:
        state.integration = body.integration
    if body.complete_step is not None and body.complete_step not in state.completed_steps:
        state.completed_steps = [*state.completed_steps, body.complete_step]
    db.commit()
    db.refresh(state)
    return _serialize(db, state)
