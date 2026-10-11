"""Test fixtures.

Tests run against a real PostgreSQL database (`<DATABASE_URL db>_test`, or
TEST_DATABASE_URL) migrated with Alembic, so SQL-level behaviour (upserts,
aggregates, JSONB, constraints) is exercised exactly as in production. Redis is
replaced by fakeredis.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fakeredis
import jwt
import psycopg
import pytest
from sqlalchemy import make_url, text

os.environ["TRACELENS_ENV"] = "test"
os.environ.setdefault("INGEST_RATE_LIMIT_PER_MINUTE", "1000")
os.environ["DEFAULT_CAPTURE_PAYLOADS"] = "false"
for _var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
    os.environ[_var] = ""

from app.core.config import Settings, get_settings  # noqa: E402

_base = Settings()  # type: ignore[call-arg]
_url = make_url(os.environ.get("TEST_DATABASE_URL") or _base.database_url)
if not os.environ.get("TEST_DATABASE_URL"):
    _url = _url.set(database=f"{_url.database}_test")
os.environ["DATABASE_URL"] = _url.render_as_string(hide_password=False)
get_settings.cache_clear()

from app.core.rate_limit import RateLimiter, get_rate_limiter  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


def _ensure_database() -> None:
    admin = _url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_url.database,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{_url.database}"')


@pytest.fixture(scope="session", autouse=True)
def _migrated() -> None:
    from alembic.config import Config

    from alembic import command

    _ensure_database()
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean_db(_migrated: None) -> Iterator[None]:
    yield
    session = get_sessionmaker()()
    try:
        tables = session.scalars(
            text(
                "SELECT quote_ident(tablename) FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        ).all()
        session.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        session.commit()
    finally:
        session.close()


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def app(fake_redis: fakeredis.FakeRedis) -> Any:
    application = create_app()
    limiter = RateLimiter(fake_redis)
    application.dependency_overrides[get_rate_limiter] = lambda: limiter
    return application


@pytest.fixture
def client(app: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db() -> Iterator[Any]:
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


def mint_token(
    user_id: str,
    org_id: str | None,
    *,
    lifetime: int = 60,
    secret: str | None = None,
    audience: str | None = None,
) -> str:
    settings = get_settings()
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": settings.internal_jwt_issuer,
        "aud": audience or settings.internal_jwt_audience,
        "sub": user_id,
        "iat": now,
        "exp": now + lifetime,
    }
    if org_id:
        claims["org_id"] = org_id
    return jwt.encode(claims, secret or settings.internal_jwt_secret.get_secret_value(), algorithm="HS256")


@dataclass
class Actor:
    user_id: str
    org_id: str
    role: str
    extra_orgs: list[str] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {"X-TraceLens-Internal-Token": mint_token(self.user_id, self.org_id)}


class Factory:
    def __init__(self, db: Any, client: Any) -> None:
        self.db = db
        self.client = client

    def user(self) -> str:
        uid = f"user_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            text('INSERT INTO "user" (id, name, email, "emailVerified") VALUES (:id, :name, :email, true)'),
            {"id": uid, "name": uid, "email": f"{uid}@example.test"},
        )
        self.db.commit()
        return uid

    def org(self, owner_role: str = "owner") -> Actor:
        oid = f"org_{uuid.uuid4().hex[:12]}"
        self.db.execute(
            text('INSERT INTO organization (id, name, slug, "createdAt") VALUES (:id, :id, :id, now())'),
            {"id": oid},
        )
        self.db.commit()
        return self.member(oid, owner_role)

    def member(self, org_id: str, role: str, user_id: str | None = None) -> Actor:
        uid = user_id or self.user()
        self.db.execute(
            text(
                'INSERT INTO member (id, "organizationId", "userId", role, "createdAt") '
                "VALUES (:id, :org, :user, :role, now())"
            ),
            {"id": uuid.uuid4().hex, "org": org_id, "user": uid, "role": role},
        )
        self.db.commit()
        return Actor(user_id=uid, org_id=org_id, role=role)

    def project(self, actor: Actor, name: str = "Support Agent") -> dict[str, Any]:
        r = self.client.post(
            f"/api/v1/orgs/{actor.org_id}/projects", json={"name": name}, headers=actor.headers
        )
        assert r.status_code == 201, r.text
        return r.json()

    def api_key(self, actor: Actor, project_id: str, name: str = "test") -> str:
        r = self.client.post(
            f"/api/v1/projects/{project_id}/api-keys", json={"name": name}, headers=actor.headers
        )
        assert r.status_code == 201, r.text
        return r.json()["secret"]


@pytest.fixture
def factory(db: Any, client: Any) -> Factory:
    return Factory(db, client)


@pytest.fixture
def owner(factory: Factory) -> Actor:
    return factory.org()


@pytest.fixture
def project(factory: Factory, owner: Actor) -> dict[str, Any]:
    return factory.project(owner)


@pytest.fixture
def api_key(factory: Factory, owner: Actor, project: dict[str, Any]) -> str:
    return factory.api_key(owner, project["id"])


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def sample_batch(
    trace_id: str = "trace-1", *, error: bool = False, base: datetime | None = None
) -> dict[str, Any]:
    """Agent trace: root agent span -> llm span + tool span (optionally failing)."""
    t0 = base or datetime.now(UTC) - timedelta(minutes=5)
    return {
        "traces": [
            {
                "trace_id": trace_id,
                "name": "answer-question",
                "status": "error" if error else "ok",
                "start_time": iso(t0),
                "end_time": iso(t0 + timedelta(seconds=3)),
                "environment": "test",
                "input": {"question": "What is my balance?"},
                "output": {"answer": "42"},
                "tags": ["unit"],
            }
        ],
        "spans": [
            {
                "trace_id": trace_id,
                "span_id": f"{trace_id}-root",
                "name": "agent",
                "kind": "agent",
                "start_time": iso(t0),
                "end_time": iso(t0 + timedelta(seconds=3)),
                "status": "error" if error else "ok",
            },
            {
                "trace_id": trace_id,
                "span_id": f"{trace_id}-llm",
                "parent_span_id": f"{trace_id}-root",
                "name": "chat gpt-4o-mini",
                "kind": "llm",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "start_time": iso(t0 + timedelta(milliseconds=100)),
                "end_time": iso(t0 + timedelta(seconds=1)),
                "usage": {"input_tokens": 1000, "output_tokens": 200},
                "input": [{"role": "user", "content": "What is my balance?"}],
            },
            {
                "trace_id": trace_id,
                "span_id": f"{trace_id}-tool",
                "parent_span_id": f"{trace_id}-root",
                "name": "lookup_balance",
                "kind": "tool",
                "start_time": iso(t0 + timedelta(seconds=1)),
                "end_time": iso(t0 + timedelta(seconds=2)),
                "status": "error" if error else "ok",
                **(
                    {"error": {"type": "TimeoutError", "message": "upstream timed out after 1s"}}
                    if error
                    else {}
                ),
            },
        ],
    }
