"""Descarga y verificacion de videos reales (con cache, sin repetir descargas).

Recibe el asset de video que dejo el extractor (``meta.video_kind``: mp4, hls,
tweet, onvideo, jwplayer, youtube) y devuelve un MP4 local verificado con
ffprobe: tiene pista de video, se puede leer y dura al menos
``media.min_video_seconds`` (los previews animados de 2 s no son el video de la
nota) y como mucho ``media.max_reel_seconds`` (90 s). Un video mas largo se recorta a sus
primeros 90 s si ``media.trim_long_videos`` esta activo (un unico tramo, nunca partes); si no,
no se usa (``too_long``). Un original de mas de ``media.max_source_seconds`` (6 min, decision
2026-10-22: programas completos, transmisiones) no se usa nunca (``source_too_long``): la duracion
se lee antes de bajar nada (ffprobe remoto o metadatos de yt-dlp). Cada URL se baja una sola vez: ``data/media_cache/<sha1(url)>.mp4``; los
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
# Algunos Cloudflare (De Frente Salta) rechazan con 403 el User-Agent de Chrome sin el resto del
# navegador y aceptan uno simple: los archivos directos se reintentan con este.
_SIMPLE_UA = "Mozilla/5.0"


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
        max_source_seconds: float = 0.0,
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
        # Original mas largo que esto: no se usa ni recortado (0 = sin tope).
        self.max_source_seconds = float(max_source_seconds or 0.0)

    # -- API ----------------------------------------------------------------

    def resolve_asset(self, asset: Asset) -> ResolvedVideo:
        if asset.path and Path(asset.path).exists():
            return self._verified(Path(asset.path), source_url=asset.path, kind="local", cache_hit=True)
        url = str(asset.remote_url or "").strip()
        if not url:
            raise VideoUnavailable("no_video_url")
        kind = str((asset.meta or {}).get("video_kind") or "") or _guess_kind(url)
        declared = float(asset.duration_seconds or 0.0)
        self._check_source_length(declared, "duracion declarada")
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
                self._check_remote_length(url)
                self._download_mp4(url, target)
            elif kind == "hls":
                self._check_remote_length(url)
                self._download_hls(url, target)
            elif kind == "onvideo":
                stream = self._onvideo_stream(url)
                self._check_remote_length(stream)
                if stream.endswith(".m3u8"):
                    self._download_hls(stream, target)
                else:
                    self._download_mp4(stream, target)
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
            if exc.reason in {"too_short", "too_long", "unsupported_format", "too_large", "source_too_long"}:
                self._write_meta(meta_path, {"status": "unusable", "reason": exc.reason, "detail": exc.detail, "url": url})
            raise
        self._write_meta(meta_path, {"status": "ok", "url": url, "kind": kind, "text": text, **resolved.as_dict()})
        return resolved

    # -- verificacion ---------------------------------------------------------

    def _verified(self, path: Path, *, source_url: str, kind: str, cache_hit: bool = False, text: str = "") -> ResolvedVideo:
        info = probe_video(str(path), self.ffprobe)
        if info["duration"] < self.min_seconds:
            raise VideoUnavailable("too_short", f"{info['duration']:.1f}s < {self.min_seconds:.0f}s")
        # Archivo bajado entero (sin duracion previa): el tope de 6 min tambien vale aca.
        self._check_source_length(float(info["duration"]), "archivo")
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
        for user_agent in (_UA, _SIMPLE_UA):
            try:
                self._download_hls(url, target, user_agent=user_agent)
                return
            except VideoUnavailable:
                continue
        try:
            self._download_http(url, target)
        except VideoUnavailable as exc:
            if "HTTP 403" not in str(exc):
                raise
            self._download_http(url, target, user_agent=_SIMPLE_UA)

    def _download_http(self, url: str, target: Path, *, user_agent: str = _UA) -> None:
        part = target.with_suffix(".part")
        try:
            with requests.get(url, headers={"User-Agent": user_agent}, stream=True, timeout=60, verify=ca_bundle_for(url)) as response:
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

    def _download_hls(self, manifest: str, target: Path, *, user_agent: str = _UA) -> None:
        part = target.with_name(target.stem + ".part.mp4")
        command = [
            self.ffmpeg, "-v", "error", "-y", "-user_agent", user_agent, "-i", manifest,
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

    def _onvideo_stream(self, embed_url: str) -> str:
        """Manifiesto HLS del reproductor; si no lo trae (pasa en muchas notas), el MP4 directo de mayor resolucion."""
        try:
            response = requests.get(embed_url, headers={"User-Agent": _UA, "Referer": "https://www.eltribuno.com/"}, timeout=20)
        except requests.RequestException as exc:
            raise VideoUnavailable("download_failed", str(exc)[:200]) from exc
        text = response.text or ""
        match = re.search(r"https://cdn\.onvideo\.news/[^\"'\s]+/master\.m3u8", text)
        if match:
            return match.group(0)
        mp4s = re.findall(r"(https://cdn\.onvideo\.news/[^\"'\s\\]+?/video_(\d+)\.mp4)", text)
        if mp4s:
            return max(mp4s, key=lambda pair: int(pair[1]))[0]
        raise VideoUnavailable("download_failed", "onvideo sin manifiesto ni mp4")

    def _check_source_length(self, seconds: float, origin: str) -> None:
        if self.max_source_seconds and seconds > self.max_source_seconds:
            raise VideoUnavailable("source_too_long", f"{seconds:.0f}s > {self.max_source_seconds:.0f}s ({origin})")

    def _check_remote_length(self, url: str) -> None:
        """Duracion del original sin bajarlo (ffprobe lee solo la cabecera); si no se puede leer, se sigue."""
        if not self.max_source_seconds:
            return
        for user_agent in (_UA, _SIMPLE_UA):
            try:
                result = subprocess.run(
                    [self.ffprobe, "-v", "error", "-user_agent", user_agent, "-show_entries", "format=duration", "-of", "csv=p=0", url],
                    capture_output=True, text=True, timeout=60,
                )
                seconds = float((result.stdout or "").strip().splitlines()[0])
            except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
                continue
            self._check_source_length(seconds, "original")
            return

    def _download_ytdlp(self, url: str, target: Path) -> str:
        """Tuit incrustado o YouTube: una sola URL, nunca recorrido de cuentas.

        Primero los metadatos (duracion, si es transmision): un programa completo se descarta sin
        bajarlo. Despues solo el tramo inicial (max_seconds + 2 s) con ffmpeg, no el archivo entero:
        antes se bajaban programas de 450 MB que vencian el tiempo y nunca llegaban a usarse.
        """
        info = self._ytdlp_info(url)
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            raise VideoUnavailable("source_too_long", "transmision en vivo")
        duration = float(info.get("duration") or 0.0)
        self._check_source_length(duration, "metadatos")
        command = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "--quiet", "--no-part",
            "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*[height<=1080]+ba/b",
            "--merge-output-format", "mp4", "--max-filesize", f"{self.max_bytes // (1024 * 1024)}M",
            "-o", str(target), url,
        ]
        if not duration or duration > self.max_seconds + TOLERANCE_SECONDS:
            command[-3:-3] = ["--download-sections", f"*0-{self.max_seconds + 2:.0f}"]
        if Path(self.ffmpeg).parent != Path("."):
            command[-3:-3] = ["--ffmpeg-location", str(Path(self.ffmpeg).parent)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise VideoUnavailable("download_failed", "timeout yt-dlp") from exc
        finally:
            for leftover in target.parent.glob(target.stem + ".*.part*"):
                leftover.unlink(missing_ok=True)
        if result.returncode != 0 or not target.exists():
            stderr = (result.stderr or "").strip()
            raise VideoUnavailable("download_failed", stderr.splitlines()[-1][:200] if stderr else "")
        return str(info.get("description") or info.get("title") or "")

    def _ytdlp_info(self, url: str) -> Dict[str, Any]:
        command = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-warnings", "--skip-download", "--dump-single-json", url]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=90, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            raise VideoUnavailable("download_failed", "timeout yt-dlp (metadatos)") from exc
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            reason = "no_video_in_post" if "No video could be found" in stderr else "download_failed"
            raise VideoUnavailable(reason, stderr.splitlines()[-1][:200] if stderr else "")
        try:
            info = json.loads(result.stdout or "{}")
        except ValueError as exc:
            raise VideoUnavailable("download_failed", "yt-dlp sin metadatos") from exc
        return info if isinstance(info, dict) else {}

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
