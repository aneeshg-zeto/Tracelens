"""Background batching exporter with a bounded queue."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from tracelens.transport import Transport

logger = logging.getLogger("tracelens")


class BatchExporter:
    """Buffers finished traces and spans and ships them in batches from a daemon thread.

    The queue is bounded: when it is full, new records are dropped (and counted) so that
    instrumentation never blocks or grows memory without limit in the host application.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        max_queue_size: int = 10_000,
        max_batch_size: int = 200,
        flush_interval: float = 1.0,
    ) -> None:
        self._transport = transport
        self._max_queue = max(1, max_queue_size)
        self._max_batch = max(1, min(max_batch_size, 500))
        self._interval = max(0.05, flush_interval)
        self._queue: deque[tuple[str, dict[str, Any]]] = deque()
        self._cond = threading.Condition()
        self._send_lock = threading.Lock()
        self._stopped = False
        self.dropped = 0
        self.sent_batches = 0
        self.failed_batches = 0
        self._thread = threading.Thread(target=self._run, name="tracelens-exporter", daemon=True)
        self._thread.start()

    def put(self, kind: str, record: dict[str, Any]) -> bool:
        with self._cond:
            if self._stopped:
                return False
            if len(self._queue) >= self._max_queue:
                self.dropped += 1
                if self.dropped == 1 or self.dropped % 1000 == 0:
                    logger.warning("TraceLens: export queue full, %d records dropped so far", self.dropped)
                return False
            self._queue.append((kind, record))
            if len(self._queue) >= self._max_batch:
                self._cond.notify()
        return True

    def _take(self) -> dict[str, list[dict[str, Any]]] | None:
        with self._cond:
            if not self._queue:
                return None
            batch: dict[str, list[dict[str, Any]]] = {"traces": [], "spans": []}
            for _ in range(min(self._max_batch, len(self._queue))):
                kind, record = self._queue.popleft()
                batch["traces" if kind == "trace" else "spans"].append(record)
            return batch

    def _drain(self) -> None:
        with self._send_lock:
            while True:
                batch = self._take()
                if batch is None:
                    return
                payload = {k: v for k, v in batch.items() if v}
                try:
                    ok = self._transport.send_batch(payload)
                except Exception:
                    logger.exception("TraceLens: unexpected error while exporting")
                    ok = False
                if ok:
                    self.sent_batches += 1
                else:
                    self.failed_batches += 1

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._stopped and len(self._queue) < self._max_batch:
                    self._cond.wait(self._interval)
                stopped = self._stopped
            self._drain()
            if stopped:
                return

    def flush(self, timeout: float | None = 10.0) -> bool:
        """Send everything queued so far. Returns False if the timeout elapsed first."""
        done = threading.Event()

        def work() -> None:
            self._drain()
            done.set()

        if timeout is None:
            work()
            return True
        threading.Thread(target=work, name="tracelens-flush", daemon=True).start()
        return done.wait(timeout)

    def shutdown(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        with self._cond:
            if self._stopped:
                return
            self._stopped = True
            self._cond.notify_all()
        self._thread.join(max(0.0, deadline - time.monotonic()))
        self.flush(max(0.0, deadline - time.monotonic()))

    @property
    def queued(self) -> int:
        with self._cond:
            return len(self._queue)
