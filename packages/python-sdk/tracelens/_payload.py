"""Conversion of arbitrary Python values into bounded, redacted, JSON-safe payloads."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

MAX_DEPTH = 10
MAX_STRING = 16_000
MAX_ITEMS = 200
REDACTED = "[REDACTED]"

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"tl_live_[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{16,}=*"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
]

PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"(?<!\w)\+?\d{1,3}[ .\-]?\(?\d{3}\)?[ .\-]?\d{3}[ .\-]?\d{4}(?!\w)"),
]

SENSITIVE_KEYS = re.compile(
    r"(?i)^(password|passwd|secret|api[_-]?key|apikey|token|access[_-]?token|refresh[_-]?token|authorization|cookie|set-cookie|private[_-]?key)$"
)

Redactor = Callable[[Any], Any]


class PayloadEncoder:
    """Makes values JSON-safe, applies redaction, and bounds their size."""

    def __init__(self, *, redact_pii: bool = False, redact: Redactor | None = None) -> None:
        self._patterns = SECRET_PATTERNS + (PII_PATTERNS if redact_pii else [])
        self._custom = redact

    def encode(self, value: Any) -> Any:
        if value is None:
            return None
        safe = self._jsonable(value, 0)
        if self._custom is not None:
            safe = self._custom(safe)
        return safe

    def redact_text(self, text: str) -> str:
        for pattern in self._patterns:
            text = pattern.sub(REDACTED, text)
        return text

    def _string(self, text: str) -> str:
        text = self.redact_text(text)
        if len(text) > MAX_STRING:
            return text[:MAX_STRING] + f"… [truncated {len(text) - MAX_STRING} chars]"
        return text

    def _jsonable(self, value: Any, depth: int) -> Any:
        if value is None or isinstance(value, bool | int | float):
            return value
        if isinstance(value, str):
            return self._string(value)
        if depth >= MAX_DEPTH:
            return "[max depth reached]"
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, Enum):
            return self._jsonable(value.value, depth + 1)
        if isinstance(value, bytes | bytearray):
            return f"<{len(value)} bytes>"
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for i, (k, v) in enumerate(value.items()):
                if i >= MAX_ITEMS:
                    out["…"] = f"{len(value) - MAX_ITEMS} more keys"
                    break
                key = str(k)
                out[key] = REDACTED if SENSITIVE_KEYS.match(key) and v else self._jsonable(v, depth + 1)
            return out
        if isinstance(value, list | tuple | set | frozenset):
            items = list(value)
            result = [self._jsonable(v, depth + 1) for v in items[:MAX_ITEMS]]
            if len(items) > MAX_ITEMS:
                result.append(f"… {len(items) - MAX_ITEMS} more items")
            return result
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return self._jsonable(model_dump(mode="json", exclude_none=True), depth + 1)
            except Exception:
                pass
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return self._jsonable(dataclasses.asdict(value), depth + 1)
        to_dict = getattr(value, "to_dict", None) or getattr(value, "dict", None)
        if callable(to_dict):
            try:
                return self._jsonable(to_dict(), depth + 1)
            except Exception:
                pass
        return self._string(repr(value))
