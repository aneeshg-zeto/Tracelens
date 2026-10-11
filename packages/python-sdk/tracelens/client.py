"""The TraceLens client: configuration, sampling, and export."""

from __future__ import annotations

import atexit
import logging
import os
import random
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from tracelens._payload import PayloadEncoder, Redactor
from tracelens.exporter import BatchExporter
from tracelens.prompts import Prompt
from tracelens.tracing import Span, SpanKind, Trace, _current_span, _current_trace
from tracelens.transport import HttpTransport, TraceLensError, Transport

logger = logging.getLogger("tracelens")

DEFAULT_BASE_URL = "http://localhost:8000"
MAX_EVAL_RESULTS = 500

_global_lock = threading.Lock()
_global_client: TraceLens | None = None


def _env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


class TraceLens:
    """Client that records traces and sends them to a TraceLens server.

    Configuration falls back to environment variables: ``TRACELENS_API_KEY``,
    ``TRACELENS_BASE_URL``, ``TRACELENS_ENVIRONMENT``, ``TRACELENS_RELEASE``,
    ``TRACELENS_SAMPLE_RATE`` and ``TRACELENS_ENABLED``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        environment: str | None = None,
        release: str | None = None,
        sample_rate: float | None = None,
        capture_payloads: bool = True,
        redact_pii: bool = False,
        redact: Redactor | None = None,
        enabled: bool | None = None,
        flush_interval: float = 1.0,
        max_batch_size: int = 200,
        max_queue_size: int = 10_000,
        timeout: float = 10.0,
        max_retries: int = 3,
        transport: Transport | None = None,
        set_global: bool = True,
        register_atexit: bool = True,
    ) -> None:
        self.api_key = api_key or os.environ.get("TRACELENS_API_KEY") or None
        self.base_url = (base_url or os.environ.get("TRACELENS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.environment = environment if environment is not None else os.environ.get("TRACELENS_ENVIRONMENT")
        self.release = release if release is not None else os.environ.get("TRACELENS_RELEASE")
        if sample_rate is None:
            sample_rate = float(os.environ.get("TRACELENS_SAMPLE_RATE", "1.0"))
        self.sample_rate = min(1.0, max(0.0, sample_rate))
        self.capture_payloads = capture_payloads
        self._encoder = PayloadEncoder(redact_pii=redact_pii, redact=redact)
        self._prompt_cache: dict[tuple[str, int | None], tuple[float, Prompt]] = {}

        env_enabled = _env_bool("TRACELENS_ENABLED")
        if enabled is None:
            enabled = (
                env_enabled if env_enabled is not None else (transport is not None or bool(self.api_key))
            )
        self.enabled = enabled

        self._transport: Transport | None = transport
        if self._transport is None and self.api_key:
            self._transport = HttpTransport(
                self.base_url, self.api_key, timeout=timeout, max_retries=max_retries
            )
        if self.enabled and self._transport is None:
            logger.warning("TraceLens: no API key configured (set TRACELENS_API_KEY); tracing is disabled")
            self.enabled = False

        self._exporter: BatchExporter | None = None
        if self.enabled and self._transport is not None:
            self._exporter = BatchExporter(
                self._transport,
                max_queue_size=max_queue_size,
                max_batch_size=max_batch_size,
                flush_interval=flush_interval,
            )
            if register_atexit:
                atexit.register(self.shutdown)

        if set_global:
            set_client(self)

    # internals --------------------------------------------------------------
    def _encode_payload(self, value: Any) -> Any:
        """Inputs and outputs: dropped entirely when payload capture is off."""
        if not self.capture_payloads:
            return None
        return self._encoder.encode(value)

    def _encode_meta(self, value: dict[str, Any]) -> dict[str, Any]:
        """Attributes and metadata: always sent, always redacted."""
        return self._encoder.encode(value) or {}

    def _enqueue(self, kind: str, record: dict[str, Any]) -> None:
        if self._exporter is not None:
            self._exporter.put(kind, record)

    def _sample(self) -> bool:
        return self.enabled and (self.sample_rate >= 1.0 or random.random() < self.sample_rate)

    # tracing API ------------------------------------------------------------
    def trace(self, name: str, **kwargs: Any) -> Trace:
        """Create a trace. Use it as a context manager so nested spans attach to it."""
        sampled = kwargs.pop("sampled", None)
        return Trace(self, name, sampled=self._sample() if sampled is None else sampled, **kwargs)

    def span(
        self,
        name: str,
        kind: SpanKind = "custom",
        *,
        parent: Span | None = None,
        trace_name: str | None = None,
        **kwargs: Any,
    ) -> Span:
        """Create a span under the current span or trace.

        Without an active trace, a trace is started implicitly and ends with this span.
        """
        parent = parent if parent is not None else _current_span.get()
        if parent is not None:
            return Span(self, parent.trace, name, kind=kind, parent=parent, **kwargs)
        trace = _current_trace.get()
        if trace is not None:
            return Span(self, trace, name, kind=kind, parent=None, **kwargs)
        implicit = self.trace(trace_name or name)
        return Span(self, implicit, name, kind=kind, parent=None, owns_trace=True, **kwargs)

    def current_trace(self) -> Trace | None:
        return _current_trace.get()

    def current_span(self) -> Span | None:
        return _current_span.get()

    def flush(self, timeout: float = 10.0) -> bool:
        if self._exporter is None:
            return True
        return self._exporter.flush(timeout)

    def shutdown(self, timeout: float = 10.0) -> None:
        if self._exporter is not None:
            self._exporter.shutdown(timeout)

    @property
    def stats(self) -> dict[str, int]:
        if self._exporter is None:
            return {"queued": 0, "dropped": 0, "sent_batches": 0, "failed_batches": 0}
        e = self._exporter
        return {
            "queued": e.queued,
            "dropped": e.dropped,
            "sent_batches": e.sent_batches,
            "failed_batches": e.failed_batches,
        }

    # API helpers -----------------------------------------------------------
    def _require_transport(self) -> Transport:
        if self._transport is None:
            raise TraceLensError("TraceLens is not configured: set TRACELENS_API_KEY or pass api_key")
        return self._transport

    def whoami(self) -> dict[str, Any]:
        """Validate the API key and return the project it belongs to."""
        return self._require_transport().request("GET", "/api/v1/ingest/whoami")

    def get_prompt(self, name: str, version: int | None = None, *, cache_ttl: float = 60.0) -> Prompt:
        """Fetch the active published version of a prompt (or a specific published version)."""
        key = (name, version)
        cached = self._prompt_cache.get(key)
        if cached and cache_ttl > 0 and time.monotonic() - cached[0] < cache_ttl:
            return cached[1]
        params = {"version": version} if version is not None else None
        data = self._require_transport().request(
            "GET", f"/api/v1/ingest/prompts/{quote(name, safe='')}", params=params
        )
        prompt = Prompt(
            name=data["name"],
            version=int(data["version"]),
            content=data["content"],
            variables=list(data.get("variables") or []),
        )
        self._prompt_cache[key] = (time.monotonic(), prompt)
        return prompt

    def get_dataset(self, name: str) -> dict[str, Any]:
        """Fetch an evaluation dataset's examples: ``{"id", "name", "examples": [{"id", "input", "expected_output"}]}``."""
        return self._require_transport().request(
            "GET", f"/api/v1/ingest/evaluations/datasets/{quote(name, safe='')}"
        )

    def run_evaluation(
        self,
        dataset: str,
        task: Callable[[Any], Any],
        evaluators: list[str | dict[str, Any]],
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Run ``task`` on every example of a dataset locally, then submit outputs for scoring.

        Each example runs inside its own trace (tagged ``evaluation``) so results link to traces.
        Returns the run summary computed by the server.
        """
        ds = self.get_dataset(dataset)
        examples = ds.get("examples", [])
        if limit is not None:
            examples = examples[:limit]
        if not examples:
            raise TraceLensError(f"Dataset {dataset!r} has no examples")
        if len(examples) > MAX_EVAL_RESULTS:
            raise TraceLensError(
                f"Dataset {dataset!r} has {len(examples)} examples; submit at most {MAX_EVAL_RESULTS} per run (pass limit=)"
            )
        specs = [{"type": e} if isinstance(e, str) else e for e in evaluators]
        run_name = name or f"{dataset} {time.strftime('%Y-%m-%d %H:%M:%S')}"
        results = []
        for example in examples:
            started = time.perf_counter()
            output: Any = None
            error: str | None = None
            with self.trace(
                f"eval: {dataset}",
                tags=["evaluation"],
                metadata={"example_id": example["id"], "run": run_name},
            ) as tr:
                tr.set_input(example.get("input"))
                try:
                    output = task(example.get("input"))
                    tr.set_output(output)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:4000]
                    tr.record_error(exc)
            results.append(
                {
                    "example_id": example["id"],
                    "output": self._encoder.encode(output),
                    "error": error,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "trace_id": tr.trace_id if tr.sampled else None,
                }
            )
        self.flush()
        return self._require_transport().request(
            "POST",
            "/api/v1/ingest/evaluations/runs",
            json={
                "dataset": dataset,
                "name": run_name[:120],
                "evaluators": specs,
                "results": results,
                "metadata": metadata or {},
            },
        )


_disabled_client: TraceLens | None = None


def set_client(client: TraceLens) -> None:
    global _global_client
    with _global_lock:
        _global_client = client


def get_client() -> TraceLens:
    """Return the global client, creating one from environment variables on first use.

    Without configuration this returns a disabled client, so instrumented code keeps working.
    """
    global _global_client, _disabled_client
    with _global_lock:
        if _global_client is not None:
            return _global_client
        if os.environ.get("TRACELENS_API_KEY"):
            _global_client = TraceLens(set_global=False)
            return _global_client
        if _disabled_client is None:
            _disabled_client = TraceLens(enabled=False, set_global=False, register_atexit=False)
        return _disabled_client
