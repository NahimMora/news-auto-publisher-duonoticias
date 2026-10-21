"""Reporte de operaciones cada 3 dias por correo (y aviso si el servicio se detiene).

Junta el estado real del sistema (ciclos, fallas, fuentes, publicaciones, vistas,
seguidores, costo de IA, formatos, respuestas a comentarios) y Gemini lo resume en
lenguaje claro: una llamada por reporte. El correo sale por SMTP con las variables
``DUO_REPORT_SMTP_*`` de ``.env``; sin credenciales el reporte se guarda en
``data/reports/`` y queda pendiente de envio.

El vigilante (``python -m cli.main ops-report --watchdog``, tarea programada aparte)
avisa por correo si el latido del servicio tiene mas de ``stale_hours`` y, si el
reporte esta vencido, lo manda igual aunque el servicio este caido. Ademas manda
avisos puntuales de fallas (scrapers, publicaciones, IA...; ``formats/alerts.py``).
"""
from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import ssl
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from formats.store import FormatsStore
from publishers.meta_api import MetaGraphPublisher
from storage.editorial_config import load_editorial_config
from storage.settings import PipelineSettings
from utils.llm_client import generate_json_with_usage
from utils.machine_guard import is_production_machine

LOGGER = logging.getLogger("duo.formats.report")
SYSTEM = (
    "Sos el analista de operaciones de Dúo Noticias. Escribís un reporte para el dueño del medio, que no es técnico y SOLO se entera "
    "de problemas por este correo. Español rioplatense, claro y directo, sin jerga técnica. Primero lo urgente (cosas que dejaron de "
    "funcionar o fallan seguido). Usá solo los datos recibidos; si un dato falta, decilo. No inventes causas."
)


def smtp_config() -> Dict[str, Any]:
    user = os.getenv("DUO_REPORT_SMTP_USER", "").strip()
    return {
        "host": os.getenv("DUO_REPORT_SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.getenv("DUO_REPORT_SMTP_PORT", "465") or 465),
        "user": user,
        "password": os.getenv("DUO_REPORT_SMTP_PASSWORD", "").strip(),
        "sender": os.getenv("DUO_REPORT_FROM", "").strip() or user,
        "to": os.getenv("DUO_REPORT_TO", "").strip(),
    }


def smtp_ready() -> bool:
    cfg = smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"])


class OpsReport:
    def __init__(
        self,
        settings: PipelineSettings,
        meta: Optional[MetaGraphPublisher],
        store: FormatsStore,
        cfg: Dict[str, Any],
        *,
        usage_sink: Optional[Callable[..., None]] = None,
        call: Optional[Callable[[str, str], Dict[str, Any]]] = None,
        sender: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self.settings = settings
        self.meta = meta
        self.store = store
        self.cfg = cfg
        self.usage_sink = usage_sink
        self.call = call or self._gemini
        self.sender = sender or self._send_smtp
        self.zone = ZoneInfo(settings.timezone)
        self.dir = settings.data_dir / "reports"
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def recipient(self) -> str:
        return smtp_config()["to"] or str(self.cfg.get("recipient") or "")

    # -- cuando ------------------------------------------------------------------

    def due(self, now: datetime) -> bool:
        every = timedelta(days=float(self.cfg.get("every_days", 3))) - timedelta(hours=1)
        if smtp_ready():
            last = self.store.last_report("sent")
        else:
            last = self.store.last_report("sent") or self.store.last_report("pending_credentials")
        if not last:
            return True
        return now.astimezone(timezone.utc) - datetime.fromisoformat(last["created_at"]) >= every

    # -- datos ----------------------------------------------------------------------

    def collect(self, now: datetime) -> Dict[str, Any]:
        days = float(self.cfg.get("every_days", 3))
        since_dt = now.astimezone(timezone.utc) - timedelta(days=days)
        since = since_dt.replace(microsecond=0).isoformat()
        with self.store.connection() as conn:
            q = lambda sql, *args: [dict(r) for r in conn.execute(sql, args).fetchall()]  # noqa: E731
            cycles = q("SELECT cycle_id, mode, started_at, finished_at, summary_json FROM cycles WHERE started_at >= ? ORDER BY started_at", since)
            pubs = q("SELECT platform, post_type, status, COUNT(*) n FROM publications WHERE created_at >= ? GROUP BY platform, post_type, status", since)
            failed = q("SELECT p.platform, substr(p.error_message, 1, 160) error, COUNT(*) n FROM publications p WHERE p.created_at >= ? AND p.status NOT IN ('published', 'in_flight') GROUP BY p.platform, error ORDER BY n DESC LIMIT 6", since)
            llm = q("SELECT purpose, model, COUNT(*) calls, SUM(ok = 0) failed, ROUND(SUM(estimated_cost_usd), 4) cost_usd FROM llm_usage WHERE created_at >= ? GROUP BY purpose, model", since)
            llm_err = q("SELECT substr(error, 1, 140) error, COUNT(*) n FROM llm_usage WHERE created_at >= ? AND ok = 0 GROUP BY error ORDER BY n DESC LIMIT 4", since)
            discards = q(
                """SELECT to_status, substr(reason, 1, instr(reason || ':', ':') - 1) reason, COUNT(*) n FROM queue_events
                   WHERE created_at >= ? AND to_status IN ('discarded', 'review', 'retry') GROUP BY to_status, reason ORDER BY n DESC LIMIT 10""",
                since,
            )
            top = q(
                """SELECT i.title, p.post_type, p.permalink, MAX(a.views) views, MAX(a.likes) likes, MAX(a.comments) comments, MAX(a.shares) shares
                   FROM publications p JOIN content_items i USING(content_key) LEFT JOIN analytics_snapshots a ON a.publication_id = p.id
                   WHERE p.platform = 'instagram' AND p.status = 'published' AND p.published_at >= ? GROUP BY p.id ORDER BY views DESC LIMIT 5""",
                since,
            )
            perf = q(
                """SELECT p.post_type, p.published_at, i.editorial_json, MAX(a.views) views FROM publications p JOIN content_items i USING(content_key)
                   LEFT JOIN analytics_snapshots a ON a.publication_id = p.id
                   WHERE p.platform = 'instagram' AND p.status = 'published' AND p.published_at >= ? GROUP BY p.id""",
                since,
            )
        live = [json.loads(c["summary_json"] or "{}") for c in cycles if c["mode"] == "live"]
        funnel = {k: sum(int(c.get(k) or 0) for c in live) for k in ("ingested", "discarded_policy", "duplicates", "watermark_discarded", "evaluated", "selected", "produced", "published", "production_errors")}
        # Ciclos esperados: uno por hora desde el primer ciclo del periodo (no antes de que el servicio existiera).
        first = min((datetime.fromisoformat(c["started_at"]) for c in cycles if c["mode"] == "live"), default=None)
        window_start = max(since_dt, first) if first else since_dt
        expected = max(1, int((now.astimezone(timezone.utc) - window_start).total_seconds() // 3600) + 1)
        by_type: Dict[str, List[int]] = defaultdict(list)
        by_hour: Dict[int, List[int]] = defaultdict(list)
        by_hook: Dict[str, List[int]] = defaultdict(list)
        for row in perf:
            views = int(row["views"] or 0)
            by_type[row["post_type"]].append(views)
            try:
                by_hour[datetime.fromisoformat(row["published_at"]).astimezone(self.zone).hour].append(views)
            except ValueError:
                pass
            variant = (json.loads(row["editorial_json"] or "{}").get("raw_response") or {}).get("variante_gancho")
            if variant:
                by_hook[variant].append(views)
        avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0  # noqa: E731
        snaps = {p: self.store.snapshots(p, (now - timedelta(days=days + 1)).date().isoformat()) for p in ("instagram", "facebook")}
        growth = {}
        for platform, rows in snaps.items():
            if rows:
                growth[platform] = {"actual": rows[-1]["followers"], "inicio_periodo": rows[0]["followers"], "dias_con_dato": len(rows)}
        if "instagram" not in growth and self.meta is not None and self.settings.ig_user_id:
            try:
                info = self.meta._request("GET", f"/{self.settings.ig_user_id}", params={"fields": "followers_count"}, access_token=self.settings.ig_access_token)
                growth["instagram"] = {"actual": info.get("followers_count"), "inicio_periodo": None, "dias_con_dato": 0, "nota": "todavia sin historial diario"}
            except Exception:
                pass
        formats = Counter(f"{p['kind']}:{p['platform']}:{p['status']}" for p in self.store.publications_since(since))
        replies = self.store.replies_since(since)
        heartbeat = {}
        try:
            heartbeat = json.loads((self.settings.data_dir / "runtime" / "heartbeat.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        quota = {}
        if self.meta is not None:
            try:
                quota = self.meta.get_ig_publish_limit()
            except Exception as exc:
                quota = {"error": str(exc)[:120]}
        return {
            "periodo": {"desde": since_dt.astimezone(self.zone).strftime("%d/%m %H:%M"), "hasta": now.astimezone(self.zone).strftime("%d/%m %H:%M"), "dias": days},
            "servicio": {
                "estado_actual": heartbeat.get("state"), "ultimo_latido": heartbeat.get("updated_at"), "ultimo_ciclo": heartbeat.get("cycle_id"),
                "ciclos_esperados": expected, "ciclos_corridos": len(live), "ciclos_sin_publicar": sum(1 for c in live if not c.get("published")),
                "duracion_media_s": avg([int(c.get("seconds") or 0) for c in live]),
            },
            "embudo_de_noticias": funnel,
            "publicaciones": pubs,
            "publicaciones_fallidas": failed,
            "descartes": discards,
            "seguidores": growth,
            "cupo_instagram_24h": quota,
            "rendimiento_promedio_vistas": {"por_tipo": {k: {"posts": len(v), "vistas": avg(v)} for k, v in by_type.items()},
                                             "por_hora": {h: {"posts": len(v), "vistas": avg(v)} for h, v in sorted(by_hour.items())},
                                             "por_gancho_AB": {k: {"posts": len(v), "vistas": avg(v)} for k, v in by_hook.items()}},
            "top5": top,
            "formatos": dict(formats),
            "respuestas_a_comentarios": {
                "evaluados": len(replies),
                "a_responder": sum(1 for r in replies if r["decision"] == "reply"),
                "publicadas": sum(1 for r in replies if r["reply_id"]),
                "modo": replies[-1]["mode"] if replies else "",
                "ejemplos": [{"comentario": r["comment_text"][:140], "respuesta": r["reply"][:220], "publicada": bool(r["reply_id"])} for r in replies if r["decision"] == "reply"][-6:],
            },
            "fuentes_de_servicio": self.store.health(),
            "ia": {"uso": llm, "errores": llm_err},
        }

    # -- resumen y correo ------------------------------------------------------------------

    def summarize(self, data: Dict[str, Any]) -> Dict[str, Any]:
        prompt = (
            "Con estos datos armá el reporte. Devolvé JSON: {\"asunto\":\"...\",\"estado\":\"ok|atencion|falla\",\"resumen\":\"2-3 frases\","
            "\"urgente\":[...],\"crecimiento\":[...],\"lo_que_funciono\":[...],\"recomendaciones\":[...]}. "
            "Si ciclos_corridos es bastante menor que ciclos_esperados, o una fuente de servicio esta caida, o fallan publicaciones, eso va en urgente.\n\n"
            + json.dumps(data, ensure_ascii=False, default=str)
        )
        try:
            return self.call(SYSTEM, prompt)
        except Exception as exc:
            LOGGER.warning("resumen del reporte sin IA: %s", exc)
            return {"asunto": "Reporte de Dúo Noticias", "estado": "atencion", "resumen": "No se pudo generar el resumen automático; abajo están los datos.", "urgente": [], "crecimiento": [], "lo_que_funciono": [], "recomendaciones": []}

    def render(self, data: Dict[str, Any], summary: Dict[str, Any]) -> str:
        e = lambda v: html.escape(str(v))  # noqa: E731
        lst = lambda items: "<ul style='margin:0;padding-left:20px'>" + "".join(f"<li>{e(i)}</li>" for i in items or []) + "</ul>" if items else "<p style='margin:0;color:#777'>—</p>"  # noqa: E731
        color = {"ok": "#2ED394", "atencion": "#FFB700", "falla": "#FF3D2E"}.get(str(summary.get("estado")), "#FFB700")
        pubs = data["publicaciones"]
        ig = sum(p["n"] for p in pubs if p["platform"] == "instagram" and p["status"] == "published")
        fb = sum(p["n"] for p in pubs if p["platform"] == "facebook" and p["status"] == "published")
        bad = sum(p["n"] for p in pubs if p["status"] not in ("published", "in_flight"))
        cost = sum(float(x.get("cost_usd") or 0) for x in data["ia"]["uso"])
        followers = (data["seguidores"].get("instagram") or {}).get("actual", "—")
        srv = data["servicio"]
        kpi = lambda v, label: f"<td style='background:#f4f0fa;padding:10px;width:16%'><b style='display:block;font-size:20px;color:#361957'>{e(v)}</b><span style='font-size:11px;color:#555'>{e(label)}</span></td>"  # noqa: E731
        sources = "".join(f"<li>{'✅' if s['ok'] else '⚠️'} {e(s['source'])}: {e(s['detail'])}</li>" for s in data["fuentes_de_servicio"])
        top = "".join(f"<li>{e(t['title'][:90])} · {int(t['views'] or 0):,} vistas</li>".replace(",", ".") for t in data["top5"])
        examples = "".join(f"<li><i>{e(x['comentario'])}</i><br>→ {e(x['respuesta'])} {'(publicada)' if x['publicada'] else '(modo prueba)'}</li>" for x in data["respuestas_a_comentarios"]["ejemplos"])
        section = lambda title, body: f"<h3 style='margin:18px 0 6px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#361957'>{e(title)}</h3>{body}"  # noqa: E731
        return f"""<!doctype html><html><body style="margin:0;background:#f2eef7;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1b1b1b">
<div style="max-width:680px;margin:0 auto;padding:20px">
<div style="background:#361957;color:#fff;padding:18px 20px"><div style="font-size:12px;letter-spacing:.1em;color:#FFB700">DÚO NOTICIAS · REPORTE DE OPERACIONES</div>
<div style="font-size:20px;font-weight:700;margin-top:4px">{e(summary.get('asunto') or 'Reporte de Dúo Noticias')}</div>
<div style="font-size:12px;opacity:.8;margin-top:4px">{e(data['periodo']['desde'])} → {e(data['periodo']['hasta'])}</div></div>
<div style="background:#fff;padding:20px">
<span style="display:inline-block;background:{color};color:#111;font-weight:700;font-size:12px;padding:3px 10px">{e(str(summary.get('estado', '')).upper())}</span>
<p style="font-size:15px;line-height:1.55">{e(summary.get('resumen', ''))}</p>
<table style="width:100%;border-spacing:6px"><tr>{kpi(f'{followers:,}'.replace(',', '.') if isinstance(followers, int) else followers, 'seguidores IG')}{kpi(ig, 'posts IG')}{kpi(fb, 'posts FB')}{kpi(bad, 'fallidos')}{kpi(f"{srv['ciclos_corridos']}/{srv['ciclos_esperados']}", 'ciclos')}{kpi(f'USD {cost:.2f}', 'costo IA')}</tr></table>
{section('Urgente', lst(summary.get('urgente')))}
{section('Crecimiento', lst(summary.get('crecimiento')))}
{section('Lo que funcionó', lst(summary.get('lo_que_funciono')))}
{section('Recomendaciones', lst(summary.get('recomendaciones')))}
{section('Fuentes de servicio', f"<ul style='margin:0;padding-left:20px'>{sources}</ul>" if sources else '<p>—</p>')}
{section('Top 5 del período', f"<ul style='margin:0;padding-left:20px'>{top}</ul>" if top else '<p>—</p>')}
{section('Respuestas a comentarios', f"<p style='margin:0 0 6px'>Evaluados: {data['respuestas_a_comentarios']['evaluados']} · a responder: {data['respuestas_a_comentarios']['a_responder']} · publicadas: {data['respuestas_a_comentarios']['publicadas']} · modo: {e(data['respuestas_a_comentarios']['modo'] or '—')}</p><ul style='margin:0;padding-left:20px'>{examples}</ul>")}
<p style="font-size:11px;color:#777;margin-top:22px">Generado automáticamente por el autopublicador. Datos completos en data/reports/.</p>
</div></div></body></html>"""

    def send(self, now: datetime) -> Dict[str, Any]:
        data = self.collect(now)
        summary = self.summarize(data)
        page = self.render(data, summary)
        stamp = now.astimezone(self.zone).strftime("%Y%m%d_%H%M")
        path = self.dir / f"ops_{stamp}.html"
        path.write_text(page, encoding="utf-8")
        (self.dir / f"ops_{stamp}.json").write_text(json.dumps({"data": data, "summary": summary}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        subject = f"Dúo Noticias · {summary.get('asunto') or 'Reporte de operaciones'}"
        status, error = "pending_credentials", ""
        if not is_production_machine():
            status = "blocked_machine"
        elif smtp_ready() and self.recipient:
            try:
                self.sender(self.recipient, subject, page)
                status = "sent"
            except Exception as exc:
                status, error = "failed", str(exc)[:400]
                LOGGER.warning("no se pudo enviar el reporte: %s", exc)
        self.store.save_report(period_start=data["periodo"]["desde"], status=status, recipient=self.recipient, subject=subject, html_path=str(path), error=error)
        return {"status": status, "path": str(path), "error": error}

    def watchdog(self, now: datetime) -> Dict[str, Any]:
        """Aviso si el servicio no late; ademas manda el reporte si esta vencido."""
        out: Dict[str, Any] = {}
        try:
            beat = json.loads((self.settings.data_dir / "runtime" / "heartbeat.json").read_text(encoding="utf-8"))
            last = datetime.fromisoformat(str(beat.get("updated_at")))
        except (OSError, ValueError, TypeError):
            beat, last = {}, None
        stale = last is None or now.astimezone(timezone.utc) - last > timedelta(hours=float(self.cfg.get("stale_hours", 2)))
        out["stale"] = stale
        if stale:
            previous = self.store.last_report("alert")
            recent = previous and now.astimezone(timezone.utc) - datetime.fromisoformat(previous["created_at"]) < timedelta(hours=6)
            if not recent and smtp_ready() and self.recipient and is_production_machine():
                when = last.astimezone(self.zone).strftime("%d/%m %H:%M") if last else "sin dato"
                body = (f"<p>El autopublicador de Dúo Noticias no da señales desde <b>{html.escape(when)}</b> (estado: {html.escape(str(beat.get('state')))}).</p>"
                        "<p>Revisá que la PC de producción esté encendida y con internet; la tarea programada lo reintenta cada 5 minutos.</p>")
                try:
                    self.sender(self.recipient, "⚠️ Dúo Noticias: el autopublicador está detenido", f"<html><body style='font-family:Arial'>{body}</body></html>")
                    self.store.save_report(period_start=when, status="alert", recipient=self.recipient, subject="servicio detenido", html_path="")
                    out["alert"] = "sent"
                except Exception as exc:
                    out["alert"] = f"failed:{exc}"
            if self.due(now):
                out["report"] = self.send(now)
        else:
            out["alerts"] = self.failure_alerts(now)
        return out

    def failure_alerts(self, now: datetime) -> Dict[str, Any]:
        """Fallas puntuales (con el servicio vivo; si esta caido ya sale el aviso de arriba)."""
        from extractors.registry import SourceRegistry
        from formats.alerts import FailureAlerts

        alerts = FailureAlerts(
            self.settings,
            self.store,
            self.cfg.get("alerts") or {},
            enabled_sources=SourceRegistry(self.settings).enabled_source_names(),
            quota=self.meta.get_ig_publish_limit if self.meta is not None else None,
        )
        can_send = smtp_ready() and bool(self.recipient) and is_production_machine()
        send = (lambda subject, page: self.sender(self.recipient, subject, page)) if can_send else None
        result = alerts.run(now, send)
        if result.get("email") == "sent":
            self.store.save_report(period_start=now.astimezone(self.zone).strftime("%d/%m %H:%M"), status="failure_alert", recipient=self.recipient,
                                   subject=str(result.get("subject") or "aviso"), html_path="")
        return result

    # -- envio e IA ------------------------------------------------------------------------

    def _send_smtp(self, to: str, subject: str, page: str) -> None:
        cfg = smtp_config()
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = cfg["sender"]
        message["To"] = to
        message.set_content("Este reporte se ve en formato HTML.")
        message.add_alternative(page, subtype="html")
        context = ssl.create_default_context()
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=60) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=60) as smtp:
                smtp.starttls(context=context)
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(message)

    def _gemini(self, system: str, prompt: str) -> Dict[str, Any]:
        started = time.monotonic()
        ok, error, usage = False, "", None
        try:
            data, usage = generate_json_with_usage(system, prompt, temperature=0.4, max_output_tokens=1800, config=self.settings.llm)
            ok = True
            return data
        except Exception as exc:
            error = str(exc)[:300]
            raise
        finally:
            if self.usage_sink:
                cost = load_editorial_config(self.settings).estimated_cost_usd(usage.input_tokens or 0, usage.output_tokens or 0, usage.model) if usage else None
                self.usage_sink(purpose="ops_report", model=(usage.model if usage else self.settings.llm.model), items=1,
                                input_tokens=usage.input_tokens if usage else None, output_tokens=usage.output_tokens if usage else None,
                                latency_ms=int((time.monotonic() - started) * 1000), ok=ok, error=error, estimated_cost_usd=cost)
