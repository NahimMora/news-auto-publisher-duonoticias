from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import quote


FolderKind = Literal["site", "temp"]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _clean_folder(value: str, default: str) -> str:
    folder = (value or default).strip().strip("/")
    return folder or default


@dataclass(frozen=True)
class MediaStorageConfig:
    provider: str
    r2_account_id: str
    r2_endpoint_url: str
    r2_bucket: str
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_public_base_url: str
    r2_region: str
    r2_site_folder: str
    r2_temp_folder: str
    r2_delete_after_publish: bool
    r2_cache_control: str


def get_config() -> MediaStorageConfig:
    provider = os.getenv("MEDIA_STORAGE_PROVIDER", "").strip().lower() or "cloudinary"
    account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
    endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()
    if not endpoint_url and account_id:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
    public_base_url = os.getenv("R2_PUBLIC_BASE_URL", "").strip() or os.getenv("R2_CUSTOM_DOMAIN", "").strip()
    return MediaStorageConfig(
        provider=provider,
        r2_account_id=account_id,
        r2_endpoint_url=endpoint_url,
        r2_bucket=os.getenv("R2_BUCKET", "").strip(),
        r2_access_key_id=os.getenv("R2_ACCESS_KEY_ID", "").strip(),
        r2_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY", "").strip(),
        r2_public_base_url=public_base_url.rstrip("/"),
        r2_region=os.getenv("R2_REGION", "auto").strip() or "auto",
        r2_site_folder=_clean_folder(os.getenv("R2_SITE_FOLDER", ""), "img"),
        r2_temp_folder=_clean_folder(os.getenv("R2_TEMP_FOLDER", ""), "img_temp"),
        r2_delete_after_publish=_env_bool("R2_DELETE_AFTER_PUBLISH", False),
        r2_cache_control=os.getenv("R2_CACHE_CONTROL", "public, max-age=31536000, immutable").strip()
        or "public, max-age=31536000, immutable",
    )


def is_r2_selected() -> bool:
    return get_config().provider == "r2"


def upload_file(file_path: str | Path, *, folder_kind: FolderKind = "temp") -> dict[str, str]:
    path = Path(file_path)
    if not path.exists():
        raise RuntimeError(f"Media local no encontrado: {path}")
    cfg = get_config()
    if cfg.provider != "r2":
        raise RuntimeError(f"Media storage provider is not R2: {cfg.provider}")
    _validate_r2_config(cfg)
    key = _build_object_key(path, _folder_for_kind(folder_kind, cfg))
    client = _r2_client(cfg)
    extra_args = {
        "ContentType": _content_type(path),
        "CacheControl": cfg.r2_cache_control,
    }
    client.upload_file(str(path), cfg.r2_bucket, key, ExtraArgs=extra_args)
    return {
        "provider": "r2",
        "url": _public_url(cfg, key),
        "key": key,
        "bucket": cfg.r2_bucket,
        "content_type": extra_args["ContentType"],
    }


def upload_site_file(file_path: str | Path) -> dict[str, str]:
    return upload_file(file_path, folder_kind="site")


def delete_uploaded(uploaded: dict[str, str]) -> bool:
    cfg = get_config()
    if cfg.provider != "r2" or not cfg.r2_delete_after_publish:
        return False
    key = str(uploaded.get("key") or "").strip()
    if not key:
        return False
    _validate_r2_config(cfg)
    client = _r2_client(cfg)
    client.delete_object(Bucket=cfg.r2_bucket, Key=key)
    return True


def _validate_r2_config(cfg: MediaStorageConfig) -> None:
    missing = []
    if not cfg.r2_account_id and not cfg.r2_endpoint_url:
        missing.append("R2_ACCOUNT_ID")
    if not cfg.r2_bucket:
        missing.append("R2_BUCKET")
    if not cfg.r2_access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not cfg.r2_secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not cfg.r2_public_base_url:
        missing.append("R2_PUBLIC_BASE_URL")
    if cfg.r2_access_key_id.lower().startswith(("http://", "https://")):
        raise RuntimeError(
            "R2_ACCESS_KEY_ID parece una URL publica. "
            "Use el Access Key ID real de Cloudflare R2 y deje la URL publica en R2_PUBLIC_BASE_URL."
        )
    if missing:
        raise RuntimeError("R2 media storage esta seleccionado pero faltan variables: " + ", ".join(missing))


def _r2_client(cfg: MediaStorageConfig):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("Falta boto3 para subir a R2. Ejecute: pip install -r requirements.txt") from exc

    return boto3.client(
        "s3",
        endpoint_url=cfg.r2_endpoint_url,
        aws_access_key_id=cfg.r2_access_key_id,
        aws_secret_access_key=cfg.r2_secret_access_key,
        region_name=cfg.r2_region,
    )


def _folder_for_kind(folder_kind: FolderKind, cfg: MediaStorageConfig) -> str:
    return cfg.r2_site_folder if folder_kind == "site" else cfg.r2_temp_folder


def _build_object_key(path: Path, folder: str) -> str:
    stat = path.stat()
    digest_seed = f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8", errors="ignore")
    digest = hashlib.sha1(digest_seed).hexdigest()[:16]
    timestamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    filename = _safe_filename(path.name)
    return f"{folder}/{timestamp}_{digest}_{filename}"


def _safe_filename(name: str) -> str:
    stem = Path(name).stem.lower()
    suffix = Path(name).suffix.lower()
    stem = re.sub(r"[^a-z0-9._-]+", "-", stem).strip("-._")
    if not stem:
        stem = "media"
    if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ""
    return f"{stem}{suffix}"


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return "video/mp4"
    return "image/jpeg"


def _public_url(cfg: MediaStorageConfig, key: str) -> str:
    quoted_key = quote(key, safe="/._-~")
    return f"{cfg.r2_public_base_url}/{quoted_key}"
