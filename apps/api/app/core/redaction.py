"""Secret redaction and payload bounding applied to everything we persist.

Redaction runs on the server regardless of SDK settings, so data from
third-party OTLP exporters is covered too.
"""

from __future__ import annotations

import json
import re
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[-_]?key|apikey|authorization|auth[-_]?header|cookie|"
    r"set-cookie|session[-_]?id|private[-_]?key|client[-_]?secret|access[-_]?key|credential)",
    re.IGNORECASE,
)
# Usage counters are not secrets even though their names contain "token".
SAFE_KEYS = re.compile(
    r"^(input|output|prompt|completion|total|cached|cache_read|cache_creation|reasoning)?[_.-]?tokens?"
    r"([_.-]?(count|usage|details))?$|^(gen_ai\.usage\..*|llm\.usage\..*|usage\..*|max_tokens|max_output_tokens"
    r"|token_count|tokens_used)$",
    re.IGNORECASE,
)

VALUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-(proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"tl_live_[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{8,}"),
    re.compile(r"(?i)basic\s+[A-Za-z0-9+/=]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]

MAX_STRING_CHARS = 8_000
MAX_FIELD_BYTES = 32_000
MAX_DEPTH = 12
MAX_ITEMS = 500


def redact_string(value: str) -> str:
    for pattern in VALUE_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def _is_sensitive_key(key: str) -> bool:
    return bool(SENSITIVE_KEY.search(key)) and not SAFE_KEYS.match(key)


def redact(value: Any, depth: int = 0) -> Any:
    if depth > MAX_DEPTH:
        return "[TRUNCATED: max depth]"
    if isinstance(value, str):
        value = redact_string(value)
        if len(value) > MAX_STRING_CHARS:
            return value[:MAX_STRING_CHARS] + f"... [TRUNCATED {len(value) - MAX_STRING_CHARS} chars]"
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_ITEMS:
                out["_truncated_keys"] = len(value) - MAX_ITEMS
                break
            key = str(k)
            out[key] = REDACTED if _is_sensitive_key(key) and v not in (None, "") else redact(v, depth + 1)
        return out
    if isinstance(value, list | tuple):
        items = [redact(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"[TRUNCATED {len(value) - MAX_ITEMS} items]")
        return items
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact_string(str(value))


def bound_payload(value: Any) -> Any:
    """Redact, then cap the serialized size of a JSON field."""
    if value is None:
        return None
    cleaned = redact(value)
    encoded = json.dumps(cleaned, default=str)
    if len(encoded) <= MAX_FIELD_BYTES:
        return cleaned
    return {"_truncated": True, "original_bytes": len(encoded), "preview": encoded[: MAX_FIELD_BYTES // 4]}


def summarize_payload(value: Any) -> Any:
    """Shape-only summary stored when a project has payload capture disabled."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {"_captured": False, "type": "object", "keys": len(value)}
    if isinstance(value, list | tuple):
        return {"_captured": False, "type": "array", "length": len(value)}
    if isinstance(value, str):
        return {"_captured": False, "type": "string", "length": len(value)}
    return {"_captured": False, "type": type(value).__name__}
