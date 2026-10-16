"""
Preview estático de formato de noticias — AutoPublicador Duo.

Lee los items editorizados del DB real y genera un HTML que muestra
EXACTAMENTE cómo se verá cada post publicado:
  - Mock de Instagram (phone frame)
  - Caption completo como aparece en el feed
  - Card de web (estilo Duo Next.js)

Sin publicar nada. Sin correr pipeline.

Uso:
    python preview_formato_noticias.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = Path("data/duo_pipeline.sqlite3")
OUT_PATH = Path("data/preview_formato_noticias.html")
TOP_N = 10

SOURCE_ICONS = {
    "tn": "📺", "infobae": "📰", "paparazzi": "⭐",
    "ambitofinanciero": "💹", "eltribuno": "🗞️",
    "nuevodiariodesalta": "📍", "elonce": "📡",
    "minutouno": "⚡", "noticiasargentinas": "🇦🇷",
    "x": "𝕏", "fiscalespenalesalta": "⚖️", "justiciasalta": "🏛️",
}

CAT_COLORS = {
    "espectaculos": "#ec4899", "nacional": "#3b82f6",
    "salta": "#10b981", "policial_salta": "#ef4444",
    "economia": "#f59e0b", "viral": "#8b5cf6",
    "internacional": "#6366f1", "deportes": "#22c55e",
}


_SALTA_SOURCES = {
    "eltribuno", "ariesonline", "eloncesalta", "nuevodiariodesalta",
    "fiscalespenalesalta", "justiciasalta",
}

_GEO_SALTA_TAGS = {"#salta", "#saltaargentina"}

_BRAND_REPLACEMENTS = {
    "#holasalta": "#DuoNoticias",
    "#HolaSalta": "#DuoNoticias",
}

_REQUIRED_BRAND = "#DuoNoticias"


def _j(text) -> dict:
    if not text:
        return {}
    try:
        return json.loads(text) if isinstance(text, str) else (text or {})
    except Exception:
        return {}


def _clean_hashtags(hashtags: list, source: str) -> list:
    """Remove #HolaSalta, replace with #DuoNoticias; remove geo tags for non-Salta sources."""
    is_local = source in _SALTA_SOURCES
    result = []
    has_brand = False
    for h in hashtags:
        norm = h.strip()
        lower = norm.lower()
        # Replace brand
        if lower == "#holasalta":
            if not has_brand:
                result.append(_REQUIRED_BRAND)
                has_brand = True
            continue
        # Drop geo tags for national/entertainment/X sources
        if lower in _GEO_SALTA_TAGS and not is_local:
            continue
        result.append(norm)
        if norm == _REQUIRED_BRAND:
            has_brand = True
    # Ensure brand tag is always present
    if not has_brand:
        result.insert(0, _REQUIRED_BRAND)
    return result[:6]


def fetch_items() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            source, canonical_url, title, summary, raw_images,
            score_total, score_json, score_theme,
            editorial_json, final_caption, final_overlay,
            assigned_post_type, assigned_slot, pipeline_status,
            extracted_at
        FROM content_items
        WHERE editorial_json IS NOT NULL AND editorial_json NOT IN ('{}','')
        ORDER BY score_total DESC
        LIMIT ?
        """,
        (TOP_N,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fmt_caption(text: str) -> str:
    if not text:
        return '<span style="color:#666;font-style:italic">Caption no generado</span>'
    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            out.append('<div style="height:10px"></div>')
        elif any(s.startswith(e) for e in ("📣","▪","❓","🔥","📌","💬","🎯","📍","🚨","✅")):
            out.append(f'<div style="color:#93c5fd;font-weight:700;margin-top:4px">{s}</div>')
        elif s == s.upper() and len(s) > 6:
            out.append(f'<div style="font-weight:800;font-size:.95em;letter-spacing:.02em">{s}</div>')
        else:
            out.append(f'<div style="margin-bottom:2px">{s}</div>')
    return "\n".join(out)


def gradient_for(source: str) -> str:
    palettes = {
        "paparazzi": "linear-gradient(135deg,#7c2d8e,#c2185b)",
        "tn": "linear-gradient(135deg,#1565c0,#0d47a1)",
        "infobae": "linear-gradient(135deg,#b71c1c,#880e0e)",
        "x": "linear-gradient(135deg,#000,#222)",
        "eltribuno": "linear-gradient(135deg,#1a237e,#283593)",
        "nuevodiariodesalta": "linear-gradient(135deg,#1b5e20,#2e7d32)",
        "fiscalespenalesalta": "linear-gradient(135deg,#4a148c,#6a1b9a)",
        "justiciasalta": "linear-gradient(135deg,#37474f,#546e7a)",
        "ambitofinanciero": "linear-gradient(135deg,#e65100,#bf360c)",
        "noticiasargentinas": "linear-gradient(135deg,#1a3a6b,#003087)",
        "minutouno": "linear-gradient(135deg,#880000,#b71c1c)",
        "elonce": "linear-gradient(135deg,#006064,#00838f)",
    }
    return palettes.get(source, "linear-gradient(135deg,#1e293b,#334155)")


def build_instagram_mock(item: dict, idx: int) -> str:
    source = item.get("source") or "?"
    icon = SOURCE_ICONS.get(source, "📄")
    title = (item.get("title") or "").strip()
    score = float(item.get("score_total") or 0)
    post_type = item.get("assigned_post_type") or "image"
    theme = item.get("score_theme") or "—"
    theme_color = CAT_COLORS.get(theme, "#6b7280")

    editorial = _j(item.get("editorial_json"))
    raw = editorial.get("raw_response") or {}
    caption = raw.get("texto_instagram") or editorial.get("caption") or item.get("final_caption") or ""
    overlay = raw.get("overlay") or editorial.get("overlay") or item.get("final_overlay") or ""
    titulo_ig = raw.get("titulo_instagram") or editorial.get("hook") or title[:60]
    cta = raw.get("cta") or ""
    hashtags = _clean_hashtags(raw.get("hashtags") or [], source)
    decision = raw.get("decision") or ("publish" if editorial.get("publish") else "manual_review")
    tone = raw.get("tone") or ""
    risk = raw.get("risk_level") or "low"
    format_type = raw.get("format") or post_type

    dec_color = {"publish": "#22c55e", "skip": "#ef4444", "manual_review": "#f59e0b"}.get(decision, "#6b7280")
    dec_label = {"publish": "✅ Publicar", "skip": "❌ Descartar", "manual_review": "⚠️ Revisión"}.get(decision, decision)
    risk_color = {"low": "#22c55e", "medium": "#f59e0b", "high": "#ef4444"}.get(risk, "#6b7280")

    hashtag_line = " ".join(f'<span class="ht">{h}</span>' for h in hashtags)
    caption_html = fmt_caption(caption)
    char_count = len(caption)
    bg_gradient = gradient_for(source)

    # Slides info (carousel)
    slides = raw.get("summary_slides") or []
    slides_html = ""
    if slides:
        slide_cards = "".join(
            f'<div class="slide-card"><strong>{s.get("title","")}</strong><p>{s.get("body","")}</p></div>'
            for s in slides[:4]
        )
        slides_html = f'<div class="slides-row">{slide_cards}</div>'

    return f"""
<div class="item-wrapper" id="item{idx}">
  <div class="item-header">
    <span class="rank">#{idx}</span>
    <span class="src-icon">{icon}</span>
    <span class="src-name">{source}</span>
    <span class="score-pill">{score:.1f}</span>
    <span class="theme-pill" style="background:{theme_color}22;border-color:{theme_color};color:{theme_color}">{theme}</span>
    <span class="fmt-pill">📐 {format_type}</span>
    <span class="tone-pill">🎭 {tone or '—'}</span>
    <span class="dec-badge" style="background:{dec_color}">{dec_label}</span>
    <span class="risk-pill" style="border-color:{risk_color};color:{risk_color}">⚠️ {risk}</span>
  </div>
  <div class="item-title-orig">📰 Original: {title[:100]}</div>

  <div class="two-pane">

    <!-- PHONE MOCK -->
    <div class="phone-col">
      <div class="phone-frame">
        <div class="phone-notch"></div>
        <div class="phone-screen">
          <!-- STATUS BAR -->
          <div class="ig-statusbar">
            <span>9:41</span>
            <span>▪▪▪ WiFi 🔋</span>
          </div>
          <!-- IG HEADER -->
          <div class="ig-top-bar">
            <span style="font-size:.7rem;font-weight:800;letter-spacing:.05em">DUO NOTICIAS</span>
            <span style="font-size:.65rem;color:#888">✕ 🔔</span>
          </div>
          <!-- POST HEADER -->
          <div class="ig-post-header">
            <div class="ig-avatar" style="background:{bg_gradient}">
              <span style="font-size:.8rem">{icon}</span>
            </div>
            <div style="flex:1">
              <div style="font-size:.65rem;font-weight:700">duonoticias</div>
              <div style="font-size:.55rem;color:#aaa">Patrocinado</div>
            </div>
            <span style="font-size:.8rem;color:#ccc">···</span>
          </div>
          <!-- IMAGE AREA -->
          <div class="ig-image" style="background:{bg_gradient}">
            <div class="ig-overlay-text">{overlay or titulo_ig[:50]}</div>
            <div class="ig-post-type">{format_type.upper()}</div>
            {'<div class="ig-carousel-dots"><span class="dot active"></span><span class="dot"></span><span class="dot"></span></div>' if format_type == 'carousel' else ''}
          </div>
          <!-- ACTIONS -->
          <div class="ig-actions">
            <span>♡</span><span>🗨</span><span>↗</span>
            <span style="margin-left:auto">🔖</span>
          </div>
          <!-- LIKES -->
          <div class="ig-likes">1.247 Me gusta</div>
          <!-- CAPTION PREVIEW -->
          <div class="ig-caption-preview">
            <span style="font-weight:700;font-size:.6rem">duonoticias </span>
            <span style="font-size:.6rem;color:#ddd">{(titulo_ig or title)[:55]}{'…' if len(titulo_ig or title) > 55 else ''}</span>
            <span style="font-size:.6rem;color:#888"> más</span>
          </div>
          <!-- HASHTAGS PREVIEW -->
          {'<div class="ig-hashtags-preview">' + ' '.join(h for h in hashtags[:3]) + '</div>' if hashtags else ''}
          <!-- TIME -->
          <div class="ig-time">Hace 2 horas</div>
        </div>
      </div>
      <!-- Format badge below phone -->
      <div class="format-label">📲 {format_type.upper()} · {char_count} chars</div>
    </div>

    <!-- CAPTION PANEL -->
    <div class="caption-col">
      <div class="cap-section">
        <div class="cap-section-title">📝 Título Instagram</div>
        <div class="cap-titulo-ig">{titulo_ig or '<span style="color:#666;font-style:italic">No generado</span>'}</div>
      </div>
      <div class="cap-section">
        <div class="cap-section-title">🖼️ Overlay (texto sobre imagen)</div>
        <div class="cap-overlay">{overlay or '<span style="color:#666;font-style:italic">—</span>'}</div>
      </div>
      <div class="cap-section">
        <div class="cap-section-title">📋 Caption completo <span class="char-count">{char_count} / 2200 chars</span></div>
        <div class="cap-full">{caption_html}</div>
      </div>
      {'<div class="cap-section"><div class="cap-section-title">🔲 Slides (carousel)</div>' + slides_html + '</div>' if slides_html else ''}
      <div class="cap-section">
        <div class="cap-section-title">💬 CTA</div>
        <div class="cap-cta">{cta or '<span style="color:#666;font-style:italic">—</span>'}</div>
      </div>
      <div class="cap-section">
        <div class="cap-section-title">🏷️ Hashtags ({len(hashtags)})</div>
        <div class="cap-hashtags">{hashtag_line or '<span style="color:#666;font-style:italic">Sin hashtags</span>'}</div>
      </div>
    </div>

    <!-- WEB CARD -->
    <div class="web-col">
      <div class="web-card-title">🌐 Card web (Duo)</div>
      <div class="web-card">
        <div class="web-img" style="background:{bg_gradient}">
          <span class="web-category-badge" style="background:{theme_color}">{theme}</span>
        </div>
        <div class="web-body">
          <div class="web-meta">
            <span class="web-source">{icon} {source}</span>
            <span class="web-time">hace 2h</span>
          </div>
          <h3 class="web-title">{(titulo_ig or title)[:80]}</h3>
          <p class="web-excerpt">{(item.get("summary") or caption[:120] or "")[:110]}…</p>
          <div class="web-footer">
            <span class="web-score">🔥 {score:.0f}</span>
            <span class="web-read">Leer →</span>
          </div>
        </div>
      </div>
      <!-- FB preview -->
      <div class="web-card-title" style="margin-top:14px">📘 Facebook preview</div>
      <div class="fb-card">
        <div class="fb-img" style="background:{bg_gradient}">
          <div class="fb-overlay">{overlay or titulo_ig[:40]}</div>
        </div>
        <div class="fb-body">
          <div class="fb-domain">duonoticias.com.ar</div>
          <div class="fb-title">{(titulo_ig or title)[:70]}</div>
          <div class="fb-desc">{(item.get("summary") or "")[:90]}…</div>
        </div>
      </div>
    </div>

  </div>
</div>"""


def build_html(items: list[dict]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    sources_found = sorted(set(i.get("source", "?") for i in items))
    publish_count = sum(1 for i in items
        if (_j(i.get("editorial_json")).get("raw_response") or {}).get("decision") == "publish"
        or _j(i.get("editorial_json")).get("publish"))
    skip_count = sum(1 for i in items
        if (_j(i.get("editorial_json")).get("raw_response") or {}).get("decision") == "skip")
    review_count = len(items) - publish_count - skip_count

    cards = "\n".join(build_instagram_mock(item, i + 1) for i, item in enumerate(items))

    index_html = "".join(
        f'<a href="#item{i+1}">'
        f'#{i+1} {SOURCE_ICONS.get(item.get("source",""),"📄")} '
        f'{(item.get("title") or "")[:22]}…'
        f'</a>'
        for i, item in enumerate(items)
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Preview Formato Noticias — Duo Noticias</title>
  <style>
    :root{{
      --bg:#0f172a;--surf:#1e293b;--surf2:#273349;--bdr:#334155;
      --text:#e2e8f0;--text2:#94a3b8;--text3:#64748b;
      --acc:#3b82f6;--red:#ef4444;--green:#22c55e;--amber:#f59e0b;
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);padding-bottom:80px}}

    /* HEADER */
    .page-hdr{{background:linear-gradient(135deg,#1e3a5f,#1e1b4b);border-bottom:1px solid var(--bdr);padding:22px 36px;position:sticky;top:0;z-index:100}}
    .page-hdr h1{{font-size:1.35rem;font-weight:800}}
    .page-hdr h1 span{{color:#60a5fa}}
    .meta-row{{margin-top:6px;color:var(--text2);font-size:.8rem;display:flex;gap:12px;flex-wrap:wrap}}
    .mpill{{background:rgba(255,255,255,.07);border:1px solid var(--bdr);border-radius:20px;padding:2px 11px}}

    /* STATS */
    .stats{{display:flex;gap:8px;padding:12px 36px;background:var(--surf);border-bottom:1px solid var(--bdr);flex-wrap:wrap}}
    .stat{{background:var(--surf2);border:1px solid var(--bdr);border-radius:10px;padding:8px 16px;text-align:center;min-width:90px}}
    .stat .sv{{font-size:1.25rem;font-weight:700;color:#60a5fa}}
    .stat .sl{{font-size:.67rem;color:var(--text2);text-transform:uppercase;letter-spacing:.04em;margin-top:1px}}

    /* INDEX */
    .idx{{padding:12px 36px;background:var(--surf);border-bottom:1px solid var(--bdr);display:flex;gap:5px;flex-wrap:wrap}}
    .idx a{{padding:3px 9px;border-radius:20px;background:var(--surf2);border:1px solid var(--bdr);color:var(--text2);text-decoration:none;font-size:.72rem;white-space:nowrap}}
    .idx a:hover{{background:var(--acc);color:#fff;border-color:var(--acc)}}

    /* ITEMS */
    .items{{padding:20px 36px;display:flex;flex-direction:column;gap:32px}}
    .item-wrapper{{background:var(--surf);border:1px solid var(--bdr);border-radius:16px;overflow:hidden}}
    .item-header{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 18px;background:var(--surf2);border-bottom:1px solid var(--bdr)}}
    .rank{{background:linear-gradient(135deg,#3b82f6,#8b5cf6);color:#fff;font-weight:800;font-size:.9rem;width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .src-icon{{font-size:1.1rem}}
    .src-name{{font-weight:700;font-size:.85rem;color:#93c5fd}}
    .score-pill{{background:#1e2a1e;border:1px solid #22c55e;color:#86efac;padding:2px 9px;border-radius:20px;font-size:.72rem;font-weight:700}}
    .theme-pill{{padding:2px 9px;border-radius:20px;font-size:.72rem;font-weight:600;border:1px solid}}
    .fmt-pill{{background:#1e1e2a;border:1px solid #6366f1;color:#a5b4fc;padding:2px 9px;border-radius:20px;font-size:.72rem}}
    .tone-pill{{background:#1a2a2a;border:1px solid #06b6d4;color:#67e8f9;padding:2px 9px;border-radius:20px;font-size:.72rem}}
    .dec-badge{{padding:3px 11px;border-radius:20px;font-size:.73rem;font-weight:700;color:#fff;margin-left:4px}}
    .risk-pill{{padding:2px 9px;border-radius:20px;font-size:.7rem;border:1px solid}}
    .item-title-orig{{padding:8px 18px;font-size:.8rem;color:var(--text2);background:rgba(0,0,0,.15);border-bottom:1px solid var(--bdr)}}

    /* TWO / THREE PANE */
    .two-pane{{display:grid;grid-template-columns:220px 1fr 260px;gap:0}}
    @media(max-width:1200px){{.two-pane{{grid-template-columns:200px 1fr}}}}
    @media(max-width:800px){{.two-pane{{grid-template-columns:1fr}}}}

    /* PHONE */
    .phone-col{{padding:20px 16px;display:flex;flex-direction:column;align-items:center;background:#0a0f1a;border-right:1px solid var(--bdr)}}
    .phone-frame{{width:160px;background:#111;border-radius:28px;border:3px solid #333;overflow:hidden;box-shadow:0 0 30px rgba(0,0,0,.8)}}
    .phone-notch{{width:50px;height:8px;background:#333;border-radius:0 0 8px 8px;margin:0 auto;margin-bottom:4px}}
    .phone-screen{{background:#000;min-height:300px}}
    .ig-statusbar{{display:flex;justify-content:space-between;padding:3px 8px;font-size:.48rem;color:#aaa;background:#000}}
    .ig-top-bar{{display:flex;justify-content:space-between;align-items:center;padding:4px 8px;border-bottom:1px solid #222}}
    .ig-post-header{{display:flex;align-items:center;gap:5px;padding:5px 6px}}
    .ig-avatar{{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}}
    .ig-image{{height:155px;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden}}
    .ig-overlay-text{{position:absolute;bottom:8px;left:6px;right:6px;font-size:.55rem;font-weight:800;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.9);line-height:1.3;text-transform:uppercase;letter-spacing:.02em}}
    .ig-post-type{{position:absolute;top:5px;right:6px;background:rgba(0,0,0,.6);color:#fff;font-size:.45rem;font-weight:700;padding:2px 5px;border-radius:4px;letter-spacing:.04em}}
    .ig-carousel-dots{{position:absolute;bottom:4px;left:50%;transform:translateX(-50%);display:flex;gap:3px}}
    .dot{{width:4px;height:4px;border-radius:50%;background:rgba(255,255,255,.4)}}
    .dot.active{{background:#fff}}
    .ig-actions{{display:flex;gap:8px;padding:5px 7px;font-size:.8rem}}
    .ig-likes{{font-size:.58rem;font-weight:700;padding:0 7px;color:#eee}}
    .ig-caption-preview{{padding:2px 7px 3px;font-size:.58rem;line-height:1.4;color:#ccc}}
    .ig-hashtags-preview{{padding:1px 7px;font-size:.55rem;color:#7ba3d4}}
    .ig-time{{padding:2px 7px 5px;font-size:.52rem;color:#666}}
    .format-label{{margin-top:8px;font-size:.7rem;color:var(--text2);text-align:center;background:var(--surf2);border:1px solid var(--bdr);border-radius:8px;padding:3px 10px}}

    /* CAPTION */
    .caption-col{{padding:18px;border-right:1px solid var(--bdr)}}
    .cap-section{{margin-bottom:14px}}
    .cap-section-title{{font-size:.67rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:5px;border-bottom:1px solid var(--bdr);padding-bottom:3px}}
    .cap-titulo-ig{{font-size:.9rem;font-weight:700;color:#bbf7d0;line-height:1.4}}
    .cap-overlay{{font-size:.88rem;font-weight:700;color:#fef3c7;background:rgba(255,200,0,.08);padding:7px 11px;border-radius:7px;border-left:3px solid #f59e0b}}
    .cap-full{{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:12px 14px;font-size:.82rem;line-height:1.7;color:#e6edf3;max-height:260px;overflow-y:auto}}
    .cap-cta{{font-size:.85rem;color:#a5f3fc;background:rgba(6,182,212,.08);padding:7px 11px;border-radius:7px;border-left:3px solid #06b6d4}}
    .cap-hashtags{{display:flex;gap:5px;flex-wrap:wrap}}
    .ht{{background:#1e3a5f;color:#93c5fd;padding:2px 9px;border-radius:12px;font-size:.75rem}}
    .char-count{{background:rgba(255,255,255,.06);border:1px solid var(--bdr);border-radius:10px;padding:1px 7px;font-size:.65rem;font-weight:400;color:var(--text3);margin-left:6px}}
    .slides-row{{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}}
    .slide-card{{background:var(--surf);border:1px solid var(--bdr);border-radius:8px;padding:7px 10px;font-size:.75rem;flex:1;min-width:100px}}
    .slide-card strong{{display:block;color:#93c5fd;margin-bottom:3px;font-size:.72rem}}
    .slide-card p{{color:var(--text2);line-height:1.4}}

    /* WEB CARD */
    .web-col{{padding:18px;background:#0a0f1a}}
    .web-card-title{{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text2);margin-bottom:8px;border-bottom:1px solid var(--bdr);padding-bottom:3px}}
    .web-card{{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;overflow:hidden}}
    .web-img{{height:120px;position:relative;display:flex;align-items:flex-end;padding:8px}}
    .web-category-badge{{font-size:.62rem;font-weight:700;padding:2px 8px;border-radius:10px;color:#fff;text-transform:uppercase;letter-spacing:.04em}}
    .web-body{{padding:11px 13px}}
    .web-meta{{display:flex;justify-content:space-between;margin-bottom:5px}}
    .web-source{{font-size:.7rem;color:var(--text2)}}
    .web-time{{font-size:.68rem;color:var(--text3)}}
    .web-title{{font-size:.85rem;font-weight:700;color:var(--text);line-height:1.4;margin-bottom:5px}}
    .web-excerpt{{font-size:.75rem;color:var(--text2);line-height:1.5;margin-bottom:8px}}
    .web-footer{{display:flex;justify-content:space-between;align-items:center}}
    .web-score{{font-size:.72rem;color:#f59e0b;font-weight:600}}
    .web-read{{font-size:.72rem;color:var(--acc);font-weight:600;cursor:pointer}}

    /* FB CARD */
    .fb-card{{background:#1c1e21;border:1px solid #3a3b3c;border-radius:8px;overflow:hidden}}
    .fb-img{{height:90px;position:relative;display:flex;align-items:flex-end;padding:6px}}
    .fb-overlay{{font-size:.6rem;font-weight:700;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.9);text-transform:uppercase;letter-spacing:.03em}}
    .fb-body{{padding:8px 10px;background:#3a3b3c}}
    .fb-domain{{font-size:.6rem;color:#aaa;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}}
    .fb-title{{font-size:.78rem;font-weight:700;color:#e4e6eb;margin-bottom:2px;line-height:1.3}}
    .fb-desc{{font-size:.68rem;color:#b0b3b8;line-height:1.4}}

    footer{{text-align:center;color:var(--text3);font-size:.72rem;padding:20px;margin-top:30px}}
  </style>
</head>
<body>

<header class="page-hdr">
  <h1>📱 Preview Formato — <span>Duo Noticias</span></h1>
  <div class="meta-row">
    <span class="mpill">📅 {now}</span>
    <span class="mpill">🏆 Top {len(items)} editorizadas</span>
    <span class="mpill">📲 Instagram + Facebook + Web</span>
    <span class="mpill">🚫 Sin publicar</span>
  </div>
</header>

<div class="stats">
  <div class="stat"><div class="sv">{len(items)}</div><div class="sl">Items</div></div>
  <div class="stat"><div class="sv" style="color:#22c55e">{publish_count}</div><div class="sl">Aprobar</div></div>
  <div class="stat"><div class="sv" style="color:#f59e0b">{review_count}</div><div class="sl">Revisar</div></div>
  <div class="stat"><div class="sv" style="color:#ef4444">{skip_count}</div><div class="sl">Descartar</div></div>
  <div class="stat"><div class="sv">{len(sources_found)}</div><div class="sl">Fuentes</div></div>
</div>

<nav class="idx">
  {index_html}
</nav>

<main class="items">
{cards}
</main>

<footer>
  Duo Noticias · Preview estático {now} · Sin publicar · DB real solo lectura
</footer>
</body>
</html>"""


def main() -> None:
    if not DB_PATH.exists():
        print(f"ERROR: No existe {DB_PATH}. Correr el pipeline primero.")
        return

    print("Leyendo items editorizados del DB...")
    items = fetch_items()
    if not items:
        print("No hay items con editorial_json en el DB. Correr run_editorial() primero.")
        return

    print(f"  -> {len(items)} items encontrados")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(items)
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"\nGenerado: {OUT_PATH.resolve()}")
    print(f"Tamaño: {OUT_PATH.stat().st_size // 1024} KB")

    import subprocess
    subprocess.Popen(["cmd", "/c", "start", str(OUT_PATH.resolve())])


if __name__ == "__main__":
    main()
