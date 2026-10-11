from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = SLUG.sub("-", name.lower()).strip("-")
    return slug[:48] or "project"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    capture_payloads: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    slow_span_threshold_ms: int | None = Field(default=None, ge=1, le=3_600_000)


class ProjectOut(BaseModel):
    id: str
    organization_id: str
    name: str
    slug: str
    capture_payloads: bool
    retention_days: int
    slow_span_threshold_ms: int
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    secret: str = Field(description="Shown once. Store it now; TraceLens keeps only a hash.")


class ProviderCredentialIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)
    default_model: str = Field(min_length=1, max_length=128)


class ProviderCredentialOut(BaseModel):
    provider: Literal["openai", "anthropic"]
    secret_last4: str
    default_model: str
    updated_at: datetime


class OnboardingUpdate(BaseModel):
    organization_id: str | None = None
    project_id: str | None = None
    integration: (
        Literal["python-sdk", "opentelemetry", "openai", "anthropic", "langchain", "langgraph"] | None
    ) = None
    complete_step: (
        Literal["organization", "project", "integration", "api-key", "install", "test-trace"] | None
    ) = None
