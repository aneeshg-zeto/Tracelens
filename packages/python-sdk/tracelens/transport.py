"""HTTP transport to the TraceLens API with bounded retries."""

from __future__ import annotations

import contextlib
import logging
import random
import time
from typing import Any, Protocol

import httpx

from tracelens.version import __version__

logger = logging.getLogger("tracelens")

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class TraceLensError(Exception):
    """Raised by SDK helpers that read from the API (prompts, datasets, evaluations)."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class Transport(Protocol):
    def send_batch(self, payload: dict[str, Any]) -> bool: ...

    def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any: ...

    def close(self) -> None: ...


class HttpTransport:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._max_retries = max(0, max_retries)
        self._backoff = backoff
        self._client = client or httpx.Client(timeout=timeout)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": f"tracelens-python/{__version__}",
        }
        self._warned: set[str] = set()

    def _sleep_for(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(30.0, max(0.0, float(retry_after)))
                except ValueError:
                    pass
        return min(30.0, self._backoff * (2**attempt)) * (0.5 + random.random() / 2)

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            logger.warning(message)

    def send_batch(self, payload: dict[str, Any]) -> bool:
        url = f"{self._base}/api/v1/ingest/batch"
        for attempt in range(self._max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = self._client.post(url, json=payload, headers=self._headers)
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    self._warn_once(
                        "network", f"TraceLens: could not reach {self._base} ({exc}); dropping batch"
                    )
                    return False
                time.sleep(self._sleep_for(attempt, None))
                continue
            if response.is_success:
                return True
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                time.sleep(self._sleep_for(attempt, response))
                continue
            message = _error_message(response)
            if response.status_code == 401:
                self._warn_once(
                    "auth", f"TraceLens: API key rejected ({message}); traces are not being recorded"
                )
            else:
                logger.warning("TraceLens: batch rejected with HTTP %s: %s", response.status_code, message)
            return False
        return False

    def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        url = f"{self._base}{path}"
        last: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(method, url, json=json, params=params, headers=self._headers)
            except httpx.HTTPError as exc:
                last = exc
                if attempt < self._max_retries:
                    time.sleep(self._sleep_for(attempt, None))
                    continue
                raise TraceLensError(f"Could not reach TraceLens at {self._base}: {exc}") from exc
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                time.sleep(self._sleep_for(attempt, response))
                continue
            if not response.is_success:
                code = None
                with contextlib.suppress(Exception):
                    code = response.json().get("error", {}).get("code")
                raise TraceLensError(_error_message(response), status=response.status_code, code=code)
            return response.json() if response.content else None
        raise TraceLensError(f"Request to {path} failed: {last}")

    def close(self) -> None:
        self._client.close()


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    except Exception:
        pass
    return f"HTTP {response.status_code}"
