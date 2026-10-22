"""Agenda de los formatos: corre al final de cada ciclo horario y decide que toca.

Turnos (hora local, una vez por dia, ver ``config/formats.yaml``):
- 7 h  historia del clima (y post si el SMN tiene alerta para Salta)
- 8 h  "Lo que tenes que saber hoy" (carrusel IG + post con fotos en FB) + historia
- 9 h  historia de servicios (agua, luz, pasos); post si aparece un corte o se cierra un paso
- 10 h proximo feriado (lunes de la semana del feriado y 3 dias antes)
- 11 h dolar (dias habiles)
- 20 h historia "Lo mas importante del dia"; domingos, reel del top 5 semanal
Cada ciclo: historia de las notas publicadas (local destacada o urgente),
actualizaciones de noticias en desarrollo, respuestas a comentarios y reporte.

Nada de esto llama a Gemini salvo las respuestas a comentarios y el reporte.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import yaml

from formats import pieces, sources
from formats.publish import FormatsPublisher, Outcome
from formats.store import FormatsStore
from formatter.motion_engine import MotionEngine
from publishers.meta_api import MetaGraphPublisher
from storage.settings import PipelineSettings
from utils.machine_guard import is_production_machine

LOGGER = logging.getLogger("duo.formats")


def load_config(base_dir: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load((base_dir / "config" / "formats.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


class FormatsRunner:
    def __init__(
        self,
        settings: PipelineSettings,
        publisher: MetaGraphPublisher,
        *,
        config: Optional[Dict[str, Any]] = None,
        engine: Optional[MotionEngine] = None,
        collect: Optional[Callable[[date], Any]] = None,
        usage_sink: Optional[Callable[..., None]] = None,
    ) -> None:
        self.settings = settings
        self.config = config if config is not None else load_config(settings.base_dir)
        self.zone = ZoneInfo(settings.timezone)
        self.store = FormatsStore(settings.sqlite_path)
        self.out = settings.data_dir / "formats"
        self.photo_dir = self.out / "photos"
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        self.publisher = FormatsPublisher(publisher, ig_reserve=int(self.config.get("ig_reserve", 25)))
        self.meta = publisher
        self._engine = engine
        self.collect = collect or sources.collect_all
        sources.TOKEN_CACHE = settings.data_dir / "runtime" / "smn_token.txt"
        self.usage_sink = usage_sink
        self.platforms = list(self.config.get("platforms") or ["instagram", "facebook"])
        self._service: Optional[Dict[str, Any]] = None
        # Formatos forzados a mano (CLI): se ignoran hora, dia y "ya salio hoy".
        self.force: set = set()

    # ------------------------------------------------------------------
    # Entrada principal
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def section(self, name: str) -> Dict[str, Any]:
        value = self.config.get(name)
        return value if isinstance(value, dict) else {}

    def run(self, *, now: Optional[datetime] = None, published_keys: Sequence[str] = (), publish_enabled: bool = True) -> Dict[str, Any]:
        """Un paso de la agenda. Nunca lanza: cada formato aislado registra su falla."""
        summary: Dict[str, Any] = {}
        if not self.enabled or not publish_enabled or not (is_production_machine() or isinstance(self.publisher, DryPublisher)):
            return summary
        now = (now or datetime.now(timezone.utc)).astimezone(self.zone)
        steps: List[tuple] = [
            ("snapshot", lambda: self.account_snapshot(now)),
            ("service_data", lambda: self.service_data(now)),
            ("note_stories", lambda: self.note_stories(published_keys, now)),
            ("updates", lambda: self.updates(published_keys, now)),
            ("weather", lambda: self.weather(now)),
            ("digest", lambda: self.digest(now)),
            ("services", lambda: self.services(now)),
            ("holidays", lambda: self.holidays(now)),
            ("dollar", lambda: self.dollar(now)),
            ("recap", lambda: self.recap(now)),
            ("weekly", lambda: self.weekly(now)),
            ("comments", lambda: self.comments(now)),
            ("report", lambda: self.report(now)),
        ]
        try:
            for name, step in steps:
                try:
                    result = step()
                    if result:
                        summary[name] = result
                except Exception as exc:
                    LOGGER.exception("formato %s fallo: %s", name, exc)
                    summary[name] = {"error": str(exc)[:200]}
        finally:
            self.close()
        return summary

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()

    @property
    def engine(self) -> MotionEngine:
        if self._engine is None:
            self._engine = MotionEngine(self.settings)
        return self._engine

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _due(self, name: str, now: datetime, *, hour: Optional[int] = None) -> Optional[str]:
        """Slot del dia si el formato esta activo, ya es la hora y todavia no salio."""
        cfg = self.section(name)
        if name in self.force:
            return f"{name}:{now.date().isoformat()}"
        if not cfg.get("enabled", True):
            return None
        start = int(hour if hour is not None else cfg.get("hour", 0))
        if not (start <= now.hour < start + int(self.config.get("window_hours", 3))):
            return None
        slot = f"{name}:{now.date().isoformat()}"
        return None if self.store.run_status(slot) == "done" else slot

    def _render(self, built: Dict[str, Any], name: str, kind: str = "jpeg") -> str:
        ext = "mp4" if kind == "mp4" else "jpg"
        out = self.out / datetime.now(self.zone).strftime("%Y-%m-%d") / f"{name}.{ext}"
        result = self.engine.worker.render(built, out, kind, timeout=600 if kind == "mp4" else None)
        return str(result.get("out") or out)

    def _record(self, slot: str, kind: str, outcomes: Sequence[Outcome]) -> Dict[str, str]:
        for o in outcomes:
            self.store.save_publication(slot, kind, o.platform, o.post_type, o.status, media_id=o.media_id, permalink=o.permalink, error=o.error, payload=o.payload)
            if o.status not in ("published", "dry_run"):
                LOGGER.warning("%s en %s: %s", kind, o.platform, o.error[:200])
        return {f"{o.platform}:{o.post_type}": o.status for o in outcomes}

    def _stories_left(self, now: datetime) -> int:
        cfg = self.section("stories")
        if not cfg.get("enabled", True):
            return 0
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        return int(cfg.get("max_per_day", 20)) - self.store.stories_since(day_start)

    def _story(self, slot: str, kind: str, built: Dict[str, Any], now: datetime, *, force: bool = False) -> Dict[str, str]:
        """Historia en IG y FB, dentro del tope diario y la reserva de cupo de IG."""
        if not force and self._stories_left(now) <= 0:
            return {"skipped": "tope_diario_de_historias"}
        platforms = list(self.platforms)
        if "instagram" in platforms and not self.publisher.ig_room():
            platforms.remove("instagram")
        platforms = [p for p in platforms if not self.store.published(slot, p, "story")]
        if not platforms:
            return {"skipped": "sin_cupo_o_ya_publicada"}
        path = self._render(built, slot.replace(":", "_"))
        return self._record(slot, kind, self.publisher.story(path, platforms=platforms))

    def _feed_platforms(self, slot: str, post_type: str) -> List[str]:
        platforms = [p for p in self.platforms if not self.store.published(slot, p, post_type)]
        if "instagram" in platforms and not self.publisher.ig_room():
            platforms.remove("instagram")
        return platforms

    def _notes(self, since: datetime, *, with_views: bool = False, platforms: Sequence[str] = ("instagram",)) -> List[pieces.NoteView]:
        """Notas publicadas en ``platforms`` desde ``since`` (con sus vistas maximas), una fila por nota."""
        query = f"""
            SELECT i.*, p.published_at, p.permalink, p.platform_media_id,
                   COALESCE((SELECT MAX(views) FROM analytics_snapshots a WHERE a.publication_id = p.id), 0) AS views
            FROM publications p JOIN content_items i USING(content_key)
            WHERE p.platform IN ({','.join('?' * len(platforms))}) AND p.status = 'published' AND p.published_at >= ?
            ORDER BY p.published_at
        """
        with self.store.connection() as conn:
            found = conn.execute(query, (*platforms, since.astimezone(timezone.utc).replace(microsecond=0).isoformat())).fetchall()
        rows = list({str(r["content_key"]): dict(r) for r in reversed(found)}.values())[::-1]
        notes = [pieces.NoteView(r, self.photo_dir, self.settings.ffmpeg_path) for r in rows]
        return sorted(notes, key=lambda n: -n.views) if with_views else notes

    def service_data(self, now: datetime) -> Dict[str, Any]:
        if self._service is None:
            data, health = self.collect(now.date())
            self.store.save_health(health)
            self._service = data
        return {k: bool(v) for k, v in self._service.items()}

    # ------------------------------------------------------------------
    # Seguidores (crecimiento para el reporte)
    # ------------------------------------------------------------------

    def account_snapshot(self, now: datetime) -> Optional[Dict[str, Any]]:
        day = now.date().isoformat()
        out: Dict[str, Any] = {}
        if not self.store.has_snapshot(day, "instagram") and self.settings.ig_user_id:
            info = self.meta._request("GET", f"/{self.settings.ig_user_id}", params={"fields": "followers_count,media_count"}, access_token=self.settings.ig_access_token)
            self.store.save_snapshot(day, "instagram", info.get("followers_count"), info.get("media_count"))
            out["instagram"] = info.get("followers_count")
        if not self.store.has_snapshot(day, "facebook"):
            try:
                page = self.meta._get_fb_page_id()
                info = self.meta._request("GET", f"/{page}", params={"fields": "followers_count,fan_count"}, access_token=self.meta._get_fb_publish_token())
                self.store.save_snapshot(day, "facebook", info.get("followers_count") or info.get("fan_count"), None)
                out["facebook"] = info.get("followers_count") or info.get("fan_count")
            except Exception as exc:
                LOGGER.warning("seguidores de Facebook: %s", exc)
        return out or None

    # ------------------------------------------------------------------
    # Historias de las notas del ciclo
    # ------------------------------------------------------------------

    def note_stories(self, keys: Sequence[str], now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("stories")
        if not keys or not cfg.get("enabled", True):
            return None
        since = now - timedelta(hours=3)
        # Feed de IG separado (2026-10-21): las notas que salen solo en Facebook tambien tienen su historia.
        notes = [n for n in self._notes(since, platforms=("instagram", "facebook")) if n.key in set(keys)]
        out: Dict[str, Any] = {}
        groups = set(cfg.get("post_story_groups") or ["local"])
        breaking = [n for n in notes if n.urgent and cfg.get("breaking", True)]
        for note in breaking:
            published = datetime.fromisoformat(str(note.row.get("published_at"))).astimezone(self.zone)
            built = pieces.story_breaking(note, published)
            if built:
                out[f"breaking:{note.key[:8]}"] = self._story(f"story-breaking:{note.key}", "story-breaking", built, now, force=True)
        regular = sorted([n for n in notes if n.group in groups and n not in breaking], key=lambda n: -n.relevance)
        for note in regular[: int(cfg.get("post_stories_per_cycle", 1))]:
            built = pieces.story_post(note)
            if built:
                out[f"post:{note.key[:8]}"] = self._story(f"story-post:{note.key}", "story-post", built, now)
        return out or None

    # ------------------------------------------------------------------
    # Noticias en desarrollo
    # ------------------------------------------------------------------

    def updates(self, keys: Sequence[str], now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("updates")
        if not keys or not cfg.get("enabled", True):
            return None
        out: Dict[str, Any] = {}
        with self.store.connection() as conn:
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM content_items WHERE event_role = 'update' AND content_key IN ({','.join('?' * len(keys))})", list(keys)).fetchall()]
        for row in rows:
            slot = f"update:{row['content_key']}"
            if self.store.run_status(slot) == "done":
                continue
            out[row["content_key"][:8]] = self._apply_update(row, slot, now, cfg)
            self.store.set_run(slot, "update", "done", out[row["content_key"][:8]])
        return out or None

    def _apply_update(self, row: Dict[str, Any], slot: str, now: datetime, cfg: Dict[str, Any]) -> Dict[str, Any]:
        with self.store.connection() as conn:
            previous = conn.execute(
                """SELECT i.content_key, i.title, i.summary, i.body_text, i.source, i.created_at FROM content_items i
                   WHERE i.event_key = ? AND i.content_key != ? AND i.pipeline_status = 'published'
                   ORDER BY i.updated_at LIMIT 1""",
                (row.get("event_key"), row["content_key"]),
            ).fetchone()
            if previous is None:
                return {"skipped": "sin_post_original"}
            previous = dict(previous)
            pubs = {r["platform"]: dict(r) for r in conn.execute("SELECT * FROM publications WHERE content_key = ? AND status = 'published'", (previous["content_key"],)).fetchall()}
        note = pieces.NoteView({**row, "views": 0}, self.photo_dir, self.settings.ffmpeg_path)
        old_text = " ".join(str(previous.get(k) or "") for k in ("title", "summary", "body_text"))
        new_text = " ".join(str(row.get(k) or "") for k in ("title", "summary", "body_text"))
        change = pieces.figure_change(old_text, new_text)
        stamp = now.strftime("%d/%m %H:%M")
        source = pieces.SOURCE_NAMES.get(str(row.get("source") or ""), str(row.get("source") or ""))
        if change:
            line = f"🔄 ACTUALIZACIÓN {stamp} h: la cifra de {change['noun']} pasó de {change['before']} a {change['after']}, según {source}."
        else:
            line = f"🔄 ACTUALIZACIÓN {stamp} h: {note.headline.replace('*', '')}. Más datos en nuestro último post."
        out: Dict[str, Any] = {"change": change}
        if cfg.get("story", True):
            before = after = None
            if change:
                try:
                    old_at = datetime.fromisoformat(str(previous.get("created_at")).replace("Z", "+00:00")).astimezone(self.zone).strftime("%d/%m %H:%M h")
                except ValueError:
                    old_at = ""
                before = {"value": str(change["before"]), "label": change["noun"], "time": old_at, "source": pieces.SOURCE_NAMES.get(str(previous.get("source")), str(previous.get("source")))}
                after = {"value": str(change["after"]), "label": change["noun"], "time": f"{stamp} h", "source": source}
            else:
                after = {"time": f"{stamp} h"}
            out["story"] = self._story(slot, "story-update", pieces.story_update(note, note.headline, before, after), now, force=True)
        fb = pubs.get("facebook")
        if fb and cfg.get("facebook_edit", True):
            original = str(fb.get("caption") or "")
            message = f"{line}\n\n{original}"[:1990]
            outcome = self.publisher.facebook_edit(str(fb.get("platform_post_id") or fb.get("platform_media_id")), message, video=str(fb.get("post_type")) == "reel")
            out.update(self._record(slot, "update-edit", [outcome]))
        ig = pubs.get("instagram")
        if ig and cfg.get("instagram_comment", True):
            outcome = self.publisher.instagram_comment(str(ig.get("platform_media_id")), line)
            out.update(self._record(slot, "update-comment", [outcome]))
        return out

    # ------------------------------------------------------------------
    # Turnos fijos
    # ------------------------------------------------------------------

    def weather(self, now: datetime) -> Optional[Dict[str, Any]]:
        data = (self._service or {}).get("weather")
        out: Dict[str, Any] = {}
        slot = self._due("weather_story", now)
        if slot and data:
            built = pieces.piece("weather-story", "board", "reel", pieces.weather_extra(data, now.date()))
            out["story"] = self._story(slot, "weather-story", built, now)
            self.store.set_run(slot, "weather_story", "done", out["story"])
        alert_cfg = self.section("weather_alert_post")
        level = (data or {}).get("alert_levels", {}).get(now.date().isoformat(), 1)
        if data and alert_cfg.get("enabled", True) and (level >= int(alert_cfg.get("min_level", 2)) or "weather_alert_post" in self.force):
            slot = f"weather_alert:{now.date().isoformat()}:{level}"
            if self.store.run_status(slot) != "done":
                path = self._render(pieces.piece("weather", "board", "portrait", pieces.weather_extra(data, now.date())), slot.replace(":", "_"))
                out["alert_post"] = self._record(slot, "weather-alert", self.publisher.post(pieces.weather_caption(data, now.date()), [path], platforms=self._feed_platforms(slot, "image")))
                self.store.set_run(slot, "weather_alert", "done", out["alert_post"])
        return out or None

    def digest(self, now: datetime) -> Optional[Dict[str, Any]]:
        slot = self._due("digest", now)
        if not slot:
            return None
        cfg = self.section("digest")
        start = (now - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
        # Con el feed de IG separado, el resumen es la forma de llevar al feed las notas que salieron solo en Facebook.
        notes = pieces.pick_digest(self._notes(start, platforms=("instagram", "facebook")), size=int(cfg.get("size", 5)))
        if len(notes) < 3:
            self.store.set_run(slot, "digest", "done", {"skipped": f"pocas_notas:{len(notes)}"})
            return {"skipped": f"pocas_notas:{len(notes)}"}
        service = self._service or {}
        built = pieces.digest_pieces(notes, service.get("weather"), service.get("dollar"), service.get("holidays"), now.date())
        paths = [self._render(b, f"digest_{i}") for i, b in enumerate(built)]
        caption = pieces.digest_caption(notes, service.get("weather"), now.date())
        out = {"post": self._record(slot, "digest", self.publisher.post(caption, paths, platforms=self._feed_platforms(slot, "carousel")))}
        if cfg.get("story", True):
            out["story"] = self._story(slot, "digest-story", pieces.piece("digest-story", "story", "reel", {"kind": "story-post", "image": paths[0], "headline": "Lo que tenés que saber hoy"}), now)
        self.store.set_run(slot, "digest", "done", out)
        return out

    def services(self, now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("services")
        if not cfg.get("enabled", True):
            return None
        service = self._service or {}
        extra = pieces.services_extra(service.get("water"), service.get("power"), service.get("passes"), now)
        out: Dict[str, Any] = {}
        slot = self._due("services", now, hour=int(cfg.get("story_hour", 9)))
        if slot:
            out["story"] = self._story(slot, "services-story", pieces.piece("services-story", "board", "reel", extra), now)
            self.store.set_run(slot, "services", "done", out["story"])
        if cfg.get("post_on_change", True):
            signature = self._services_signature(service)
            last = self.store.last_run("services_state")
            previous = json.loads(last["detail_json"]).get("signature") if last else None
            state_slot = f"services_state:{now.strftime('%Y-%m-%dT%H')}"
            if previous is not None and signature["alerts"] and signature["alerts"] != previous.get("alerts") and 7 <= now.hour <= 22:
                path = self._render(pieces.piece("services", "board", "portrait", extra), state_slot.replace(":", "_"))
                out["post"] = self._record(state_slot, "services", self.publisher.post(pieces.services_caption(extra), [path], platforms=self._feed_platforms(state_slot, "image")))
            self.store.set_run(state_slot, "services_state", "done", {"signature": signature})
        return out or None

    @staticmethod
    def _services_signature(service: Dict[str, Any]) -> Dict[str, Any]:
        """Lo que justifica un post: cortes de agua vigentes y pasos cerrados (los cerrados de siempre no)."""
        alerts: List[str] = []
        for cut in (service.get("water") or {}).get("cuts") or []:
            alerts.append(f"agua:{cut['zone']}:{cut['date']}")
        for p in service.get("passes") or []:
            if p["state"] != "ABIERTO":
                alerts.append(f"paso:{p['name']}")
        return {"alerts": sorted(alerts)}

    def holidays(self, now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("holidays")
        slot = self._due("holidays", now)
        data = (self._service or {}).get("holidays")
        if not slot or not data:
            return None
        first = date.fromisoformat(data[0]["fecha"])
        days = (first - now.date()).days
        week_monday = now.weekday() == 0 and days <= 6 and cfg.get("monday_of_week", True)
        if days != int(cfg.get("days_before", 3)) and not week_monday and "holidays" not in self.force:
            return None
        path = self._render(pieces.piece("holidays", "board", "portrait", pieces.holidays_extra(data, now.date())), slot.replace(":", "_"))
        out = self._record(slot, "holidays", self.publisher.post(pieces.holidays_caption(data, now.date()), [path], platforms=self._feed_platforms(slot, "image")))
        self.store.set_run(slot, "holidays", "done", out)
        return out

    def dollar(self, now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("dollar")
        slot = self._due("dollar", now)
        quotes = (self._service or {}).get("dollar")
        if not slot or not quotes:
            return None
        holidays = {h["fecha"] for h in (self._service or {}).get("holidays") or []}
        if cfg.get("weekdays_only", True) and (now.weekday() >= 5 or now.date().isoformat() in holidays) and "dollar" not in self.force:
            return None
        path = self._render(pieces.piece("dollar", "board", "portrait", pieces.dollar_extra(quotes, now)), slot.replace(":", "_"))
        out = self._record(slot, "dollar", self.publisher.post(pieces.dollar_caption(quotes), [path], platforms=self._feed_platforms(slot, "image")))
        self.store.set_run(slot, "dollar", "done", out)
        return out

    def recap(self, now: datetime) -> Optional[Dict[str, Any]]:
        slot = self._due("recap", now)
        if not slot:
            return None
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        notes = [n for n in self._notes(start, with_views=True) if n.photo()][: int(self.section("recap").get("size", 5))]
        if len(notes) < 3:
            self.store.set_run(slot, "recap", "done", {"skipped": "pocas_notas"})
            return {"skipped": "pocas_notas"}
        out = self._story(slot, "recap", pieces.story_recap(notes, now.date()), now, force=True)
        self.store.set_run(slot, "recap", "done", out)
        return out

    def weekly(self, now: datetime) -> Optional[Dict[str, Any]]:
        cfg = self.section("weekly")
        if now.weekday() != int(cfg.get("weekday", 6)) and "weekly" not in self.force:
            return None
        slot = self._due("weekly", now)
        if not slot:
            return None
        start = now - timedelta(days=7)
        notes = [n for n in self._notes(start, with_views=True) if n.photo()][: int(cfg.get("size", 5))]
        if len(notes) < 5:
            self.store.set_run(slot, "weekly", "done", {"skipped": "pocas_notas"})
            return {"skipped": "pocas_notas"}
        built = pieces.weekly_piece(notes, start.date(), now.date())
        video = self._render(built, "weekly", "mp4")
        cover = self._render(pieces.piece("weekly-cover", "story", "reel", {"kind": "story-recap", "dateLabel": "Top 5 de la semana", "items": built["content"]["extra"]["items"]}), "weekly_cover")
        out = self._record(slot, "weekly", self.publisher.reel(pieces.weekly_caption(notes), video, cover=cover, seconds=float(built["presentation"]["durationSeconds"]), platforms=self._feed_platforms(slot, "reel")))
        self.store.set_run(slot, "weekly", "done", out)
        return out

    # ------------------------------------------------------------------
    # Comentarios y reporte
    # ------------------------------------------------------------------

    def comments(self, now: datetime) -> Optional[Dict[str, Any]]:
        from formats.comments import CommentResponder

        cfg = self.section("comments")
        if not cfg.get("enabled", True) or str(cfg.get("mode", "auto")) == "off":
            return None
        return CommentResponder(self.settings, self.meta, self.store, cfg, usage_sink=self.usage_sink, publisher=self.publisher).run(now)

    def report(self, now: datetime) -> Optional[Dict[str, Any]]:
        from formats.report import OpsReport

        cfg = self.section("report")
        if not cfg.get("enabled", True) or now.hour < int(cfg.get("hour", 9)):
            return None
        reporter = OpsReport(self.settings, self.meta, self.store, cfg, usage_sink=self.usage_sink)
        if not reporter.due(now):
            return None
        return reporter.send(now)


STEPS = ("weather_story", "weather_alert_post", "digest", "services", "holidays", "dollar", "recap", "weekly", "comments", "report")


class DryPublisher(FormatsPublisher):
    """Vista previa: renderiza todo y no publica nada."""

    def __init__(self) -> None:
        self.ig_reserve = 0

    def ig_room(self, needed: int = 1) -> bool:
        return True

    def ig_usage(self) -> Dict[str, Any]:
        return {}

    @staticmethod
    def _dry(platform: str, post_type: str, **payload: Any) -> Outcome:
        return Outcome(platform, post_type, "dry_run", payload=payload)

    def story(self, path: str, *, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        return [self._dry(p, "story", path=path) for p in platforms]

    def post(self, caption: str, images: Sequence[str], *, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        return [self._dry(p, "carousel" if len(images) > 1 else "image", caption=caption, images=list(images)) for p in platforms]

    def reel(self, caption: str, video: str, *, cover: str = "", seconds: float = 0, platforms: Sequence[str] = ("instagram", "facebook")) -> List[Outcome]:
        return [self._dry(p, "reel", caption=caption, video=video, cover=cover) for p in platforms]

    def facebook_edit(self, post_id: str, message: str, *, video: bool = False) -> Outcome:
        return self._dry("facebook", "edit", post_id=post_id, message=message)

    def instagram_comment(self, media_id: str, message: str) -> Outcome:
        return self._dry("instagram", "comment", media_id=media_id, message=message)

    def reply_comment(self, platform: str, comment_id: str, message: str) -> Outcome:
        return self._dry(platform, "reply", comment_id=comment_id, message=message)


class PreviewStore(FormatsStore):
    """Lee la base real pero no marca turnos ni publicaciones."""

    def set_run(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_publication(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_snapshot(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_comment(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_report(self, *args: Any, **kwargs: Any) -> None:
        return None

    def save_health(self, *args: Any, **kwargs: Any) -> None:
        return None

    def run_status(self, slot: str) -> str:
        return ""

    def published(self, slot: str, platform: str, post_type: str) -> bool:
        return False


def run_steps(settings: PipelineSettings, publisher: MetaGraphPublisher, steps: Sequence[str], *, live: bool, usage_sink: Optional[Callable[..., None]] = None) -> Dict[str, Any]:
    """CLI: corre formatos puntuales ahora. Sin ``live`` es una vista previa (render sin publicar)."""
    from formats.comments import CommentResponder
    from formats.report import OpsReport

    runner = FormatsRunner(settings, publisher, usage_sink=usage_sink)
    if not live:
        runner.publisher = DryPublisher()
        runner.store = PreviewStore(settings.sqlite_path)
        runner.out = settings.data_dir / "formats" / "preview"
    runner.force = set(steps)
    now = datetime.now(runner.zone)
    out: Dict[str, Any] = {}
    try:
        runner.service_data(now)
        for step in steps:
            if step == "report":
                rep = OpsReport(settings, publisher, runner.store, runner.section("report"), usage_sink=usage_sink)
                if live:
                    out[step] = rep.send(now)
                else:
                    data = rep.collect(now)
                    page = rep.render(data, rep.summarize(data))
                    path = runner.out / f"ops_preview_{now:%Y%m%d_%H%M}.html"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(page, encoding="utf-8")
                    out[step] = {"preview": str(path)}
                continue
            if step == "comments":
                cfg = runner.section("comments") if live else {**runner.section("comments"), "mode": "shadow"}
                out[step] = CommentResponder(settings, publisher, runner.store, cfg, usage_sink=usage_sink, publisher=runner.publisher).run(now)
                continue
            method = runner.weather if step.startswith("weather") else getattr(runner, step)
            out[step] = method(now)
    finally:
        runner.close()
    return out


def published_keys_from(summary: Dict[str, Any]) -> List[str]:
    return [str(d.get("content_key")) for d in summary.get("decisions") or [] if d.get("status") == "published" and d.get("content_key")]

