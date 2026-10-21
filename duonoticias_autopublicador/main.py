from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import Settings
from .duo_client import DuoClient
from .hs_client import HolaSaltaClient
from .logging_utils import configure_logging
from .models import DiscoveredItem, news_key, trace_id, video_key
from .pipeline import PassthroughProcessor, Processor
from .state import StateStore

logger = logging.getLogger(__name__)


class AutoPublisher:
    def __init__(
        self,
        settings: Settings,
        store: StateStore,
        hs_client: HolaSaltaClient,
        duo_client: DuoClient,
        processor: Processor | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.settings = settings
        self.store = store
        self.hs = hs_client
        self.duo = duo_client
        self.processor = processor or PassthroughProcessor()
        self.dry_run = dry_run

    def run_once(self) -> dict[str, int]:
        news = self.hs.get_news()
        videos = self.hs.get_video_jobs()
        discovered = [DiscoveredItem(news_key(item), "news", item) for item in news]
        discovered.extend(DiscoveredItem(video_key(item), "video_link", item) for item in videos)
        result = self.store.ingest(
            discovered,
            initial_mode=self.settings.initial_sync,
            last_n=self.settings.initial_sync_last_n,
        )
        if result["changed_sent"]:
            logger.warning("sent_item_content_changed_no_resend", extra={"attempts": result["changed_sent"]})

        for row in self.store.list_for_processing():
            extra = {"trace_id": trace_id(row["key"]), "item_key": row["key"], "kind": row["kind"]}
            try:
                raw: dict[str, Any] = json.loads(row["raw_json"])
                processed = self.processor.process(raw)
                self.store.mark_processed(row["key"], processed)
                logger.info("item_processed", extra=extra)
            except Exception as exc:
                self.store.mark_failed(row["key"], f"processor: {type(exc).__name__}: {exc}")
                logger.exception("item_processing_failed", extra=extra)

        if not self.dry_run:
            for row in self.store.list_for_sending():
                extra = {"trace_id": trace_id(row["key"]), "item_key": row["key"], "kind": row["kind"]}
                result_send = self.duo.send(row)
                if result_send.success:
                    self.store.mark_sent(row["key"])
                    logger.info("item_sent", extra={**extra, "status_code": result_send.status_code})
                elif not result_send.retryable:
                    self.store.mark_failed(row["key"], result_send.error or "fallo definitivo")
                    logger.error("item_send_permanent_failure", extra={**extra, "status_code": result_send.status_code})
                else:
                    attempts = row["attempts"] + 1
                    base = self.settings.retry_base_seconds * (2 ** row["attempts"])
                    delay = min(self.settings.retry_max_seconds, base) * (0.5 + random.random())
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                    status = self.store.mark_retry(
                        row["key"], result_send.error or "fallo transitorio", retry_at, self.settings.send_max_attempts
                    )
                    logger.warning("item_send_retry" if status == "processed" else "item_send_attempts_exhausted", extra={**extra, "attempts": attempts})

        self._write_heartbeat()
        return self.store.counts()

    def _write_heartbeat(self) -> None:
        path = self.settings.heartbeat_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"lastSuccessfulPass": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        temporary.replace(path)


def describe_validation_error(exc: ValidationError) -> str:
    """Field names and error types only: pydantic's message includes input values (secrets)."""
    problems = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error.get("loc", ())) or "?"
        problems.append(f"{field} ({error.get('type', 'invalid')})")
    return "campos faltantes o invalidos: " + ", ".join(problems)


def dry_run_state_path(path: Path) -> Path:
    """Dry runs keep their own outbox so their items are never sent by a later live run."""
    return path.with_name(f"{path.stem}.dry-run{path.suffix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autopublicador de DuoNoticias")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--once", action="store_true", help="Ejecutar una pasada y salir")
    modes.add_argument("--verify", action="store_true", help="Mostrar conteos sin modificar nada")
    parser.add_argument("--dry-run", action="store_true", help="Procesar y persistir, pero no enviar a DuoNoticias")
    parser.add_argument("--env-file", default=".env", help="Ruta del archivo .env")
    return parser


def cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    try:
        settings = Settings.load(args.env_file)
        effective_dry_run = bool(args.dry_run or settings.dry_run)
        settings.assert_safe_machine(effective_dry_run=effective_dry_run or args.verify)
    except ValidationError as exc:
        logger.error(f"configuration_error: {describe_validation_error(exc)}")
        return 2
    except Exception as exc:
        logger.error(f"configuration_error: {exc}")
        return 2

    if args.verify:
        print(json.dumps(StateStore.read_counts(settings.state_db_path), ensure_ascii=False, sort_keys=True))
        return 0

    state_db_path = dry_run_state_path(settings.state_db_path) if effective_dry_run else settings.state_db_path
    if effective_dry_run:
        logger.info(f"dry_run_uses_separate_state_db path={state_db_path}")
    store = StateStore(state_db_path)
    hs = HolaSaltaClient(
        settings.hs_api_url,
        settings.hs_api_username,
        settings.hs_api_password,
        max_retries=settings.hs_max_retries,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
    )
    duo = DuoClient(settings.duo_api_url, settings.duo_api_token)
    app = AutoPublisher(settings, store, hs, duo, dry_run=effective_dry_run)
    stop = threading.Event()

    def request_stop(signum: int, frame: object) -> None:
        logger.info("shutdown_requested")
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    try:
        while not stop.is_set():
            try:
                counts = app.run_once()
                logger.info("poll_success " + json.dumps(counts, sort_keys=True))
            except Exception:
                logger.exception("poll_failed_will_retry")
            if args.once:
                break
            stop.wait(settings.poll_interval_seconds)
    finally:
        hs.close()
        duo.close()
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(cli())
