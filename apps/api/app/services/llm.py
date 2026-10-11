"""Server-side LLM calls for the investigator, LLM judge, and model evaluation runs.

Credentials resolve per project first (encrypted ProviderCredential), then the
operator-level fallback in the environment. Nothing here is called during trace
ingestion.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
import openai
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import EncryptionUnavailableError, decrypt_secret
from app.models import ProviderCredential

TIMEOUT_SECONDS = 60.0


class LLMNotConfiguredError(Exception):
    pass


class LLMCallError(Exception):
    pass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str
    source: str  # project | server


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    latency_ms: float


def resolve_config(
    db: Session, project_id: uuid.UUID, provider: str | None = None, model: str | None = None
) -> LLMConfig:
    stmt = select(ProviderCredential).where(ProviderCredential.project_id == project_id)
    if provider:
        stmt = stmt.where(ProviderCredential.provider == provider)
    cred = db.scalars(stmt.order_by(ProviderCredential.updated_at.desc())).first()
    if cred is not None:
        try:
            key = decrypt_secret(cred.encrypted_secret)
        except EncryptionUnavailableError as exc:
            raise LLMNotConfiguredError(str(exc)) from exc
        return LLMConfig(cred.provider, model or cred.default_model, key, "project")

    s = get_settings()
    if s.llm_provider and (provider is None or provider == s.llm_provider):
        secret = s.openai_api_key if s.llm_provider == "openai" else s.anthropic_api_key
        chosen_model = model or s.llm_model
        if secret is not None and chosen_model:
            return LLMConfig(s.llm_provider, chosen_model, secret.get_secret_value(), "server")
    raise LLMNotConfiguredError(
        "No LLM provider is configured. Add a provider key in Project settings > AI providers, or set "
        "LLM_PROVIDER, LLM_MODEL and the matching API key on the server."
    )


def complete(
    config: LLMConfig, *, system: str, user: str, json_mode: bool = False, max_tokens: int = 1500
) -> LLMResponse:
    started = time.perf_counter()
    try:
        if config.provider == "openai":
            client = openai.OpenAI(api_key=config.api_key, timeout=TIMEOUT_SECONDS, max_retries=2)
            kwargs: dict[str, Any] = {}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(
                model=config.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_completion_tokens=max_tokens,
                **kwargs,
            )
            text = resp.choices[0].message.content or ""
            usage = resp.usage
            cached = None
            if usage is not None and usage.prompt_tokens_details is not None:
                cached = usage.prompt_tokens_details.cached_tokens
            return LLMResponse(
                text,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
                cached,
                (time.perf_counter() - started) * 1000,
            )
        if config.provider == "anthropic":
            client_a = anthropic.Anthropic(api_key=config.api_key, timeout=TIMEOUT_SECONDS, max_retries=2)
            msg = client_a.messages.create(
                model=config.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(block, "text", "") for block in msg.content)
            u = msg.usage
            cache_read = getattr(u, "cache_read_input_tokens", None) or 0
            cache_write = getattr(u, "cache_creation_input_tokens", None) or 0
            return LLMResponse(
                text,
                u.input_tokens + cache_read + cache_write,
                u.output_tokens,
                cache_read or None,
                (time.perf_counter() - started) * 1000,
            )
    except (openai.OpenAIError, anthropic.AnthropicError) as exc:
        raise LLMCallError(
            f"{config.provider} request failed: {type(exc).__name__}: {str(exc)[:300]}"
        ) from exc
    raise LLMNotConfiguredError(f"Unsupported provider {config.provider}")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> dict[str, Any]:
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise LLMCallError("model response did not contain a JSON object")
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMCallError("model response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise LLMCallError("model response JSON was not an object")
    return value
