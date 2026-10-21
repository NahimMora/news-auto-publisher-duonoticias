"""Avisos por correo cuando algo puntual falla (corre en el vigilante, cada hora).

Cada problema tiene una clave estable (``scraper_falla:tn``). El correo sale solo si
aparece un problema nuevo o si uno sigue abierto despues de ``repeat_hours``; cuando
un problema avisado se normaliza, el siguiente chequeo manda un "volvio a funcionar".
El estado vive en ``data/runtime/alerts_state.json``.

Chequeos (umbrales en ``config/formats.yaml`` -> ``alerts``):
- scrapers: una fuente que tira error en ciclos seguidos, o que no trae notas nuevas
  hace demasiadas horas (asi se detecto Policia, cuyas notas se tomaban como repetidas);
- publicaciones de noticias o formatos que fallaron en Instagram o Facebook;
- ciclos seguidos sin publicar con notas en espera (y el cupo de Instagram);
- errores de produccion en los ultimos ciclos y el ultimo error del servicio;
- la IA (Gemini) fallando seguido;
- fuentes de servicio (clima, dolar, cortes...) caidas hace horas;
- poco espacio en disco.
"""
from __future__ import annotations

import html
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from formats.store import FormatsStore
from storage.settings import PipelineSettings

LOGGER = logging.getLogger("duo.formats.alerts")

DEFAULTS: Dict[str, Any] = {
    "enabled": True,
    "repeat_hours": 12,
    "window_hours": 2,
    "scraper_fails_in_row": 2,
    "scraper_silence_hours": {"default": 8},
    "cycles_without_publishing": 3,
    "min_waiting_for_alert": 5,
    "production_errors": 3,
    "llm_failures": 3,
    "service_down_hours": 12,
    "min_free_disk_gb": 5,
}


@dataclass
class Problem:
    key: str
    title: str
    detail: str


def _parse(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class FailureAlerts:
    def __init__(
        self,
        settings: PipelineSettings,
        store: FormatsStore,
        cfg: Dict[str, Any],
        *,
        enabled_sources: Optional[List[str]] = None,
        quota: Optional[Callable[[], Dict[str, Any]]] = None,
        free_disk_gb: Optional[Callable[[], float]] = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.enabled_sources = enabled_sources
        self.quota = quota
        self.free_disk_gb = free_disk_gb or (lambda: shutil.disk_usage(settings.data_dir).free / 1024**3)
        self.zone = ZoneInfo(settings.timezone)
        self.state_path = settings.data_dir / "runtime" / "alerts_state.json"

    # -- chequeos ------------------------------------------------------------------------------

    def check(self, now: datetime) -> List[Problem]:
        now = now.astimezone(timezone.utc)
        problems: List[Problem] = []
        for name in ("_scrapers", "_publications", "_cycles", "_llm", "_services", "_disk"):
            try:
                problems += getattr(self, name)(now)
            except Exception as exc:  # un chequeo roto no tapa a los demas
                LOGGER.warning("chequeo %s fallo: %s", name, exc)
        return problems

    def _local(self, value: Optional[datetime]) -> str:
        return value.astimezone(self.zone).strftime("%d/%m %H:%M") if value else "nunca"

    def _scrapers(self, now: datetime) -> List[Problem]:
        out: List[Problem] = []
        health = {row["source"]: row for row in self.store.scraper_health()}
        with self.store.connection() as conn:
            latest = {r[0]: r[1] for r in conn.execute("SELECT source, MAX(extracted_at) FROM content_items GROUP BY source").fetchall()}
        silence = dict(self.cfg["scraper_silence_hours"] or {})
        default_silence = float(silence.get("default", 8))
        for source in self.enabled_sources if self.enabled_sources is not None else sorted(health):
            row = health.get(source) or {}
            if int(row.get("fails_in_row") or 0) >= int(self.cfg["scraper_fails_in_row"]):
                out.append(Problem(
                    f"scraper_falla:{source}",
                    f"El scraper de {source} está fallando",
                    f"Falló en los últimos {row['fails_in_row']} ciclos. Último error: {row.get('detail') or 'sin detalle'}. "
                    f"Última vez que funcionó: {self._local(_parse(row.get('last_ok_at')))}.",
                ))
                continue
            last_new = max(filter(None, (_parse(row.get("last_items_at")), _parse(latest.get(source)))), default=None)
            hours = float(silence.get(source, default_silence))
            if last_new is None or now - last_new > timedelta(hours=hours):
                out.append(Problem(
                    f"scraper_sin_notas:{source}",
                    f"{source} no trae notas nuevas hace más de {hours:.0f} h",
                    f"Última nota nueva: {self._local(last_new)}. El scraper responde, pero no entra nada: "
                    "puede haber cambiado la página de la fuente o las notas se están tomando como repetidas.",
                ))
        return out

    def _publications(self, now: datetime) -> List[Problem]:
        since = (now - timedelta(hours=float(self.cfg["window_hours"]))).replace(microsecond=0).isoformat()
        with self.store.connection() as conn:
            news = conn.execute(
                "SELECT platform, substr(error_message, 1, 200) error, COUNT(*) n FROM publications WHERE created_at >= ? AND status = 'failed' GROUP BY platform, error",
                (since,),
            ).fetchall()
            fmts = conn.execute(
                "SELECT platform, kind, substr(error, 1, 200) error, COUNT(*) n FROM format_publications WHERE created_at >= ? AND status = 'failed' GROUP BY platform, kind, error",
                (since,),
            ).fetchall()
        out: List[Problem] = []
        for row in news:
            out.append(Problem(f"publicacion_falla:{row['platform']}", f"Fallan publicaciones de noticias en {row['platform']}",
                               f"{row['n']} en las últimas {self.cfg['window_hours']} h. Error: {row['error'] or 'sin detalle'}"))
        for row in fmts:
            out.append(Problem(f"formato_falla:{row['platform']}:{row['kind']}", f"Falla el formato {row['kind']} en {row['platform']}",
                               f"{row['n']} en las últimas {self.cfg['window_hours']} h. Error: {row['error'] or 'sin detalle'}"))
        return out

    def _cycles(self, now: datetime) -> List[Problem]:
        with self.store.connection() as conn:
            rows = conn.execute("SELECT cycle_id, summary_json FROM cycles WHERE mode = 'live' ORDER BY started_at DESC LIMIT 6").fetchall()
        cycles = [(r["cycle_id"], json.loads(r["summary_json"] or "{}")) for r in rows]
        out: List[Problem] = []
        need = int(self.cfg["cycles_without_publishing"])
        recent = cycles[:need]
        if len(recent) == need and all(not c.get("published") for _, c in recent):
            waiting = int(((recent[0][1].get("allocation") or {}).get("waiting")) or 0)
            if waiting >= int(self.cfg["min_waiting_for_alert"]):
                quota = ""
                if self.quota:
                    try:
                        q = self.quota() or {}
                        if q:
                            quota = f" Cupo de Instagram: {q.get('quota_usage')} de {q.get('quota_total')} usados en 24 h."
                    except Exception:
                        quota = ""
                out.append(Problem("sin_publicar", f"{need} ciclos seguidos sin publicar",
                                   f"Hay {waiting} notas en espera y no salió ninguna desde el ciclo {recent[-1][0]}.{quota}"))
        errors = sum(int(c.get("production_errors") or 0) for _, c in cycles[:3])
        if errors >= int(self.cfg["production_errors"]):
            out.append(Problem("errores_produccion", "Errores al armar las piezas",
                               f"{errors} notas fallaron al producirse en los últimos 3 ciclos (video, imagen o texto)."))
        try:
            beat = json.loads((self.settings.data_dir / "runtime" / "heartbeat.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            beat = {}
        if str(beat.get("last_error") or "").strip():
            out.append(Problem("error_ciclo", "El último ciclo terminó con error", str(beat["last_error"])[:400]))
        return out

    def _llm(self, now: datetime) -> List[Problem]:
        since = (now - timedelta(hours=float(self.cfg["window_hours"]))).replace(microsecond=0).isoformat()
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT substr(error, 1, 160) error, COUNT(*) n FROM llm_usage WHERE created_at >= ? AND ok = 0 GROUP BY error ORDER BY n DESC",
                (since,),
            ).fetchall()
        total = sum(int(r["n"]) for r in rows)
        if total >= int(self.cfg["llm_failures"]):
            return [Problem("ia_falla", "La IA (Gemini) está fallando",
                            f"{total} llamadas fallidas en las últimas {self.cfg['window_hours']} h. Error más común: {rows[0]['error'] or 'sin detalle'}")]
        return []

    def _services(self, now: datetime) -> List[Problem]:
        out: List[Problem] = []
        limit = timedelta(hours=float(self.cfg["service_down_hours"]))
        for row in self.store.health():
            if row["ok"]:
                continue
            last_ok = _parse(row.get("last_ok_at"))
            if last_ok is None or now - last_ok > limit:
                out.append(Problem(f"servicio_caido:{row['source']}", f"Fuente de servicio caída: {row['source']}",
                                   f"Sin datos buenos desde {self._local(last_ok)}. Detalle: {row['detail']}"))
        return out

    def _disk(self, now: datetime) -> List[Problem]:
        free = float(self.free_disk_gb())
        if free < float(self.cfg["min_free_disk_gb"]):
            return [Problem("disco", "Poco espacio en disco", f"Quedan {free:.1f} GB libres en el disco de datos.")]
        return []

    # -- correo ------------------------------------------------------------------------------

    def _load_state(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    def run(self, now: datetime, send: Optional[Callable[[str, str], None]]) -> Dict[str, Any]:
        """Chequea y, si hay algo nuevo, repetido o resuelto, manda un correo con ``send(subject, html)``."""
        if not self.cfg.get("enabled", True):
            return {"enabled": False}
        utc = now.astimezone(timezone.utc).replace(microsecond=0)
        problems = self.check(utc)
        state = self._load_state()
        current = {p.key: p for p in problems}
        repeat = timedelta(hours=float(self.cfg["repeat_hours"]))
        new = [p for p in problems if p.key not in state]
        again = [p for p in problems if p.key in state and utc - (_parse(state[p.key].get("last_sent")) or utc) >= repeat]
        resolved = [dict(state[k], key=k) for k in state if k not in current]
        out: Dict[str, Any] = {"problems": [p.key for p in problems], "new": [p.key for p in new], "resolved": [r["key"] for r in resolved]}
        if not (new or again or resolved):
            return out
        if send is None:
            out["email"] = "not_sent"
            return out
        subject = self._subject(new, again, resolved)
        try:
            send(subject, self._render(utc, new, again, [p for p in problems if p not in new and p not in again], resolved))
        except Exception as exc:
            out["email"] = f"failed:{str(exc)[:200]}"
            return out
        stamp = utc.isoformat()
        for p in new + again:
            state[p.key] = {"title": p.title, "first_seen": state.get(p.key, {}).get("first_seen", stamp), "last_sent": stamp}
        for r in resolved:
            state.pop(r["key"], None)
        self._save_state(state)
        out["email"] = "sent"
        out["subject"] = subject
        return out

    @staticmethod
    def _subject(new: List[Problem], again: List[Problem], resolved: List[Dict[str, Any]]) -> str:
        open_ = new + again
        if open_:
            head = open_[0].title if len(open_) == 1 else f"{len(open_)} problemas ({open_[0].title}…)"
            return f"⚠️ Dúo Noticias: {head}"
        return "✅ Dúo Noticias: " + (resolved[0]["title"] + " — se normalizó" if len(resolved) == 1 else f"{len(resolved)} problemas se normalizaron")

    def _render(self, now: datetime, new: List[Problem], again: List[Problem], ongoing: List[Problem], resolved: List[Dict[str, Any]]) -> str:
        e = html.escape
        block = lambda title, items, color: (  # noqa: E731
            f"<h3 style='margin:18px 0 6px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:{color}'>{e(title)}</h3>"
            + "".join(f"<p style='margin:0 0 10px'><b>{e(p.title)}</b><br><span style='color:#444'>{e(p.detail)}</span></p>" for p in items)
        ) if items else ""
        done = "".join(f"<li>{e(r.get('title') or r['key'])}</li>" for r in resolved)
        return f"""<!doctype html><html><body style="margin:0;background:#f2eef7;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1b1b1b">
<div style="max-width:640px;margin:0 auto;padding:20px"><div style="background:#361957;color:#fff;padding:14px 18px">
<div style="font-size:12px;letter-spacing:.1em;color:#FFB700">DÚO NOTICIAS · AVISO DEL AUTOPUBLICADOR</div>
<div style="font-size:12px;opacity:.8;margin-top:4px">{e(self._local(now))}</div></div>
<div style="background:#fff;padding:18px">
{block('Nuevo', new, '#C62828')}{block('Sigue pasando', again, '#E65100')}{block('Ya avisado, sigue abierto', ongoing, '#777')}
{f"<h3 style='margin:18px 0 6px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:#2E7D32'>Volvió a funcionar</h3><ul style='margin:0;padding-left:20px'>{done}</ul>" if done else ''}
<p style="font-size:11px;color:#777;margin-top:22px">Lo manda el vigilante (cada hora). Un problema abierto se vuelve a avisar cada {e(str(self.cfg['repeat_hours']))} h.</p>
</div></div></body></html>"""
