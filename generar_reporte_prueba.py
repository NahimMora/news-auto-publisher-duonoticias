"""
Prueba controlada del pipeline AutoPublicador Duo.

Genera un reporte HTML con:
- Antes: contenido crudo del scraper
- Criterio: por qué se eligió (score de viralidad)
- Después: caption editorial listo para Instagram/Facebook

Uso: python generar_reporte_prueba.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Bootstrap pipeline ---
from jobs.pipeline import DuoPipeline
from storage.settings import get_settings

REPORTE_PATH = Path("data/reporte_prueba_10_noticias.html")
TOP_N = 10


def run_pipeline_stages() -> None:
    settings = get_settings()
    p = DuoPipeline(settings)

    print(f"[1/4] Scrapeando todas las fuentes...")
    ingested = p.run_scraper(max_news=None)
    print(f"      => {ingested} items ingestados")

    print(f"[2/4] Puntuando por viralidad...")
    scored = p.run_scoring()
    print(f"      => {scored} items puntuados")

    print(f"[3/4] Generando captions editoriales (OpenAI)...")
    edited = p.run_editorial()
    print(f"      => {edited} items editorizados")

    print(f"[4/4] Leyendo top {TOP_N} de la base de datos...")


def fetch_top10(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            source, canonical_url, title, summary, body_text,
            score_total, score_json, score_reason, score_theme,
            dedupe_status, dedupe_reason,
            editorial_json, final_caption, final_overlay,
            assigned_slot, assigned_time, pipeline_status,
            updated_at
        FROM content_items
        WHERE score_total IS NOT NULL
          AND score_total > 0
        ORDER BY score_total DESC
        LIMIT ?
        """,
        (TOP_N,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _j(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _score_bar(value: float, max_val: float = 100.0) -> str:
    pct = min(1.0, max(0.0, float(value or 0) / max(0.001, float(max_val))))
    color = "#22c55e" if pct >= 0.7 else "#f59e0b" if pct >= 0.4 else "#ef4444"
    return f'<div class="bar-bg"><div class="bar-fill" style="width:{pct*100:.1f}%;background:{color}"></div><span class="bar-label">{value:.0f}</span></div>'


SOURCE_ICONS = {
    "tn": "📺", "infobae": "📰", "paparazzi": "⭐",
    "ambitofinanciero": "💹", "eltribuno": "🗞️",
    "nuevodiariodesalta": "📍", "elonce": "📡",
    "minutouno": "⚡", "noticiasargentinas": "🇦🇷",
    "x": "𝕏", "ariesonline": "📻", "eloncesalta": "📍",
}

SCORE_LABELS = {
    "novelty": ("Novedad", "Qué tan nueva y reciente es la noticia"),
    "engagement_potential": ("Engagement", "Potencial de likes/comentarios/shares"),
    "debate_potential": ("Debate", "Capacidad de generar discusión"),
    "repostability": ("Repostabilidad", "Probabilidad de que otros lo compartan"),
    "emotional_impact": ("Impacto emocional", "Resonancia emocional del contenido"),
    "clarity": ("Claridad", "Qué tan claro y comprensible es el contenido"),
    "topic_fit": ("Fit temático", "Alineación con temas de interés del público"),
}


def build_html(items: list[dict]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cards_html = ""

    for rank, item in enumerate(items, start=1):
        source = item.get("source") or "?"
        icon = SOURCE_ICONS.get(source, "📄")
        title = (item.get("title") or "Sin título").strip()
        summary = (item.get("summary") or "").strip()
        body = (item.get("body_text") or "").strip()
        body_paras = [p.strip() for p in body.splitlines() if len(p.strip()) > 20][:4]
        url = item.get("canonical_url") or "#"
        score_total = float(item.get("score_total") or 0)
        score_data = _j(item.get("score_json"))
        score_reason = item.get("score_reason") or "Sin detalle"
        theme = item.get("score_theme") or "general"
        editorial = _j(item.get("editorial_json"))
        raw_resp = editorial.get("raw_response") or {}
        # Use texto_instagram from raw_response (direct OpenAI output) or fallback to caption field
        caption_raw = (
            raw_resp.get("texto_instagram")
            or editorial.get("caption")
            or item.get("final_caption")
            or ""
        )
        overlay = raw_resp.get("overlay") or editorial.get("overlay") or item.get("final_overlay") or ""
        titulo_ig = raw_resp.get("titulo_instagram") or editorial.get("hook") or ""
        decision = raw_resp.get("decision") or ("publish" if editorial.get("publish") else "manual_review")
        decision_reason = raw_resp.get("decision_reason") or editorial.get("reason") or ""
        format_type = raw_resp.get("format") or editorial.get("style") or "image"
        cta = raw_resp.get("cta") or editorial.get("cta") or ""
        hashtags = raw_resp.get("hashtags") or []
        risk_level = raw_resp.get("risk_level") or "low"
        safety_notes = raw_resp.get("safety_notes") or ""
        tone = raw_resp.get("tone") or editorial.get("tone") or ""
        # Visible metrics (for X content mostly)
        visible_metrics = _j(editorial.get("input_payload", {}).get("visible_metrics_json") if isinstance(editorial.get("input_payload"), dict) else None)
        if not visible_metrics:
            # Try from ranking_signals_json in DB row
            rs = item.get("ranking_signals_json") or ""
            visible_metrics = _j(rs) if rs else {}
        dedupe = item.get("dedupe_status") or "unique"
        slot = item.get("assigned_slot") or item.get("assigned_time") or "sin asignar"
        status = item.get("pipeline_status") or "?"
        char_count = len(caption_raw)

        # Decision badge
        decision_color = {"publish": "#22c55e", "skip": "#ef4444", "manual_review": "#f59e0b"}.get(decision, "#6b7280")
        decision_label = {"publish": "✅ Publicar", "skip": "❌ Descartar", "manual_review": "⚠️ Revisión manual"}.get(decision, decision)

        # Score breakdown rows (scores are 0–100)
        score_rows = ""
        for key, (label, tooltip) in SCORE_LABELS.items():
            val = float(score_data.get(key) or 0)
            score_rows += f"""
            <tr title="{tooltip}">
              <td class="sl">{label}</td>
              <td>{_score_bar(val, 100.0)}</td>
            </tr>"""

        # Sub-scores from source_scores
        source_scores = score_data.get("source_scores") or {}
        source_score_rows = ""
        for k, v in source_scores.items():
            label = k.replace("_score", "").replace("_", " ").title()
            source_score_rows += f'<tr><td class="sl">{label}</td><td>{_score_bar(float(v or 0), 100.0)}</td></tr>'

        # Visible metrics block
        metrics_html = ""
        if visible_metrics:
            m_items = []
            icons = {"views": "👁️", "likes": "❤️", "comments": "💬", "shares": "🔁", "bookmarks": "🔖", "quotes": "💭"}
            for mk, mv in visible_metrics.items():
                if isinstance(mv, (int, float)) and mv > 0:
                    ico = icons.get(mk, "📊")
                    val_fmt = f"{int(mv):,}".replace(",", ".")
                    m_items.append(f'<span class="metric-pill">{ico} {val_fmt}</span>')
            if m_items:
                metrics_html = f'<div class="metrics-row">{"".join(m_items)}</div>'

        # Body text preview
        body_preview = ""
        for para in body_paras:
            body_preview += f'<p class="body-p">{para}</p>'
        if not body_preview:
            body_preview = '<p class="body-p muted">Sin cuerpo extraído</p>'

        # Caption formatted
        caption_formatted = ""
        if caption_raw:
            for line in caption_raw.split("\n"):
                stripped = line.strip()
                if not stripped:
                    caption_formatted += "<br>"
                else:
                    caption_formatted += f'<span class="cap-line">{stripped}</span><br>'

        hashtags_html = " ".join(f'<span class="htag">{h}</span>' for h in hashtags) if hashtags else '<span class="muted">sin hashtags</span>'

        cards_html += f"""
<article class="card" id="n{rank}">
  <div class="card-header">
    <div class="rank-badge">#{rank}</div>
    <div class="card-meta">
      <span class="source-chip">{icon} {source}</span>
      <span class="score-chip" title="Score total de viralidad (0-100)">{score_total:.1f} / 100</span>
      <span class="theme-chip">🏷️ {theme}</span>
      <span class="format-chip">📐 {format_type}</span>
      <span class="tone-chip">🎭 {tone or 'N/A'}</span>
      <span class="decision-badge" style="background:{decision_color}">{decision_label}</span>
    </div>
    <a class="src-link" href="{url}" target="_blank" rel="noopener">🔗 Ver fuente original</a>
  </div>
  {metrics_html}

  <div class="two-col">

    <!-- ANTES -->
    <section class="panel before-panel">
      <h3 class="panel-title">📥 ANTES — Contenido crudo del scraper</h3>

      <div class="field-block">
        <label>Título original</label>
        <p class="field-value title-value">{title}</p>
      </div>

      <div class="field-block">
        <label>Extracto / bajada</label>
        <p class="field-value">{summary or '<span class="muted">No disponible</span>'}</p>
      </div>

      <div class="field-block">
        <label>Cuerpo (primeros párrafos)</label>
        <div class="body-preview">{body_preview}</div>
      </div>

      <div class="field-block">
        <label>Estado de deduplicación</label>
        <p class="dedup-tag dedup-{dedupe}">{dedupe}</p>
      </div>
    </section>

    <!-- DESPUÉS -->
    <section class="panel after-panel">
      <h3 class="panel-title">📤 DESPUÉS — Caption editorial para Instagram/Facebook</h3>

      <div class="field-block">
        <label>Título Instagram</label>
        <p class="field-value title-ig">{titulo_ig or '<span class="muted">No generado</span>'}</p>
      </div>

      <div class="field-block">
        <label>Overlay (texto sobre imagen)</label>
        <p class="field-value overlay-value">{overlay or '<span class="muted">No generado</span>'}</p>
      </div>

      <div class="field-block">
        <label>Caption completo <span class="char-count">({char_count} caracteres)</span></label>
        <div class="caption-box">{caption_formatted or '<span class="muted">No generado</span>'}</div>
      </div>

      <div class="field-block">
        <label>CTA</label>
        <p class="field-value cta-value">{cta or '<span class="muted">Sin CTA</span>'}</p>
      </div>

      <div class="field-block">
        <label>Hashtags</label>
        <div class="hashtags-row">{hashtags_html}</div>
      </div>

      <div class="field-block">
        <label>Slot programado</label>
        <p class="field-value slot-value">🕐 {slot}</p>
      </div>
    </section>
  </div>

  <!-- CRITERIO DE ELECCIÓN -->
  <section class="criteria-section">
    <h3 class="panel-title">⚖️ CRITERIO DE ELECCIÓN — Por qué fue seleccionada</h3>
    <div class="criteria-grid">
      <div class="criteria-left">
        <table class="score-table">
          <thead><tr><th>Dimensión editorial</th><th>Puntuación (0-100)</th></tr></thead>
          <tbody>{score_rows}</tbody>
        </table>
        <div class="score-total-row">
          <strong>Score total:</strong>
          <span class="score-total-val">{score_total:.1f}</span>
          {_score_bar(score_total, 100.0)}
        </div>
        {f'<details class="sub-scores"><summary>📊 Sub-scores adicionales</summary><table class="score-table" style="margin-top:8px"><thead><tr><th>Métrica interna</th><th>Valor</th></tr></thead><tbody>{source_score_rows}</tbody></table></details>' if source_score_rows else ""}
      </div>
      <div class="criteria-right">
        <div class="reason-box">
          <label>🤖 Razón del scoring</label>
          <p>{score_reason}</p>
        </div>
        <div class="reason-box">
          <label>✏️ Decisión editorial</label>
          <p><strong style="color:{decision_color}">{decision_label}</strong><br>{decision_reason or 'Sin detalle'}</p>
        </div>
        {f'<div class="reason-box"><label>🛡️ Nota de seguridad</label><p>{safety_notes}</p></div>' if safety_notes else ""}
      </div>
    </div>
  </section>
</article>
"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Prueba Controlada Pipeline — AutoPublicador Duo</title>
  <style>
    :root {{
      --bg: #0f172a;
      --surface: #1e293b;
      --surface2: #273349;
      --border: #334155;
      --accent: #3b82f6;
      --accent2: #8b5cf6;
      --before: #0f2940;
      --before-border: #1d4ed8;
      --after: #0f2a1a;
      --after-border: #16a34a;
      --criteria: #1a1a2e;
      --criteria-border: #7c3aed;
      --text: #e2e8f0;
      --text2: #94a3b8;
      --text3: #64748b;
      font-size: 15px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      padding: 0 0 60px;
    }}

    /* HEADER */
    .page-header {{
      background: linear-gradient(135deg, #1e3a5f 0%, #1e1b4b 100%);
      border-bottom: 1px solid var(--border);
      padding: 32px 40px;
      position: sticky; top: 0; z-index: 100;
    }}
    .page-header h1 {{ font-size: 1.6rem; font-weight: 800; letter-spacing: -0.5px; }}
    .page-header h1 span {{ color: #60a5fa; }}
    .page-header .meta {{
      margin-top: 6px; color: var(--text2); font-size: 0.85rem;
      display: flex; gap: 20px; flex-wrap: wrap;
    }}
    .meta-pill {{
      background: rgba(255,255,255,0.08);
      border-radius: 20px; padding: 2px 12px;
      border: 1px solid var(--border);
    }}

    /* SUMMARY BAR */
    .summary-bar {{
      display: flex; gap: 12px; padding: 20px 40px;
      background: var(--surface); border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
    }}
    .summary-stat {{
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 10px; padding: 10px 18px;
      text-align: center;
    }}
    .summary-stat .sval {{ font-size: 1.5rem; font-weight: 700; color: #60a5fa; }}
    .summary-stat .slabel {{ font-size: 0.72rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }}

    /* INDEX */
    .index-bar {{
      padding: 16px 40px;
      display: flex; gap: 8px; flex-wrap: wrap;
      background: var(--surface);
    }}
    .index-bar a {{
      padding: 4px 12px; border-radius: 20px;
      background: var(--surface2); border: 1px solid var(--border);
      color: var(--text2); text-decoration: none; font-size: 0.8rem;
      transition: all 0.15s;
    }}
    .index-bar a:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

    /* CARDS */
    .cards-container {{ padding: 24px 40px; display: flex; flex-direction: column; gap: 32px; }}

    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
    }}
    .card-header {{
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
      padding: 16px 20px;
      background: var(--surface2);
      border-bottom: 1px solid var(--border);
    }}
    .rank-badge {{
      background: linear-gradient(135deg, #3b82f6, #8b5cf6);
      color: #fff; font-weight: 800; font-size: 1.1rem;
      width: 48px; height: 48px; border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }}
    .card-meta {{ display: flex; gap: 8px; flex-wrap: wrap; flex: 1; align-items: center; }}
    .source-chip, .score-chip, .theme-chip, .format-chip {{
      padding: 3px 10px; border-radius: 20px; font-size: 0.78rem; font-weight: 600;
      border: 1px solid var(--border);
    }}
    .source-chip {{ background: #1e3a5f; color: #93c5fd; }}
    .score-chip {{ background: #1e2a1e; color: #86efac; }}
    .theme-chip {{ background: #2a1e3a; color: #c4b5fd; }}
    .format-chip {{ background: #2a1e1e; color: #fca5a5; }}
    .tone-chip {{ background: #1e2a2a; color: #67e8f9; }}
    .risk-badge {{
      padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700;
    }}
    .risk-medium {{ background: #422006; color: #fed7aa; }}
    .risk-high {{ background: #450a0a; color: #fca5a5; }}
    .metrics-row {{
      padding: 8px 20px; display: flex; gap: 8px; flex-wrap: wrap;
      border-top: 1px solid var(--border);
      background: rgba(0,0,0,0.15);
    }}
    .metric-pill {{
      background: #1e2a3a; border: 1px solid #334155;
      padding: 3px 12px; border-radius: 20px; font-size: 0.8rem;
      color: #93c5fd;
    }}
    details.sub-scores {{ margin-top: 10px; }}
    details.sub-scores summary {{
      cursor: pointer; font-size: 0.8rem; color: var(--text2);
      padding: 4px 0; user-select: none;
    }}
    .decision-badge {{
      padding: 4px 14px; border-radius: 20px; font-size: 0.8rem; font-weight: 700;
      color: #fff; margin-left: auto;
    }}
    .src-link {{
      color: var(--text2); font-size: 0.78rem; text-decoration: none;
      padding: 3px 8px; border-radius: 6px; border: 1px solid var(--border);
      white-space: nowrap;
    }}
    .src-link:hover {{ color: var(--accent); border-color: var(--accent); }}

    /* TWO COL */
    .two-col {{
      display: grid; grid-template-columns: 1fr 1fr;
      border-bottom: 1px solid var(--border);
    }}
    @media (max-width: 900px) {{
      .two-col {{ grid-template-columns: 1fr; }}
    }}

    .panel {{ padding: 20px 24px; }}
    .before-panel {{
      background: var(--before);
      border-right: 1px solid var(--border);
      border-right-color: var(--before-border);
    }}
    .after-panel {{ background: var(--after); }}
    .panel-title {{
      font-size: 0.82rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; margin-bottom: 16px; padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
      display: flex; align-items: center; gap: 6px;
    }}

    /* FIELDS */
    .field-block {{ margin-bottom: 16px; }}
    .field-block label {{
      display: block; font-size: 0.72rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--text2); margin-bottom: 5px;
    }}
    .field-value {{ color: var(--text); line-height: 1.5; font-size: 0.9rem; }}
    .title-value {{ font-size: 0.95rem; font-weight: 600; color: #e0f2fe; }}
    .title-ig {{ font-size: 0.95rem; font-weight: 700; color: #bbf7d0; }}
    .overlay-value {{
      font-size: 0.9rem; font-weight: 600; color: #fef3c7;
      background: rgba(255,200,0,0.08);
      padding: 6px 10px; border-radius: 6px;
      border-left: 3px solid #f59e0b;
    }}
    .cta-value {{
      font-size: 0.88rem; color: #a5f3fc;
      background: rgba(6,182,212,0.08);
      padding: 6px 10px; border-radius: 6px;
      border-left: 3px solid #06b6d4;
    }}
    .slot-value {{ font-size: 0.88rem; color: #c4b5fd; }}
    .muted {{ color: var(--text3); font-style: italic; font-size: 0.85rem; }}
    .char-count {{ color: var(--text3); font-size: 0.75rem; font-weight: 400; }}

    /* BODY PREVIEW */
    .body-preview {{
      background: rgba(0,0,0,0.2); border-radius: 8px; padding: 10px 14px;
      max-height: 140px; overflow-y: auto;
    }}
    .body-p {{ font-size: 0.85rem; color: var(--text2); line-height: 1.6; margin-bottom: 6px; }}

    /* CAPTION */
    .caption-box {{
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 10px;
      padding: 14px 16px;
      font-size: 0.88rem;
      line-height: 1.7;
      max-height: 260px;
      overflow-y: auto;
      color: #e6edf3;
    }}
    .cap-line {{ display: inline; }}

    /* DEDUP */
    .dedup-tag {{
      display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 0.78rem; font-weight: 600;
    }}
    .dedup-unique {{ background: #14532d; color: #86efac; }}
    .dedup-duplicate {{ background: #7f1d1d; color: #fca5a5; }}
    .dedup-similar {{ background: #451a03; color: #fed7aa; }}

    /* HASHTAGS */
    .hashtags-row {{ display: flex; gap: 6px; flex-wrap: wrap; }}
    .htag {{
      background: #1e3a5f; color: #93c5fd;
      padding: 2px 10px; border-radius: 12px; font-size: 0.78rem;
    }}

    /* CRITERIA */
    .criteria-section {{
      padding: 20px 24px;
      background: var(--criteria);
      border-top: 2px solid var(--criteria-border);
    }}
    .criteria-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 12px; }}
    @media (max-width: 900px) {{ .criteria-grid {{ grid-template-columns: 1fr; }} }}

    .score-table {{
      width: 100%; border-collapse: collapse; font-size: 0.83rem;
    }}
    .score-table th {{
      text-align: left; color: var(--text2); font-size: 0.72rem;
      text-transform: uppercase; letter-spacing: 0.05em;
      padding: 5px 8px; border-bottom: 1px solid var(--border);
    }}
    .score-table td {{ padding: 5px 8px; vertical-align: middle; }}
    .score-table .sl {{ color: var(--text2); white-space: nowrap; font-size: 0.83rem; }}
    .score-table tr:hover td {{ background: rgba(255,255,255,0.03); }}

    .bar-bg {{
      background: var(--surface); border-radius: 4px; height: 16px;
      width: 100%; position: relative; overflow: visible;
      display: flex; align-items: center;
    }}
    .bar-fill {{
      height: 100%; border-radius: 4px; transition: width 0.3s;
    }}
    .bar-label {{
      position: absolute; right: 0; font-size: 0.7rem; color: var(--text2);
      background: var(--surface); padding: 0 4px; border-radius: 3px;
    }}

    .score-total-row {{
      margin-top: 10px; display: flex; align-items: center; gap: 10px;
      font-size: 0.88rem; color: var(--text);
    }}
    .score-total-val {{
      font-size: 1.2rem; font-weight: 800; color: #60a5fa; min-width: 50px;
    }}
    .score-total-row .bar-bg {{ flex: 1; }}

    .reason-box {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 10px; padding: 14px 16px; margin-bottom: 12px;
    }}
    .reason-box label {{
      display: block; font-size: 0.72rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.06em;
      color: var(--text2); margin-bottom: 6px;
    }}
    .reason-box p {{ font-size: 0.88rem; color: var(--text); line-height: 1.5; }}

    /* FOOTER */
    .page-footer {{
      margin-top: 40px; text-align: center; color: var(--text3);
      font-size: 0.8rem; padding: 20px;
    }}
  </style>
</head>
<body>

<header class="page-header">
  <h1>🧪 Prueba Controlada — <span>AutoPublicador Duo</span></h1>
  <div class="meta">
    <span class="meta-pill">📅 {now}</span>
    <span class="meta-pill">🏆 Top {TOP_N} noticias por viralidad</span>
    <span class="meta-pill">🤖 Editorial: GPT-4.1-mini</span>
    <span class="meta-pill">📱 Destino: Instagram + Facebook</span>
    <span class="meta-pill">📏 Límite: 2200 caracteres</span>
  </div>
</header>

<div class="summary-bar">
  <div class="summary-stat">
    <div class="sval">{len(items)}</div>
    <div class="slabel">Noticias analizadas</div>
  </div>
  <div class="summary-stat">
    <div class="sval">{len(set(i.get("source","") for i in items))}</div>
    <div class="slabel">Fuentes distintas</div>
  </div>
  <div class="summary-stat">
    <div class="sval">{sum(1 for i in items if _j(i.get("editorial_json")).get("decision")=="publish")}</div>
    <div class="slabel">Aprobadas para publicar</div>
  </div>
  <div class="summary-stat">
    <div class="sval">{sum(1 for i in items if _j(i.get("editorial_json")).get("decision")=="skip")}</div>
    <div class="slabel">Descartadas</div>
  </div>
  <div class="summary-stat">
    <div class="sval">{f'{sum(float(i.get("score_total") or 0) for i in items)/max(1,len(items)):.1f}'}</div>
    <div class="slabel">Score prom. (0-100)</div>
  </div>
  <div class="summary-stat">
    <div class="sval">{f'{sum(len(_j(i.get("editorial_json")).get("texto_instagram","") or i.get("final_caption","")) for i in items)//max(1,len(items))}'}</div>
    <div class="slabel">Chars promedio caption</div>
  </div>
</div>

<nav class="index-bar">
  {''.join(f'<a href="#n{r+1}">#{r+1} {SOURCE_ICONS.get(item.get("source",""),"📄")} {(item.get("title") or "?")[:30]}...</a>' for r, item in enumerate(items))}
</nav>

<main class="cards-container">
{cards_html}
</main>

<footer class="page-footer">
  Generado por AutoPublicador Duo · {now} · D:\\WebApp_HolaSalta como referencia (sin modificar)
</footer>

</body>
</html>"""


def main() -> None:
    settings = get_settings()

    print("=" * 56)
    print("  AutoPublicador Duo — Prueba Controlada 10 Noticias")
    print("=" * 56)

    run_pipeline_stages()

    db_path = settings.sqlite_path
    print(f"\n[5/4] Generando HTML desde {db_path}...")
    items = fetch_top10(db_path)

    if not items:
        print("ERROR: No se encontraron items en la base de datos.")
        print("Asegurate de que el pipeline haya corrido al menos una vez.")
        sys.exit(1)

    print(f"      => {len(items)} items encontrados")

    REPORTE_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(items)
    REPORTE_PATH.write_text(html, encoding="utf-8")

    print(f"\n{'='*56}")
    print(f"  REPORTE GENERADO:")
    print(f"  {REPORTE_PATH.resolve()}")
    print(f"{'='*56}")
    print("\nAbrir en el navegador para ver antes/despues de cada noticia.")


if __name__ == "__main__":
    main()
