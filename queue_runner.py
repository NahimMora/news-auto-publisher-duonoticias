from __future__ import annotations

"""Deprecated Celery wrapper.

The old queue used to enqueue scraper -> captioner -> formatter -> publisher subprocesses.
That would compete with the SQLite runtime, so this wrapper now enqueues one CLI cycle only.
"""

import os
import sys
from pathlib import Path

from utils.task_queue import enqueue_pipeline

BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    max_news = os.getenv("DUO_MAX_NOTICIAS", "").strip()
    command = [sys.executable, "-m", "cli.main", "run-once", "--safe-mode"]
    if max_news:
        command.extend(["--max-news", max_news])
    job_id = enqueue_pipeline([command], cwd=str(BASE_DIR))
    print(f"Pipeline nuevo encolado: {job_id}")


if __name__ == "__main__":
    main()
