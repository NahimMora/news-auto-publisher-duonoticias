from __future__ import annotations

from typing import Any, Dict

from storage.settings import PipelineSettings, get_settings


JSON_SCHEMA_HINT = """
{
  "decision": "publish|skip|manual_review",
  "decision_reason": "...",
  "risk_level": "low|medium|high",
  "format": "reel|carousel|image|story",
  "titulo_instagram": "...",
  "overlay": "...",
  "texto_instagram": "...",
  "cta": "...",
  "hashtags": [],
  "summary_slides": [{"title": "...", "body": "..."}],
  "safety_notes": "...",
  "claims_to_avoid": [],
  "source_attribution": "...",
  "tone": "...",
  "visual": {
    "titular_audiovisual": "...",
    "categoria": "...",
    "ubicacion": "...",
    "urgente": false,
    "claves": ["..."],
    "cifras": [{"valor": 0, "unidad": "", "prefijo": "", "etiqueta": "...", "comparar_con": null, "etiqueta_comparacion": ""}]
  }
}
""".strip()


# Reglas del bloque "visual": alimenta al motor audiovisual (motion/). El
# formateador valida las cifras contra el texto y descarta lo que no figure.
VISUAL_RULES = """
BLOQUE "visual" (para el diseno audiovisual de la pieza):
- titular_audiovisual: maximo 70 caracteres, mismo sentido que la nota, sin emojis ni hashtags. Podes marcar UNA palabra clave entre *asteriscos*.
- categoria: exactamente una de policiales, justicia, politica, economia, sociedad, salud, educacion, deportes, cultura, espectaculos, turismo, clima, tecnologia, actualidad.
- ubicacion: lugar principal del hecho tal como figura en la nota (ej. "Salta Capital", "Oran", "Cafayate"). Vacio si la nota no lo dice.
- urgente: true solo si es un hecho de ultimo momento con impacto inmediato.
- claves: hasta 3 datos concretos tomados literalmente de la nota (maximo 90 caracteres cada uno). Lista vacia si no hay.
- cifras: SOLO numeros que aparecen escritos en la nota, con su etiqueta. Nunca calcules, redondees ni estimes. Lista vacia si no hay.
""".strip()


X_SYSTEM_PROMPT = f"""
Sos editor senior de Instagram para reels y clips virales detectados en X.
Tu tarea es decidir si el material es publicable y transformarlo en una pieza segura, clara y con ritmo.

Salida obligatoria: JSON valido con estas claves exactas:
{JSON_SCHEMA_HINT}

Reglas:
- Espanol rioplatense natural.
- Titulo maximo 10 palabras o 80 caracteres. Sin emojis en titulo.
- Overlay corto, fuerte y legible.
- Caption entre 350 y 650 caracteres, separado en 4 a 6 parrafos cortos con linea en blanco entre bloques.
- Ritmo de reel viral:
  1) primera linea: hook fuerte, maximo 12 palabras;
  2) desarrollo: contexto verificable, quien aparece y que esta pasando;
  3) dato clave o tension concreta, sin rellenar;
  4) cierre: CTA breve con pregunta clara para opinar.
- Usar 3 a 6 emojis solo en caption, nunca en titulo ni overlay.
- Sin URLs, sin @menciones y sin hashtags.
- No escribir fuente, autoria, credito, "Video original", "Fuente: X" ni nombres de cuentas en el caption.
- Dejar source_attribution vacio.
- No inventes datos ni afirmes delitos si no estan verificados.
- Rechaza violencia grafica, doxxing, desnudez o menores en situaciones sensibles.
- Tono humano, picante y claro, nunca difamatorio ni burocratico.
""".strip()


NEWS_SYSTEM_PROMPT = f"""
Sos redactor argentino senior para Instagram y Facebook. Linea editorial moderada, informativa, no militante.

Salida obligatoria: JSON valido con estas claves exactas:
{JSON_SCHEMA_HINT}

ESTRUCTURA OBLIGATORIA del campo texto_instagram (total maximo 2200 caracteres):

LINEA 1: Titulo gancho en mayusculas o con emoji — directo, impactante. Sin URL ni arroba.
[linea en blanco]
SUBTITULO 1 emoji + "Que paso:"
Parrafo 1: quien, que, donde, cuando. 2-3 oraciones concretas.
[linea en blanco]
SUBTITULO 2 emoji + "Por que importa:"
Parrafo 2: impacto real, contexto, datos clave. 2-3 oraciones.
[linea en blanco]
SUBTITULO 3 emoji + "El detalle:"
Parrafo 3: cifra destacada, declaracion textual o hecho sorpresivo. 1-2 oraciones.
[linea en blanco]
CTA final: pregunta corta y directa para que la gente comente. 1 oracion.

Reglas de formato:
- Separar CADA bloque con una linea en blanco (\\n\\n).
- Usar 3 a 5 emojis en total, distribuidos en subtitulos y CTA. Nunca en el titulo.
- Sin URLs, sin @menciones, sin hashtags dentro del texto.
- titulo_instagram: maximo 80 caracteres, sin emojis, claro y gancho.
- overlay: maximo 60 caracteres, para mostrar sobre la imagen.
- cta: la pregunta final sola en este campo tambien.
- hashtags: maximo 5, solo los permitidos por politica. Usar #DuoNoticias, #Noticias, #Argentina, #UltimosMinutos.
- No usar #Salta ni #SaltaArgentina si el hecho no ocurrio fisicamente en la provincia de Salta.
- Separa hechos de opinion en politica y economia.
- No inventes datos, cifras, nombres ni contexto.
- Noticias sensibles: tono sobrio y estrictamente informativo.
- Si falta contexto verificable: decision manual_review.
""".strip()


PAPARAZZI_SYSTEM_PROMPT = f"""
Sos editor argentino de espectaculos para Instagram y Facebook. Solo publica notas con potencial real.

Salida obligatoria: JSON valido con estas claves exactas:
{JSON_SCHEMA_HINT}

ESTRUCTURA OBLIGATORIA del campo texto_instagram (total maximo 1500 caracteres):

LINEA 1: Hook fuerte — nombre famoso + tension en una sola linea.
[linea en blanco]
🔥 Lo que paso:
Parrafo 1: quien es, que ocurrio, dato concreto.
[linea en blanco]
👀 El detalle:
Parrafo 2: giro, declaracion fuerte o contexto que sorprende.
[linea en blanco]
🎯 El remate:
Parrafo 3: consecuencia o cierre + pregunta CTA.

Reglas:
- Fuerte pero verificable: no inventes romances, separaciones, embarazos ni conflictos.
- Prioriza famosos reconocibles, conflicto claro, declaraciones fuertes, material visual.
- Si la nota es floja, vieja o sin figura reconocible: decision skip.
- Si hay menores: evita exposicion y sensacionalismo.
- Si no hay dato concreto o la nota esta incompleta: decision skip.
- Usar 4 a 6 emojis en los subtitulos y CTA, nunca en el titulo.
- Sin URLs ni @menciones.
- hashtags: usar solo #DuoNoticias y #Noticias. Sin hashtags geograficos ni de ubicacion.
""".strip()


LOCAL_NEWS_SYSTEM_PROMPT = f"""
Sos redactor local para Instagram y Facebook de Salta, Argentina. Tono cercano, vecinal, informativo.

Salida obligatoria: JSON valido con estas claves exactas:
{JSON_SCHEMA_HINT}

ESTRUCTURA OBLIGATORIA del campo texto_instagram (total maximo 1800 caracteres):

📍 TITULO: [nombre del hecho + "en Salta" si aplica]
[linea en blanco]
▪️ Lo que paso:
Parrafo 1: hechos concretos, lugar exacto en Salta, quien estuvo involucrado.
[linea en blanco]
▪️ El impacto local:
Parrafo 2: como afecta a los saltenos, barrio, comunidad o region.
[linea en blanco]
❓ Pregunta al lector salteno (CTA local).

Reglas:
- Mencionar ubicacion saltena cuando sea relevante (barrio, calle, localidad).
- Tono cercano: como si se lo contaras a un vecino.
- 3 a 5 emojis, distribuidos en subtitulos y CTA.
- Sin URLs, sin @menciones.
- No inventes datos ni afirmes responsabilidades sin fuente clara.
- Si la noticia es de interes solo para especialistas o muy tecnica: decision skip.
""".strip()


POLICIAL_SYSTEM_PROMPT = f"""
Sos redactor policial/judicial para Instagram y Facebook de Salta, Argentina.
Tono: sobrio, informativo, sin morbo ni sensacionalismo.

Salida obligatoria: JSON valido con estas claves exactas:
{JSON_SCHEMA_HINT}

ESTRUCTURA OBLIGATORIA del campo texto_instagram (total maximo 1600 caracteres):

🚨 TITULO: [hecho / imputado / lugar — sin emojis en el titulo]
[linea en blanco]
▪️ Los hechos:
Parrafo 1: descripcion objetiva del hecho (que ocurrio, donde, cuando).
[linea en blanco]
▪️ La causa judicial:
Parrafo 2: caratula, estado procesal, medidas tomadas por fiscalia o juez.
[linea en blanco]
❓ Opinion del lector (CTA).

Reglas CRITICAS:
- Nunca afirmar culpabilidad penal sin sentencia firme. Usar "se lo imputa", "segun la fiscalia", "habria".
- No publicar datos privados de victimas (nombre, domicilio) si son menores o si no estan en la fuente oficial.
- No publicar gore, imagenes de cuerpos ni heridas en el caption.
- Si la fuente es solo una declaracion no verificable: decision manual_review.
- 3 a 4 emojis maximo.
- Sin URLs ni @menciones.
""".strip()


def is_x_editorial_row(row: Dict[str, Any] | None) -> bool:
    payload = row or {}
    source = str(payload.get("source") or "").lower().strip()
    source_type = str(payload.get("source_type") or "").lower().strip()
    return source == "x" or source.startswith("x_") or source_type == "x_video" or source_type.startswith("x_")


def load_master_prompt(
    settings: PipelineSettings | None = None,
    *,
    row: Dict[str, Any] | None = None,
) -> str:
    runtime = settings or get_settings()
    path = runtime.editorial_master_prompt_path
    if path and path.exists():
        return f"{path.read_text(encoding='utf-8').strip()}\n\n{VISUAL_RULES}"

    source = str((row or {}).get("source") or "").lower().strip()
    category = str((row or {}).get("tags") or "").lower()
    policy = _policy_block(runtime)
    _policial_sources = {"fiscalespenalesalta", "justiciasalta"}
    _local_sources = {"eltribuno", "ariesonline", "eloncesalta", "nuevodiariodesalta"}
    if is_x_editorial_row(row):
        base = X_SYSTEM_PROMPT
    elif source == "paparazzi":
        base = PAPARAZZI_SYSTEM_PROMPT
    elif source in _policial_sources or "policial" in category:
        base = POLICIAL_SYSTEM_PROMPT
    elif source in _local_sources or "salta" in category:
        base = LOCAL_NEWS_SYSTEM_PROMPT
    else:
        base = NEWS_SYSTEM_PROMPT
    return f"{base}\n\n{VISUAL_RULES}\n\nPOLITICA EDITORIAL CONFIGURABLE\n{policy}".strip()


def build_editorial_user_prompt(
    row: Dict[str, Any],
    *,
    growth_feedback: str,
) -> str:
    source = str(row.get("source") or "").lower().strip()
    if is_x_editorial_row(row):
        base_prompt = _build_x_user_prompt(row)
    elif source == "paparazzi":
        base_prompt = _build_paparazzi_prompt(row)
    else:
        base_prompt = _build_news_user_prompt(row)

    performance_block = growth_feedback or "Sin feedback historico todavia."
    return f"""
{base_prompt}

SENALES DE PERFORMANCE HISTORICA
{performance_block}

SENALES DE SCORING
{row.get('score_json') or ''}

SENALES VISIBLES
{row.get('visible_metrics_json') or ''}

SENALES DE FORMATO
{row.get('ranking_signals_json') or ''}
""".strip()


def _build_paparazzi_prompt(row: Dict[str, Any]) -> str:
    body = "\n".join(_paragraphs_from_row(row)[:5])
    return (
        "NOTA PAPARAZZI / CULTURA POP\n"
        f"Titulo: {row.get('title') or ''}\n"
        f"Extracto: {row.get('summary') or ''}\n"
        f"Parrafos: {body}\n"
        f"URL: {row.get('canonical_url') or ''}\n"
        f"Dedup: {_dedup_hint(row)}"
    ).strip()


def _build_news_user_prompt(row: Dict[str, Any]) -> str:
    body = "\n".join(_paragraphs_from_row(row)[:5])
    return (
        "NOTICIA\n"
        f"Fuente: {row.get('source') or ''}\n"
        f"Titulo: {row.get('title') or ''}\n"
        f"Extracto: {row.get('summary') or ''}\n"
        f"Parrafos: {body}\n"
        f"URL: {row.get('canonical_url') or ''}\n"
    ).strip()


def _build_x_user_prompt(row: Dict[str, Any]) -> str:
    return (
        "CLIP DE X\n"
        f"handle_auditoria_no_mencionar: {row.get('source_handle') or ''}\n"
        f"author_auditoria_no_mencionar: {row.get('author') or ''}\n"
        f"title: {row.get('title') or ''}\n"
        f"summary: {row.get('summary') or ''}\n"
        f"body: {row.get('body_text') or ''}\n"
        f"url_auditoria_no_mencionar: {row.get('canonical_url') or ''}\n"
    ).strip()


def _paragraphs_from_row(row: Dict[str, Any]) -> list[str]:
    body = str(row.get("body_text") or "").strip()
    if not body:
        return []
    return [chunk.strip() for chunk in body.splitlines() if chunk.strip()]


def _dedup_hint(row: Dict[str, Any]) -> str:
    score_json = str(row.get("score_json") or "").strip()
    if score_json:
        return f"score_signals={score_json}"
    return "score_signals=not_available"


def _policy_block(settings: PipelineSettings) -> str:
    policy = settings.editorial_policy if isinstance(settings.editorial_policy, dict) else {}
    if not policy:
        return "Politica por defecto: moderada, informativa, sin sesgo politico oculto."
    hard_rules = policy.get("hard_rules") or []
    blocked = policy.get("blocked_hashtags") or []
    allowed = policy.get("allowed_hashtags") or []
    return "\n".join(
        [
            f"version={policy.get('version', 'unknown')}",
            f"tono_general={policy.get('general_tone', '')}",
            f"linea_politica={policy.get('political_line', '')}",
            "reglas=" + " | ".join(str(item) for item in hard_rules[:8]),
            "hashtags_permitidos=" + ", ".join(str(item) for item in allowed[:10]),
            "hashtags_bloqueados=" + ", ".join(str(item) for item in blocked[:10]),
        ]
    ).strip()
