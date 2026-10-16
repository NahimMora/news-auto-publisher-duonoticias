"""
Simulacion completa del pipeline AutoPublicador Duo.

Corre todas las etapas (scraping -> scoring -> editorial -> formato -> schedule)
sobre una base de datos TEMPORAL aislada. El DB real y el estado live
quedan INTACTOS. No se llama a Meta Graph API en ningun momento.

Al terminar genera data/simulacion_pipeline.html con el reporte antes/despues.

Uso:
    python simular_pipeline_html.py
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from jobs.pipeline import DuoPipeline
from storage.settings import get_settings

REPORTE_PATH = Path("data/simulacion_pipeline.html")
TOP_N = 10


def _j(text) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text) if isinstance(text, str) else (text or {})
    except Exception:
        return {}


SOURCE_ICONS = {
    "tn": "📺", "infobae": "📰", "paparazzi": "⭐",
    "ambitofinanciero": "💹", "eltribuno": "🗞️",
    "nuevodiariodesalta": "📍", "elonce": "📡",
    "minutouno": "⚡", "noticiasargentinas": "🇦🇷",
    "x": "𝕏", "fiscalespenalesalta": "⚖️", "justiciasalta": "🏛️",
}

SCORE_LABELS = [
    ("novelty",              "Novedad",          "Qué tan nueva es la noticia"),
    ("engagement_potential", "Engagement",        "Potencial de interacciones"),
    ("debate_potential",     "Debate",            "Capacidad de generar discusión"),
    ("repostability",        "Repostabilidad",    "Probabilidad de ser compartida"),
    ("emotional_impact",     "Impacto emocional", "Resonancia emocional"),
    ("clarity",              "Claridad",          "Comprensibilidad del contenido"),
    ("topic_fit",            "Fit temático",      "Alineación con el público"),
]


def score_bar(value: float, max_val: float = 100.0) -> str:
    pct = min(1.0, max(0.0, float(value or 0) / max(0.001, float(max_val))))
    color = "#22c55e" if pct >= 0.7 else "#f59e0b" if pct >= 0.4 else "#ef4444"
    return (
        f'<div class="bar-bg">'
        f'<div class="bar-fill" style="width:{pct*100:.1f}%;background:{color}"></div>'
        f'<span class="bar-label">{value:.0f}</span>'
        f'</div>'
    )


def run_isolated_pipeline(tmp_db: Path) -> DuoPipeline:
    real_settings = get_settings()
    sim_settings = dataclasses.replace(
        real_settings,
        sqlite_path=tmp_db,
        live_publish_enabled=False,
    )
    pipeline = DuoPipeline(sim_settings)

    print("[1/5] Scrapeando todas las fuentes activas...")
    ingested = pipeline.run_scraper(max_news=None)
    print(f"      => {ingested} items ingestados")

    print("[2/5] Puntuando por viralidad...")
    scored = pipeline.run_scoring()
    print(f"      => {scored} items puntuados")

    print("[3/5] Generando captions editoriales (OpenAI)...")
    edited = pipeline.run_editorial()
    print(f"      => {edited} items editorizados")

    print("[4/5] Formateando assets...")
    formatted = pipeline.run_formatter()
    print(f"      => {formatted} items formateados")

    print("[5/5] Asignando slots de publicacion...")
    scheduled = pipeline.run_scheduler()
    print(f"      => {scheduled} items programados")

    return pipeline


def fetch_top(pipeline: DuoPipeline) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(pipeline.settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            source, canonical_url, title, summary, body_text,
            score_total, score_json, score_reason, score_theme,
            dedupe_status,
            editorial_json, final_caption, final_overlay,
            assigned_slot, assigned_time, assigned_post_type,
            pipeline_status, updated_at
        FROM content_items
        WHERE score_total IS NOT NULL AND score_total > 0
        ORDER BY score_total DESC
        LIMIT ?
        """,
        (TOP_N,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_card(rank: int, item: dict) -> str:
    source = item.get("source") or "?"
    icon = SOURCE_ICONS.get(source, "📄")
    title = (item.get("title") or "Sin título").strip()
    summary = (item.get("summary") or "").strip()
    body = (item.get("body_text") or "").strip()
    url = item.get("canonical_url") or "#"
    score_total = float(item.get("score_total") or 0)
    score_data = _j(item.get("score_json"))
    score_reason = item.get("score_reason") or "Sin detalle"
    theme = item.get("score_theme") or "—"
    slot = item.get("assigned_slot") or item.get("assigned_time") or "sin asignar"
    post_type = item.get("assigned_post_type") or "—"
    status = item.get("pipeline_status") or "—"
    dedupe = item.get("dedupe_status") or "unique"

    editorial = _j(item.get("editorial_json"))
    raw_resp = editorial.get("raw_response") or {}
    caption_raw = raw_resp.get("texto_instagram") or editorial.get("caption") or item.get("final_caption") or ""
    overlay = raw_resp.get("overlay") or editorial.get("overlay") or item.get("final_overlay") or ""
    titulo_ig = raw_resp.get("titulo_instagram") or editorial.get("hook") or ""
    decision = raw_resp.get("decision") or ("publish" if editorial.get("publish") else "manual_review")
    decision_reason = raw_resp.get("decision_reason") or editorial.get("reason") or ""
    cta = raw_resp.get("cta") or editorial.get("cta") or ""
    hashtags = raw_resp.get("hashtags") or []
    tone = raw_resp.get("tone") or editorial.get("tone") or ""
    risk_level = raw_resp.get("risk_level") or "low"

    dec_color = {"publish": "#22c55e", "skip": "#ef4444", "manual_review": "#f59e0b"}.get(decision, "#6b7280")
    dec_label = {"publish": "✅ Publicar", "skip": "❌ Descartar", "manual_review": "⚠️ Revisión manual"}.get(decision, decision)

    body_paras = [p.strip() for p in body.splitlines() if len(p.strip()) > 20][:4]
    body_html = "".join(f'<p class="body-p">{p}</p>' for p in body_paras) or '<p class="body-p muted">Sin cuerpo extraído</p>'

    cap_html = ""
    if caption_raw:
        for line in caption_raw.split("\n"):
            s = line.strip()
            cap_html += ("<br>" if not s else f'<span class="cap-line">{s}</span><br>')

    score_rows = ""
    for key, label, tooltip in SCORE_LABELS:
        val = float(score_data.get(key) or 0)
        score_rows += f'<tr title="{tooltip}"><td class="sl">{label}</td><td>{score_bar(val)}</td></tr>'

    sub_scores = score_data.get("source_scores") or {}
    sub_rows = ""
    for k, v in sub_scores.items():
        lbl = k.replace("_score", "").replace("_", " ").title()
        sub_rows += f'<tr><td class="sl">{lbl}</td><td>{score_bar(float(v or 0))}</td></tr>'

    htags_html = " ".join(f'<span class="htag">{h}</span>' for h in hashtags) or '<span class="muted">sin hashtags</span>'
    char_count = len(caption_raw)

    return f"""
<article class="card" id="n{rank}">
  <div class="card-header">
    <div class="rank-badge">#{rank}</div>
    <div class="card-meta">
      <span class="chip source-chip">{icon} {source}</span>
      <span class="chip score-chip">{score_total:.1f} / 100</span>
      <span class="chip theme-chip">🏷️ {theme}</span>
      <span class="chip type-chip">📐 {post_type}</span>
      <span class="chip tone-chip">🎭 {tone or '—'}</span>
      <span class="chip status-chip">⚙️ {status}</span>
      <span class="decision-badge" style="background:{dec_color}">{dec_label}</span>
    </div>
    <a class="src-link" href="{url}" target="_blank" rel="noopener">🔗 Fuente</a>
  </div>

  <div class="two-col">
    <section class="panel before-panel">
      <h3 class="panel-title">📥 ANTES — Contenido crudo</h3>
      <div class="field-block">
        <label>Título original</label>
        <p class="field-value title-raw">{title}</p>
      </div>
      <div class="field-block">
        <label>Bajada / extracto</label>
        <p class="field-value">{summary or '<span class="muted">No disponible</span>'}</p>
      </div>
      <div class="field-block">
        <label>Cuerpo (primeros párrafos)</label>
        <div class="body-preview">{body_html}</div>
      </div>
      <div class="field-block">
        <label>Deduplicación</label>
        <span class="dedup-tag dedup-{dedupe}">{dedupe}</span>
      </div>
    </section>

    <section class="panel after-panel">
      <h3 class="panel-title">📤 DESPUÉS — Caption editorial</h3>
      <div class="field-block">
        <label>Título Instagram</label>
        <p class="field-value title-ig">{titulo_ig or '<span class="muted">No generado</span>'}</p>
      </div>
      <div class="field-block">
        <label>Overlay (texto sobre imagen)</label>
        <p class="field-value overlay-val">{overlay or '<span class="muted">—</span>'}</p>
      </div>
      <div class="field-block">
        <label>Caption completo <span class="char-badge">{char_count} chars</span></label>
        <div class="caption-box">{cap_html or '<span class="muted">No generado</span>'}</div>
      </div>
      <div class="field-block">
        <label>CTA</label>
        <p class="field-value cta-val">{cta or '<span class="muted">—</span>'}</p>
      </div>
      <div class="field-block">
        <label>Hashtags</label>
        <div class="htags-row">{htags_html}</div>
      </div>
      <div class="field-block">
        <label>Slot asignado (simulado)</label>
        <p class="field-value slot-val">🕐 {slot}</p>
      </div>
    </section>
  </div>

  <section class="criteria-section">
    <h3 class="panel-title">⚖️ CRITERIO DE ELECCIÓN</h3>
    <div class="criteria-grid">
      <div>
        <table class="score-table">
          <thead><tr><th>Dimensión</th><th>Puntuación (0-100)</th></tr></thead>
          <tbody>{score_rows}</tbody>
        </table>
        <div class="total-row">
          <strong>Score total</strong>
          <span class="total-val">{score_total:.1f}</span>
          {score_bar(score_total)}
        </div>
        {f'<details class="sub-det"><summary>📊 Sub-scores internos</summary><table class="score-table" style="margin-top:6px"><tbody>{sub_rows}</tbody></table></details>' if sub_rows else ''}
      </div>
      <div>
        <div class="reason-box">
          <label>🤖 Razón del scoring</label>
          <p>{score_reason}</p>
        </div>
        <div class="reason-box">
          <label>✏️ Decisión editorial</label>
          <p><strong style="color:{dec_color}">{dec_label}</strong><br>{decision_reason or 'Sin detalle'}</p>
        </div>
        {'<div class="reason-box risk-box"><label>⚠️ Nivel de riesgo</label><p>' + risk_level + '</p></div>' if risk_level != 'low' else ''}
      </div>
    </div>
  </section>
</article>"""


def build_html(items: list[dict], run_stats: dict) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cards = "\n".join(build_card(i + 1, item) for i, item in enumerate(items))

    sources_found = sorted(set(i.get("source", "?") for i in items))
    publish_count = sum(1 for i in items if (_j(i.get("editorial_json")).get("raw_response") or {}).get("decision") == "publish" or _j(i.get("editorial_json")).get("publish"))
    avg_score = sum(float(i.get("score_total") or 0) for i in items) / max(1, len(items))
    avg_chars = sum(len((_j(i.get("editorial_json")).get("raw_response") or {}).get("texto_instagram") or i.get("final_caption") or "") for i in items) // max(1, len(items))

    index_links = "".join(
        f'<a href="#n{r+1}">'
        f'#{r+1} {SOURCE_ICONS.get(item.get("source",""), "📄")} '
        f'{(item.get("title") or "?")[:28]}…'
        f'</a>'
        for r, item in enumerate(items)
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Simulacion Pipeline — AutoPublicador Duo</title>
  <style>
    :root{{
      --bg:#0f172a;--surface:#1e293b;--surface2:#273349;--border:#334155;
      --accent:#3b82f6;--text:#e2e8f0;--text2:#94a3b8;--text3:#64748b;
      --before:#0f2940;--before-bdr:#1d4ed8;
      --after:#0f2a1a;--after-bdr:#16a34a;
      --criteria:#1a1a2e;--criteria-bdr:#7c3aed;
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding-bottom:60px}}

    /* HEADER */
    .page-header{{background:linear-gradient(135deg,#1e3a5f 0%,#1e1b4b 100%);border-bottom:1px solid var(--border);padding:28px 40px;position:sticky;top:0;z-index:100}}
    .page-header h1{{font-size:1.5rem;font-weight:800;letter-spacing:-.5px}}
    .page-header h1 span{{color:#60a5fa}}
    .sim-badge{{display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #f59e0b;border-radius:20px;padding:3px 14px;font-size:.78rem;font-weight:700;margin-top:8px}}
    .meta-row{{margin-top:8px;color:var(--text2);font-size:.82rem;display:flex;gap:16px;flex-wrap:wrap}}
    .meta-pill{{background:rgba(255,255,255,.08);border-radius:20px;padding:2px 12px;border:1px solid var(--border)}}

    /* STATS BAR */
    .stats-bar{{display:flex;gap:10px;padding:16px 40px;background:var(--surface);border-bottom:1px solid var(--border);flex-wrap:wrap}}
    .stat{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:10px 18px;text-align:center;min-width:120px}}
    .stat .sv{{font-size:1.4rem;font-weight:700;color:#60a5fa}}
    .stat .sl{{font-size:.7rem;color:var(--text2);text-transform:uppercase;letter-spacing:.05em;margin-top:2px}}

    /* PIPELINE FLOW */
    .flow-bar{{padding:12px 40px;background:var(--surface2);border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:.82rem}}
    .flow-step{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:4px 14px;color:var(--text2)}}
    .flow-step.ok{{border-color:#22c55e;color:#86efac}}
    .flow-arrow{{color:var(--text3)}}

    /* INDEX */
    .index-nav{{padding:14px 40px;background:var(--surface);border-bottom:1px solid var(--border);display:flex;gap:6px;flex-wrap:wrap}}
    .index-nav a{{padding:3px 10px;border-radius:20px;background:var(--surface2);border:1px solid var(--border);color:var(--text2);text-decoration:none;font-size:.75rem;white-space:nowrap}}
    .index-nav a:hover{{background:var(--accent);color:#fff;border-color:var(--accent)}}

    /* CARDS */
    .cards{{padding:24px 40px;display:flex;flex-direction:column;gap:28px}}
    .card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden}}
    .card-header{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 18px;background:var(--surface2);border-bottom:1px solid var(--border)}}
    .rank-badge{{background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;font-weight:800;font-size:1rem;width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .card-meta{{display:flex;gap:6px;flex-wrap:wrap;flex:1;align-items:center}}
    .chip{{padding:2px 9px;border-radius:20px;font-size:.73rem;font-weight:600;border:1px solid var(--border)}}
    .source-chip{{background:#1e3a5f;color:#93c5fd}}
    .score-chip{{background:#1e2a1e;color:#86efac}}
    .theme-chip{{background:#2a1e3a;color:#c4b5fd}}
    .type-chip{{background:#2a1e1e;color:#fca5a5}}
    .tone-chip{{background:#1e2a2a;color:#67e8f9}}
    .status-chip{{background:#272727;color:#94a3b8}}
    .decision-badge{{padding:3px 12px;border-radius:20px;font-size:.75rem;font-weight:700;color:#fff;margin-left:auto}}
    .src-link{{color:var(--text2);font-size:.75rem;text-decoration:none;padding:3px 8px;border-radius:6px;border:1px solid var(--border);white-space:nowrap}}
    .src-link:hover{{color:var(--accent);border-color:var(--accent)}}

    /* TWO-COL */
    .two-col{{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--border)}}
    @media(max-width:900px){{.two-col{{grid-template-columns:1fr}}}}
    .panel{{padding:18px 22px}}
    .before-panel{{background:var(--before);border-right:1px solid var(--before-bdr)}}
    .after-panel{{background:var(--after)}}
    .panel-title{{font-size:.75rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:14px;padding-bottom:7px;border-bottom:1px solid var(--border)}}

    /* FIELDS */
    .field-block{{margin-bottom:14px}}
    .field-block label{{display:block;font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:4px}}
    .field-value{{color:var(--text);line-height:1.5;font-size:.87rem}}
    .title-raw{{font-size:.92rem;font-weight:600;color:#e0f2fe}}
    .title-ig{{font-size:.92rem;font-weight:700;color:#bbf7d0}}
    .overlay-val{{font-size:.87rem;font-weight:600;color:#fef3c7;background:rgba(255,200,0,.08);padding:6px 10px;border-radius:6px;border-left:3px solid #f59e0b}}
    .cta-val{{font-size:.85rem;color:#a5f3fc;background:rgba(6,182,212,.08);padding:6px 10px;border-radius:6px;border-left:3px solid #06b6d4}}
    .slot-val{{color:#c4b5fd;font-size:.85rem}}
    .muted{{color:var(--text3);font-style:italic;font-size:.82rem}}
    .char-badge{{background:rgba(255,255,255,.07);border:1px solid var(--border);border-radius:10px;padding:1px 8px;font-size:.68rem;font-weight:400;color:var(--text3);margin-left:6px}}

    .body-preview{{background:rgba(0,0,0,.2);border-radius:8px;padding:10px 13px;max-height:130px;overflow-y:auto}}
    .body-p{{font-size:.82rem;color:var(--text2);line-height:1.6;margin-bottom:5px}}

    .caption-box{{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:12px 14px;font-size:.85rem;line-height:1.7;max-height:240px;overflow-y:auto;color:#e6edf3}}
    .cap-line{{display:inline}}

    .dedup-tag{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:.75rem;font-weight:600}}
    .dedup-unique{{background:#14532d;color:#86efac}}
    .dedup-duplicate{{background:#7f1d1d;color:#fca5a5}}
    .dedup-similar{{background:#451a03;color:#fed7aa}}

    .htags-row{{display:flex;gap:5px;flex-wrap:wrap}}
    .htag{{background:#1e3a5f;color:#93c5fd;padding:2px 10px;border-radius:12px;font-size:.75rem}}

    /* CRITERIA */
    .criteria-section{{padding:18px 22px;background:var(--criteria);border-top:2px solid var(--criteria-bdr)}}
    .criteria-grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:10px}}
    @media(max-width:900px){{.criteria-grid{{grid-template-columns:1fr}}}}
    .score-table{{width:100%;border-collapse:collapse;font-size:.8rem}}
    .score-table th{{text-align:left;color:var(--text2);font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;padding:4px 7px;border-bottom:1px solid var(--border)}}
    .score-table td{{padding:4px 7px;vertical-align:middle}}
    .score-table .sl{{color:var(--text2);white-space:nowrap}}
    .score-table tr:hover td{{background:rgba(255,255,255,.03)}}
    .bar-bg{{background:var(--surface);border-radius:4px;height:15px;position:relative;display:flex;align-items:center}}
    .bar-fill{{height:100%;border-radius:4px}}
    .bar-label{{position:absolute;right:0;font-size:.67rem;color:var(--text2);background:var(--surface);padding:0 3px;border-radius:3px}}
    .total-row{{margin-top:8px;display:flex;align-items:center;gap:8px;font-size:.85rem}}
    .total-val{{font-size:1.15rem;font-weight:800;color:#60a5fa;min-width:45px}}
    .total-row .bar-bg{{flex:1}}
    .reason-box{{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:10px}}
    .reason-box label{{display:block;font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:5px}}
    .reason-box p{{font-size:.85rem;color:var(--text);line-height:1.5}}
    .risk-box{{border-color:#f59e0b}}
    details.sub-det summary{{cursor:pointer;font-size:.77rem;color:var(--text2);padding:4px 0;user-select:none}}

    footer{{text-align:center;color:var(--text3);font-size:.75rem;padding:20px;margin-top:30px}}
  </style>
</head>
<body>

<header class="page-header">
  <h1>🧪 Simulacion Pipeline — <span>AutoPublicador Duo</span></h1>
  <span class="sim-badge">⚠️ MODO SIMULACION — DB temporal aislada — cero impacto en live</span>
  <div class="meta-row">
    <span class="meta-pill">📅 {now}</span>
    <span class="meta-pill">🏆 Top {len(items)} noticias</span>
    <span class="meta-pill">🤖 GPT-4.1-mini editorial</span>
    <span class="meta-pill">🚫 Meta Graph API: NO llamada</span>
    <span class="meta-pill">🗄️ DB real: INTACTA</span>
  </div>
</header>

<div class="stats-bar">
  <div class="stat"><div class="sv">{run_stats.get("ingested",0)}</div><div class="sl">Scrapeados</div></div>
  <div class="stat"><div class="sv">{run_stats.get("scored",0)}</div><div class="sl">Puntuados</div></div>
  <div class="stat"><div class="sv">{run_stats.get("edited",0)}</div><div class="sl">Editorizados</div></div>
  <div class="stat"><div class="sv">{run_stats.get("formatted",0)}</div><div class="sl">Formateados</div></div>
  <div class="stat"><div class="sv">{run_stats.get("scheduled",0)}</div><div class="sl">Programados</div></div>
  <div class="stat"><div class="sv">{len(items)}</div><div class="sl">En reporte</div></div>
  <div class="stat"><div class="sv">{publish_count}</div><div class="sl">Aprobados</div></div>
  <div class="stat"><div class="sv">{len(sources_found)}</div><div class="sl">Fuentes</div></div>
  <div class="stat"><div class="sv">{avg_score:.1f}</div><div class="sl">Score prom.</div></div>
  <div class="stat"><div class="sv">{avg_chars}</div><div class="sl">Chars prom.</div></div>
</div>

<div class="flow-bar">
  <div class="flow-step ok">✅ Scraping</div>
  <span class="flow-arrow">→</span>
  <div class="flow-step ok">✅ Scoring</div>
  <span class="flow-arrow">→</span>
  <div class="flow-step ok">✅ Editorial AI</div>
  <span class="flow-arrow">→</span>
  <div class="flow-step ok">✅ Formato</div>
  <span class="flow-arrow">→</span>
  <div class="flow-step ok">✅ Scheduler</div>
  <span class="flow-arrow">→</span>
  <div class="flow-step" style="border-color:#ef4444;color:#fca5a5">🚫 Publicación (bloqueada)</div>
</div>

<nav class="index-nav">
  {index_links}
</nav>

<main class="cards">
{cards}
</main>

<footer>
  AutoPublicador Duo · Simulacion {now} · DB real intacta · D:\\WebApp_HolaSalta solo referencia (sin modificar)
</footer>
</body>
</html>"""


def main() -> None:
    print("=" * 58)
    print("  AutoPublicador Duo — SIMULACION COMPLETA (DB temporal)")
    print("=" * 58)
    print("  El DB real queda intacto. No se publica nada.\n")

    tmp_dir = tempfile.mkdtemp(prefix="duo_sim_")
    tmp_db = Path(tmp_dir) / "sim_pipeline.sqlite3"

    try:
        pipeline = run_isolated_pipeline(tmp_db)

        items = fetch_top(pipeline)
        if not items:
            print("\nNo se encontraron items con score. Revisá las fuentes y el scoring.")
            return

        run_stats = {
            "ingested": pipeline.run_scraper.__doc__ and 0 or 0,
        }
        conn_check = __import__("sqlite3").connect(tmp_db)
        conn_check.row_factory = __import__("sqlite3").Row
        counts = dict(conn_check.execute(
            "SELECT pipeline_status, COUNT(*) FROM content_items GROUP BY pipeline_status"
        ).fetchall())
        conn_check.close()

        run_stats = {
            "ingested":  sum(v for k, v in counts.items()),
            "scored":    counts.get("scored", 0) + counts.get("editorialized", 0) + counts.get("formatted", 0) + counts.get("scheduled", 0),
            "edited":    counts.get("editorialized", 0) + counts.get("formatted", 0) + counts.get("scheduled", 0),
            "formatted": counts.get("formatted", 0) + counts.get("scheduled", 0),
            "scheduled": counts.get("scheduled", 0),
        }

        REPORTE_PATH.parent.mkdir(parents=True, exist_ok=True)
        html = build_html(items, run_stats)
        REPORTE_PATH.write_text(html, encoding="utf-8")

        print(f"\n{'='*58}")
        print(f"  SIMULACION COMPLETADA")
        print(f"  Reporte: {REPORTE_PATH.resolve()}")
        print(f"  Items analizados: {len(items)}")
        print(f"  Estado DB real: INTACTO")
        print(f"{'='*58}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print("\n  DB temporal eliminada.")

    import subprocess
    subprocess.Popen(["cmd", "/c", "start", str(REPORTE_PATH.resolve())])


if __name__ == "__main__":
    main()
