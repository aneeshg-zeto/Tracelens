"""Managed prompt versions fetched from TraceLens."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    content: str
    variables: list[str] = field(default_factory=list)

    def compile(self, strict: bool = True, **values: Any) -> str:
        """Substitute ``{{ variable }}`` placeholders. Missing variables raise ``KeyError`` when strict."""
        missing = [v for v in self.variables if v not in values]
        if strict and missing:
            raise KeyError(f"Missing prompt variables: {', '.join(missing)}")

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(values[key]) if key in values else match.group(0)

        return _VARIABLE.sub(replace, self.content)

    format = compile

    @property
    def attributes(self) -> dict[str, Any]:
        return {"tracelens.prompt.name": self.name, "tracelens.prompt.version": self.version}
