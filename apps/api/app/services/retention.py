from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("tracelens.retention")
BATCH = 1000


def purge_expired(db: Session, max_batches: int = 100) -> int:
    """Delete traces older than their project's retention window (spans cascade).

    Runs in bounded batches so a large backlog cannot hold long locks.
    """
    deleted = 0
    for _ in range(max_batches):
        result = db.execute(
            text(
                """
                DELETE FROM traces WHERE id IN (
                  SELECT t.id FROM traces t JOIN projects p ON p.id = t.project_id
                  WHERE t.start_time < now() - make_interval(days => p.retention_days)
                  LIMIT :batch
                )
                """
            ),
            {"batch": BATCH},
        )
        db.commit()
        count = result.rowcount or 0  # type: ignore[attr-defined]
        deleted += count
        if count < BATCH:
            break
    if deleted:
        logger.info("retention purge", extra={"deleted_traces": deleted})
    return deleted
