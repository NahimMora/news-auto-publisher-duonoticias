from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from utils.machine_guard import assert_production_machine


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read a deliberately small, non-interpolating .env format."""
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "si", "sí"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"booleano invalido: {value!r}")


class Settings(BaseModel):
    hs_api_url: str = "http://127.0.0.1:8000"
    hs_api_username: str = "admin"
    hs_api_password: str
    poll_interval_seconds: float = Field(default=45, gt=0)
    duo_api_url: str
    duo_api_token: str
    state_db_path: Path = Path("state/state.db")
    initial_sync: Literal["mark_seen", "process_all", "last_n"] = "mark_seen"
    initial_sync_last_n: int = Field(default=10, ge=0)
    dry_run: bool = False
    send_max_attempts: int = Field(default=5, ge=1)
    heartbeat_path: Path = Path("state/heartbeat.json")
    hs_max_retries: int = Field(default=5, ge=1)
    retry_base_seconds: float = Field(default=1.0, gt=0)
    retry_max_seconds: float = Field(default=60.0, gt=0)

    @field_validator("dry_run", mode="before")
    @classmethod
    def parse_bool(cls, value: object) -> object:
        return _as_bool(value) if isinstance(value, (str, bool)) else value

    @field_validator("hs_api_url", "duo_api_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.rstrip("/")

    @classmethod
    def load(cls, env_file: str | Path = ".env") -> "Settings":
        values = _read_dotenv(Path(env_file))
        values.update({key: value for key, value in os.environ.items() if key in _ENV_MAP})
        kwargs = {_ENV_MAP[key]: value for key, value in values.items() if key in _ENV_MAP and value != ""}
        return cls.model_validate(kwargs)

    def assert_safe_machine(self, effective_dry_run: bool = False) -> None:
        if not effective_dry_run:
            assert_production_machine()


_ENV_MAP = {
    "HS_API_URL": "hs_api_url",
    "HS_API_USERNAME": "hs_api_username",
    "HS_API_PASSWORD": "hs_api_password",
    "POLL_INTERVAL_SECONDS": "poll_interval_seconds",
    "DUO_API_URL": "duo_api_url",
    "DUO_API_TOKEN": "duo_api_token",
    "STATE_DB_PATH": "state_db_path",
    "INITIAL_SYNC": "initial_sync",
    "INITIAL_SYNC_LAST_N": "initial_sync_last_n",
    "DRY_RUN": "dry_run",
    "SEND_MAX_ATTEMPTS": "send_max_attempts",
    "HEARTBEAT_PATH": "heartbeat_path",
    "HS_MAX_RETRIES": "hs_max_retries",
    "RETRY_BASE_SECONDS": "retry_base_seconds",
    "RETRY_MAX_SECONDS": "retry_max_seconds",
}

