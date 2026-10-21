"""Descarga y verificacion de videos reales (con cache, sin repetir descargas).

Recibe el asset de video que dejo el extractor (``meta.video_kind``: mp4, hls,
tweet, onvideo, jwplayer, youtube) y devuelve un MP4 local verificado con
ffprobe: tiene pista de video, se puede leer y dura al menos
``media.min_video_seconds`` (los previews animados de 2 s no son el video de la
nota) y como mucho ``media.max_reel_seconds`` (90 s). Un video mas largo se recorta a sus
primeros 90 s si ``media.trim_long_videos`` esta activo (un unico tramo, nunca partes); si no,
no se usa (``too_long``). Cada URL se baja una sola vez: ``data/media_cache/<sha1(url)>.mp4``; los
ciclos siguientes reutilizan el archivo y su resultado de ffprobe.

Los fallos se informan con un motivo legible (``VideoUnavailable.reason``) para
registrarlo y aplicar la alternativa de la fuente (imagen en las locales;
descarte en Paparazzi, TN e Infobae). Nunca se reemplaza por una foto animada.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from storage.models import Asset
from utils.tls import ca_bundle_for

LOGGER = logging.getLogger("duo.media")
# Margen sobre el tope del reel (redondeos de duracion entre contenedores).
TOLERANCE_SECONDS = 0.5
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


class VideoUnavailable(RuntimeError):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class ResolvedVideo:
    path: str
    duration_seconds: float
    width: int
    height: int
    has_audio: bool
    source_url: str
    kind: str
    cache_hit: bool = False
    text: str = ""
    # True si el original duraba mas que el tope y se recorto a sus primeros segundos.
    trimmed: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def probe_video(path: str, ffprobe: str = "ffprobe") -> Dict[str, Any]:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoUnavailable("probe_failed", str(exc)) from exc
    if result.returncode != 0:
        raise VideoUnavailable("unsupported_format", (result.stderr or "").strip()[-200:])
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError as exc:
        raise VideoUnavailable("unsupported_format", "ffprobe sin json") from exc
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise VideoUnavailable("unsupported_format", "sin pista de video")
    duration = float((data.get("format") or {}).get("duration") or 0.0)
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "codec": str(video.get("codec_name") or ""),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


class MediaResolver:
    def __init__(
        self,
        cache_dir: Path,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        min_seconds: float = 5.0,
        max_download_mb: float = 400.0,
        timeout_seconds: int = 240,
        max_seconds: float = 90.0,
        trim_long: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.min_seconds = float(min_seconds)
        self.max_bytes = int(max_download_mb * 1024 * 1024)
        self.timeout = int(timeout_seconds)
        # Tope del reel (video completo). Se bajan 2 s de mas para saber si el original lo supera
        # sin descargar el resto.
        self.max_seconds = float(max_seconds)
        # Mas largo que el tope: se usan solo los primeros max_seconds (si no, too_long).
        self.trim_long = bool(trim_long)

    # -- API ----------------------------------------------------------------

    def resolve_asset(self, asset: Asset) -> ResolvedVideo:
        if asset.path and Path(asset.path).exists():
            return self._verified(Path(asset.path), source_url=asset.path, kind="local", cache_hit=True)
        url = str(asset.remote_url or "").strip()
        if not url:
            raise VideoUnavailable("no_video_url")
        kind = str((asset.meta or {}).get("video_kind") or "") or _guess_kind(url)
        declared = float(asset.duration_seconds or 0.0)
        if declared > self.max_seconds + TOLERANCE_SECONDS and not self.trim_long:
            raise VideoUnavailable("too_long", f"{declared:.0f}s > {self.max_seconds:.0f}s (duracion declarada)")
        return self.resolve(url, kind)

    def resolve(self, url: str, kind: str) -> ResolvedVideo:
        target = self.cache_dir / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.mp4"
        meta_path = target.with_suffix(".json")
        cached = self._read_meta(meta_path)
        if self.trim_long and cached.get("reason") == "too_long":
            # Descartado antes de activar el recorte: se vuelve a bajar y se recorta.
            cached = {}
        if target.exists() and target.stat().st_size > 0 and cached.get("status") != "unusable":
            try:
                return self._verified(target, source_url=url, kind=kind, cache_hit=True, text=str(cached.get("text") or ""))
            except VideoUnavailable as exc:
                target.unlink(missing_ok=True)
                self._write_meta(meta_path, {"status": "unusable", "reason": exc.reason, "detail": exc.detail, "url": url})
                raise
        if cached.get("status") == "unusable":
            raise VideoUnavailable(str(cached.get("reason") or "unusable"), "resultado en cache")
        text = ""
        try:
            if kind == "mp4":
                self._download_mp4(url, target)
            elif kind == "hls":
                self._download_hls(url, target)
            elif kind == "onvideo":
                self._download_hls(self._onvideo_manifest(url), target)
            elif kind == "jwplayer":
                from extractors.news.paparazzi import resolve_jwplayer

                media_id = url.rstrip("/").rsplit("/", 1)[-1]
                candidate = resolve_jwplayer(media_id)
                if candidate is None:
                    raise VideoUnavailable("download_failed", f"jwplayer {media_id} sin mp4")
                self._download_mp4(candidate.url, target)
            elif kind in {"tweet", "youtube"}:
                text = self._download_ytdlp(url, target)
            else:
                raise VideoUnavailable("unsupported_format", f"tipo de video desconocido: {kind}")
            resolved = self._verified(target, source_url=url, kind=kind, text=text)
        except VideoUnavailable as exc:
            target.unlink(missing_ok=True)
            # Lo definitivamente inutilizable no se vuelve a bajar en cada ciclo.
            if exc.reason in {"too_short", "too_long", "unsupported_format", "too_large"}:
                self._write_meta(meta_path, {"status": "unusable", "reason": exc.reason, "detail": exc.detail, "url": url})
            raise
        self._write_meta(meta_path, {"status": "ok", "url": url, "kind": kind, "text": text, **resolved.as_dict()})
        return resolved

    # -- verificacion ---------------------------------------------------------

    def _verified(self, path: Path, *, source_url: str, kind: str, cache_hit: bool = False, text: str = "") -> ResolvedVideo:
        info = probe_video(str(path), self.ffprobe)
        if info["duration"] < self.min_seconds:
            raise VideoUnavailable("too_short", f"{info['duration']:.1f}s < {self.min_seconds:.0f}s")
        trimmed = False
        if info["duration"] > self.max_seconds + TOLERANCE_SECONDS:
            if not self.trim_long:
                raise VideoUnavailable("too_long", f"{info['duration']:.0f}s > {self.max_seconds:.0f}s")
            path = self._trim(path)
            info = probe_video(str(path), self.ffprobe)
            trimmed = True
        if info["width"] <= 0 or info["height"] <= 0:
            raise VideoUnavailable("unsupported_format", "dimensiones invalidas")
        return ResolvedVideo(
            path=str(path),
            duration_seconds=round(float(info["duration"]), 2),
            width=int(info["width"]),
            height=int(info["height"]),
            has_audio=bool(info["has_audio"]),
            source_url=source_url,
            kind=kind,
            cache_hit=cache_hit,
            text=text,
            trimmed=trimmed,
        )

    def _trim(self, path: Path) -> Path:
        """Primeros max_seconds del video (copia directa; si queda largo, recodifica).

        Un archivo de la cache se reemplaza; uno local de otro lado se recorta a la cache.
        """
        inside = path.parent.resolve() == self.cache_dir.resolve()
        target = path if inside else self.cache_dir / f"{hashlib.sha1(str(path).encode('utf-8')).hexdigest()}.mp4"
        part = target.with_name(target.stem + ".trim.mp4")
        seconds = f"{self.max_seconds:.3f}"
        attempts = (
            ["-c", "copy"],
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"],
        )
        for codec in attempts:
            command = [self.ffmpeg, "-v", "error", "-y", "-i", str(path), "-t", seconds, *codec, "-movflags", "+faststart", str(part)]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                part.unlink(missing_ok=True)
                continue
            if result.returncode == 0 and part.exists():
                duration = probe_video(str(part), self.ffprobe)["duration"]
                if 0 < duration <= self.max_seconds + TOLERANCE_SECONDS:
                    part.replace(target)
                    return target
            part.unlink(missing_ok=True)
        raise VideoUnavailable("trim_failed", f"no se pudo recortar a {self.max_seconds:.0f}s")

    # -- descargas -------------------------------------------------------------

    def _download_mp4(self, url: str, target: Path) -> None:
        """Primero el tramo inicial con ffmpeg (lee por rangos HTTP); si no, el archivo entero."""
        try:
            self._download_hls(url, target)
        except VideoUnavailable:
            self._download_http(url, target)

    def _download_http(self, url: str, target: Path) -> None:
        part = target.with_suffix(".part")
        try:
            with requests.get(url, headers={"User-Agent": _UA}, stream=True, timeout=60, verify=ca_bundle_for(url)) as response:
                if response.status_code >= 400:
                    raise VideoUnavailable("download_failed", f"HTTP {response.status_code}")
                content_type = str(response.headers.get("content-type") or "").lower()
                if content_type.startswith(("text/", "application/json")):
                    raise VideoUnavailable("unsupported_format", f"content-type {content_type}")
                written = 0
                with part.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        written += len(chunk)
                        if written > self.max_bytes:
                            raise VideoUnavailable("too_large", f"> {self.max_bytes // (1024 * 1024)} MB")
                        handle.write(chunk)
            part.replace(target)
        except requests.RequestException as exc:
            raise VideoUnavailable("download_failed", str(exc)[:200]) from exc
        finally:
            part.unlink(missing_ok=True)

    def _download_hls(self, manifest: str, target: Path) -> None:
        part = target.with_name(target.stem + ".part.mp4")
        command = [
            self.ffmpeg, "-v", "error", "-y", "-user_agent", _UA, "-i", manifest,
            "-t", f"{self.max_seconds + 2:.0f}", "-c", "copy", "-bsf:a", "aac_adtstoasc", str(part),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            part.unlink(missing_ok=True)
            raise VideoUnavailable("download_failed", "timeout HLS") from exc
        if result.returncode != 0 or not part.exists():
            part.unlink(missing_ok=True)
            raise VideoUnavailable("download_failed", (result.stderr or "").strip()[-200:])
        part.replace(target)

    def _onvideo_manifest(self, embed_url: str) -> str:
        try:
            response = requests.get(embed_url, headers={"User-Agent": _UA, "Referer": "https://www.eltribuno.com/"}, timeout=20)
        except requests.RequestException as exc:
            raise VideoUnavailable("download_failed", str(exc)[:200]) from exc
        match = re.search(r"https://cdn\.onvideo\.news/[^\"'\s]+/master\.m3u8", response.text or "")
        if not match:
            raise VideoUnavailable("download_failed", "onvideo sin manifiesto")
        return match.group(0)

    def _download_ytdlp(self, url: str, target: Path) -> str:
        """Tuit incrustado o YouTube: una sola URL, nunca recorrido de cuentas."""
        info_path = target.with_suffix(".info.json")
        command = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "--quiet",
            "-f", "b[ext=mp4]/bv*[ext=mp4]+ba[ext=m4a]/b", "-S", "res:1080,ext:mp4",
            "--max-filesize", f"{self.max_bytes // (1024 * 1024)}M",
            "--write-info-json", "-o", str(target), url,
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise VideoUnavailable("download_failed", "timeout yt-dlp") from exc
        if result.returncode != 0 or not target.exists():
            stderr = (result.stderr or "").strip()
            reason = "no_video_in_post" if "No video could be found" in stderr else "download_failed"
            raise VideoUnavailable(reason, stderr.splitlines()[-1][:200] if stderr else "")
        text = ""
        if info_path.exists():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                text = str(info.get("description") or info.get("title") or "")
            except ValueError:
                text = ""
            info_path.unlink(missing_ok=True)
        return text

    @staticmethod
    def _read_meta(path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_meta(path: Path, payload: Dict[str, Any]) -> None:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass


def _guess_kind(url: str) -> str:
    from extractors.news.media import classify_video_url

    return classify_video_url(url) or "mp4"
