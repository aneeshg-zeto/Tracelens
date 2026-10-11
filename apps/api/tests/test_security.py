from __future__ import annotations

import pytest

from app.core.permissions import has_permission
from app.core.redaction import REDACTED, bound_payload, redact, summarize_payload
from app.core.security import (
    InternalTokenError,
    generate_api_key,
    hash_api_key,
    looks_like_api_key,
    verify_internal_token,
)

from .conftest import mint_token


def test_generated_keys_are_unique_prefixed_and_hashed() -> None:
    a, b = generate_api_key(), generate_api_key()
    assert a.raw != b.raw
    assert a.raw.startswith("tl_live_") and looks_like_api_key(a.raw)
    assert a.prefix == a.raw[:14]
    assert a.hash == hash_api_key(a.raw) and a.raw not in a.hash


def test_internal_token_valid() -> None:
    p = verify_internal_token(mint_token("u1", "o1"))
    assert (p.user_id, p.organization_id) == ("u1", "o1")


@pytest.mark.parametrize(
    "token",
    [
        mint_token("u1", "o1", secret="x" * 40),
        mint_token("u1", "o1", audience="someone-else"),
        mint_token("u1", "o1", lifetime=-60),
        mint_token("u1", "o1", lifetime=3600),
        "not-a-jwt",
    ],
    ids=["wrong-secret", "wrong-audience", "expired", "lifetime-too-long", "garbage"],
)
def test_internal_token_rejected(token: str) -> None:
    with pytest.raises(InternalTokenError):
        verify_internal_token(token)


def test_redaction_keys_and_values() -> None:
    data = {
        "api_key": "abc",
        "Authorization": "Bearer abcdefghijkl",
        "nested": {"password": "hunter2", "note": "my key is sk-proj-ABCDEFGHIJKLMNOPQRSTUV ok"},
        "input_tokens": 120,
        "gen_ai.usage.output_tokens": 30,
        "msg": "use tl_live_abcdefghijklmnopqrstuvwxyz",
    }
    out = redact(data)
    assert out["api_key"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["nested"]["password"] == REDACTED
    assert "sk-proj" not in out["nested"]["note"] and REDACTED in out["nested"]["note"]
    assert out["input_tokens"] == 120
    assert out["gen_ai.usage.output_tokens"] == 30
    assert "tl_live_" not in out["msg"]


def test_bound_payload_truncates_large_values() -> None:
    out = bound_payload({"items": ["x" * 5000 for _ in range(20)]})
    assert out["_truncated"] is True and out["original_bytes"] > 32_000


def test_summarize_payload_never_includes_content() -> None:
    assert summarize_payload({"secret": "v"}) == {"_captured": False, "type": "object", "keys": 1}
    assert summarize_payload("hello") == {"_captured": False, "type": "string", "length": 5}


def test_permission_matrix() -> None:
    assert has_permission("owner", "project", "delete")
    assert not has_permission("admin", "project", "delete")
    assert has_permission("admin", "apiKey", "create")
    assert not has_permission("member", "apiKey", "create")
    assert has_permission("member", "trace", "ingest")
    assert has_permission("viewer", "trace", "read")
    assert not has_permission("viewer", "evaluation", "run")
    assert not has_permission("unknown", "trace", "read")
