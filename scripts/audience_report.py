"""Medicion de audiencia de Instagram dia por dia (estrategia 2026-10-21, docs/ESTRATEGIA_AUDIENCIA.md).

Junta, por dia local:
- de la API de Instagram (solo lectura): altas y bajas de seguidores, alcance, interacciones,
  cuentas que interactuaron y visitas al perfil;
- de la base del pipeline: publicaciones en el feed y en historias, y vistas/likes/compartidos
  promedio por tipo de publicacion en el control T3 (~25 h).

Uso: python scripts/audience_report.py [--days 21]
Escribe data/reports/audience_<fecha>.json y muestra una tabla.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publishers.meta_api import MetaGraphPublisher  # noqa: E402
from storage.settings import get_settings  # noqa: E402
from storage.sqlite_store import PipelineStore  # noqa: E402

ZONE = ZoneInfo("America/Buenos_Aires")
ACCOUNT_METRICS = ("reach", "total_interactions", "accounts_engaged", "profile_views")


def account_day(publisher: MetaGraphPublisher, day: datetime) -> dict:
    settings = publisher.settings
    since, until = int(day.timestamp()), int((day + timedelta(days=1)).timestamp())
    out: dict = {}

    def total(metric: str, **extra):
        payload = publisher._request(
            "GET",
            f"/{settings.ig_user_id}/insights",
            params={"metric": metric, "period": "day", "metric_type": "total_value", "since": since, "until": until, **extra},
            access_token=settings.ig_access_token,
        )
        return ((payload.get("data") or [{}])[0].get("total_value") or {})

    try:
        breakdowns = (total("follows_and_unfollows", breakdown="follow_type").get("breakdowns") or [{}])[0].get("results") or []
        by_type = {item["dimension_values"][0]: item["value"] for item in breakdowns}
        # follow_type: FOLLOWER = altas del dia, NON_FOLLOWER = bajas del dia.
        out["altas"] = by_type.get("FOLLOWER", 0)
        out["bajas"] = by_type.get("NON_FOLLOWER", 0)
        out["neto"] = out["altas"] - out["bajas"]
    except Exception as exc:  # el dia en curso todavia no tiene desglose
        out["seguidores_error"] = str(exc)[:120]
    for metric in ACCOUNT_METRICS:
        try:
            out[metric] = total(metric).get("value")
        except Exception as exc:
            out[metric] = None
            out[f"{metric}_error"] = str(exc)[:120]
    return out


def pipeline_day(store: PipelineStore, day: datetime) -> dict:
    start = day.astimezone(timezone.utc).isoformat()
    end = (day + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    with store.connection() as conn:
        feed = conn.execute(
            "SELECT COUNT(*) FROM publications WHERE platform = 'instagram' AND status = 'published' AND published_at >= ? AND published_at < ?",
            (start, end),
        ).fetchone()[0]
        facebook = conn.execute(
            "SELECT COUNT(*) FROM publications WHERE platform = 'facebook' AND status = 'published' AND published_at >= ? AND published_at < ?",
            (start, end),
        ).fetchone()[0]
        formats = conn.execute(
            "SELECT COUNT(*) FROM format_publications WHERE platform = 'instagram' AND created_at >= ? AND created_at < ?",
            (start, end),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT p.platform, p.post_type, COUNT(*) n, AVG(a.views) views, AVG(a.likes) likes, AVG(a.shares) shares
               FROM publications p JOIN analytics_snapshots a ON a.publication_id = p.id AND a.checkpoint_label = 'T3'
               WHERE p.status = 'published' AND p.published_at >= ? AND p.published_at < ?
               GROUP BY 1, 2""",
            (start, end),
        ).fetchall()
    per_type = {
        f"{r['platform']}:{r['post_type']}": {"n": r["n"], "vistas": round(r["views"] or 0), "likes": round(r["likes"] or 0, 1), "compartidos": round(r["shares"] or 0, 1)}
        for r in rows
    }
    return {"feed_ig": feed, "solo_o_tambien_fb": facebook, "formatos_ig": formats, "a_25h": per_type}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=21)
    args = parser.parse_args()
    settings = get_settings()
    publisher = MetaGraphPublisher(settings)
    store = PipelineStore(settings)
    today = datetime.now(ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    for offset in range(args.days, -1, -1):
        day = today - timedelta(days=offset)
        days.append({"dia": day.date().isoformat(), **account_day(publisher, day), **pipeline_day(store, day)})
    path = settings.data_dir / "reports" / f"audience_{today.date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(days, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'dia':<11}{'altas':>6}{'bajas':>6}{'neto':>6}{'alcance':>9}{'interac':>8}{'feed':>5}{'hist':>5}  imagen@25h  reel@25h")
    for d in days:
        img = d["a_25h"].get("instagram:image", {}).get("vistas", "-")
        reel = d["a_25h"].get("instagram:reel", {}).get("vistas", "-")
        print(f"{d['dia']:<11}{d.get('altas', '-'):>6}{d.get('bajas', '-'):>6}{d.get('neto', '-'):>6}{d.get('reach') or '-':>9}"
              f"{d.get('total_interactions') or '-':>8}{d['feed_ig']:>5}{d['formatos_ig']:>5}  {img:>10}  {reel:>8}")
    print(f"\nGuardado en {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
