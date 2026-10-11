from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
SpanKind = Literal["llm", "tool", "retrieval", "chain", "agent", "http", "custom", "other"]
MAX_FUTURE_SKEW = timedelta(hours=1)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _check_id(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not ID_PATTERN.match(value):
        raise ValueError(f"{field} must be 1-128 characters of [A-Za-z0-9_-:.]")
    return value


class ErrorIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str | None = Field(default=None, max_length=256)
    message: str | None = Field(default=None, max_length=8000)
    stacktrace: str | None = Field(default=None, max_length=32000)


class UsageIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    cached_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    total_tokens: int | None = Field(default=None, ge=0, le=200_000_000)
    source: Literal["reported", "estimated"] = "reported"


class _Timed(BaseModel):
    start_time: datetime
    end_time: datetime | None = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        value = _utc(value)
        if value > datetime.now(UTC) + MAX_FUTURE_SKEW:
            raise ValueError("timestamp is too far in the future")
        return value

    @model_validator(mode="after")
    def _ordering(self) -> _Timed:
        if self.end_time is not None and self.end_time < self.start_time:
            raise ValueError("end_time must not be before start_time")
        return self


class TraceIn(_Timed):
    model_config = ConfigDict(extra="ignore")
    trace_id: str
    name: str = Field(min_length=1, max_length=512)
    status: Literal["ok", "error", "incomplete"] = "ok"
    environment: str | None = Field(default=None, max_length=128)
    release: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=256)
    session_id: str | None = Field(default=None, max_length=256)
    input: Any = None
    output: Any = None
    error: ErrorIn | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("trace_id")
    @classmethod
    def _tid(cls, v: str) -> str:
        return _check_id(v, "trace_id")  # type: ignore[return-value]

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return [t[:64] for t in v if t]


class SpanIn(_Timed):
    model_config = ConfigDict(extra="ignore")
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str = Field(min_length=1, max_length=512)
    kind: SpanKind = "other"
    status: Literal["ok", "error", "unset"] = "ok"
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    input: Any = None
    output: Any = None
    usage: UsageIn | None = None
    cost_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    error: ErrorIn | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    retry_count: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("trace_id", "span_id", "parent_span_id")
    @classmethod
    def _ids(cls, v: str | None) -> str | None:
        return _check_id(v, "id")

    @model_validator(mode="after")
    def _no_self_parent(self) -> SpanIn:
        if self.parent_span_id is not None and self.parent_span_id == self.span_id:
            raise ValueError("a span cannot be its own parent")
        return self


class IngestBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    traces: list[TraceIn] = Field(default_factory=list, max_length=500)
    spans: list[SpanIn] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _non_empty(self) -> IngestBatch:
        if not self.traces and not self.spans:
            raise ValueError("batch must contain at least one trace or span")
        return self


class IngestResponse(BaseModel):
    accepted_traces: int
    accepted_spans: int
    trace_ids: list[str]
