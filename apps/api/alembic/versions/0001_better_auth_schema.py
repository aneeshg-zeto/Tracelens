"""Better Auth schema (user, session, account, verification, organization, member, invitation, rateLimit).

Generated with `npx auth@1.7.7 generate` against the config in apps/web/lib/auth.ts
and stored in alembic/better_auth_schema.sql. When upgrading Better Auth or
adding auth plugins, regenerate that SQL against a database at the previous
revision and add a new migration with the delta. Do not edit this revision.

Revision ID: 0001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_FILE = Path(__file__).resolve().parents[1] / "better_auth_schema.sql"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    statements = [s.strip() for s in SQL_FILE.read_text().split(";") if s.strip()]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    for table in (
        "rateLimit",
        "invitation",
        "member",
        "organization",
        "verification",
        "account",
        "session",
        "user",
    ):
        op.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
