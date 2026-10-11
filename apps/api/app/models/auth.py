"""Read-only mappings of tables owned by Better Auth.

The schema is created by the first Alembic revision from the SQL that the
Better Auth CLI generated. The API only reads these tables (membership checks,
display names); Better Auth in the Next.js app is the only writer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column("emailVerified", Boolean)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(timezone=True))


class Organization(Base):
    __tablename__ = "organization"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(timezone=True))


class Member(Base):
    __tablename__ = "member"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    organization_id: Mapped[str] = mapped_column("organizationId", Text, ForeignKey("organization.id"))
    user_id: Mapped[str] = mapped_column("userId", Text, ForeignKey("user.id"))
    role: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(timezone=True))
