"""Celery queue helpers for pipeline orchestration."""
import os
import subprocess
from pathlib import Path
from typing import List

from celery import Celery, chain

BASE_DIR = Path(__file__).resolve().parents[1]

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_QUEUE = os.getenv("CELERY_QUEUE", "duo")

celery_app = Celery("duo", broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue=CELERY_QUEUE,
)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def run_command(self, cmd: List[str], cwd: str) -> dict:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Command failed: {' '.join(cmd)}")
    return {"stdout": result.stdout, "stderr": result.stderr}


def enqueue_pipeline(commands: List[List[str]], cwd: str | None = None) -> str:
    workdir = cwd or str(BASE_DIR)
    job = chain(*(run_command.si(cmd, workdir) for cmd in commands)).apply_async()
    return job.id
