from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

import jwt

from app.core.config import get_settings

API_KEY_PREFIX = "tl_live_"
API_KEY_DISPLAY_CHARS = 6


@dataclass(frozen=True)
class GeneratedKey:
    raw: str
    prefix: str
    hash: str


def hash_api_key(raw: str) -> str:
    """SHA-256 of the full key. Keys carry 256 bits of entropy from the OS CSPRNG,
    so a fast hash is sufficient (no dictionary attack is feasible)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> GeneratedKey:
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return GeneratedKey(
        raw=raw,
        prefix=raw[: len(API_KEY_PREFIX) + API_KEY_DISPLAY_CHARS],
        hash=hash_api_key(raw),
    )


def hashes_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def looks_like_api_key(value: str) -> bool:
    return value.startswith(API_KEY_PREFIX) and 30 <= len(value) <= 128


class InternalTokenError(Exception):
    pass


@dataclass(frozen=True)
class InternalPrincipal:
    user_id: str
    organization_id: str | None


def verify_internal_token(token: str) -> InternalPrincipal:
    """Verify the short-lived JWT minted by the Next.js server for a dashboard user.

    Signature, issuer, audience, expiry, and issued-at are all required. The
    token only identifies the user; membership and roles are always re-read from
    the database by the caller.
    """
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.internal_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.internal_jwt_audience,
            issuer=settings.internal_jwt_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise InternalTokenError(str(exc)) from exc
    iat = claims.get("iat")
    exp = claims.get("exp")
    if not isinstance(iat, int | float) or not isinstance(exp, int | float) or exp - iat > 300:
        raise InternalTokenError("token lifetime exceeds 5 minutes")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise InternalTokenError("missing subject")
    org = claims.get("org_id")
    return InternalPrincipal(user_id=sub, organization_id=org if isinstance(org, str) and org else None)
