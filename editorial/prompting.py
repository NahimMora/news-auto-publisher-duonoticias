"""Prompt editorial unico de DUO (caption canonico para Instagram y Facebook).

Reemplaza los cinco prompts anteriores (X "picante", noticias con subtitulos
fijos "Que paso / Por que importa", Salta local, policial y Paparazzi) por una
sola linea editorial: periodistica, argentina, directa, dinamica y cercana, con
identidad saltena. El tono se ajusta por el tipo de hecho, no por la fuente.

Ahorro: sin bloques de "senales de performance", "scoring" ni JSON crudo en el
prompt (no mejoraban la redaccion); el texto de la nota se recorta a lo util.
Los hashtags los arma el codigo (``editorial/captions.py``), no el modelo.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

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

SYSTEM_PROMPT = f"""
Sos editor de DUO Noticias, medio digital de Salta, Argentina. Escribis el texto de una publicacion
para Instagram y Facebook (el mismo texto va a las dos redes).

LINEA EDITORIAL
- Periodistica, argentina, directa, dinamica y cercana, con identidad saltena. Que se sienta escrito
  por una persona de la redaccion, no por una maquina.
- La personalidad sale del tema: en notas livianas podes usar humor argentino o salteno con medida;
  nunca en muertes, homicidios, tragedias, violencia grave, victimas o sufrimiento.
- Espectaculos: tono mas entretenido y agil, sin insultos, sin inventar ni exagerar.
- Policiales: conserva la contundencia de los hechos verificados (victima fatal, detencion, condena
  firme, numero de afectados). No suavices ni exageres. Respeta exactamente la situacion procesal que
  informa la nota: detenido, investigado, acusado, imputado y condenado no son lo mismo.
- Politica: prioriza el angulo de Salta. Si una medida involucra al gobernador Gustavo Saenz y al
  Gobierno nacional, destaca los efectos concretos para Salta y la cooperacion institucional cuando la
  nota los documente. Sin tono propagandistico, sin inventar logros, sin omitir datos sustanciales
  contrarios, sin presentar opiniones como hechos ni alterar citas.

ESCRITURA DEL CAPTION
- Usa la informacion completa de la nota: que paso, donde, cuando, quienes, consecuencias, datos
  concretos y lo que sea util para el lector. Si la nota es rica, aprovechala; si tiene pocos datos,
  escribi corto. Nunca rellenes.
- Parrafos cortos separados por una linea en blanco. Emojis ocasionales y pertinentes (0 a 4).
- Prohibido usar rotulos fijos como "Que paso:", "Por que importa:", "Los detalles:", "El detalle:",
  "CTA:", "Fuente:" o subtitulos de plantilla. Tampoco nombres el medio de origen (ya figura en el diseno).
- Cierra con una invitacion natural a comentar o compartir solo si corresponde al tema; en hechos
  tragicos, nada frivolo (podes omitirla). No repitas siempre la misma pregunta.
- No inventes datos, nombres, lugares, fechas, causas ni cifras. Solo lo que dice el material.
- Sin URLs, sin @menciones, sin hashtags (se agregan aparte). Maximo 1500 caracteres.
- titulo: claro, atractivo y preciso, maximo 90 caracteres, sin MAYUSCULAS sostenidas, sin emojis,
  como maximo un signo de exclamacion, sin clickbait que contradiga la nota.

VIDEOS DE REDES (tipo=video_x)
- Muchas veces solo hay un video y una descripcion breve. No inventes lugar, fecha, identidad de las
  personas, causas ni consecuencias. Escribi solo lo que se sostiene con el texto disponible (2 a 4
  frases alcanzan). Si con el texto no se puede saber minimamente que muestra el video,
  contexto_suficiente=false.

ACTUALIZACIONES (actualizacion=si)
- El hecho ya se publico antes: conta primero el dato nuevo y despues el contexto minimo.

Salida: solo JSON {{"titulo": "...", "caption": "...", "contexto_suficiente": true, "visual": {{...}}}}

{VISUAL_RULES}
""".strip()

MAX_BODY_CHARS = 3500


def content_kind(row: Dict[str, Any], relevance: Optional[Dict[str, Any]] = None) -> str:
    source_type = str(row.get("source_type") or "").lower()
    source = str(row.get("source") or "").lower()
    if source_type == "x_video" or source == "x":
        return "video_x"
    if source == "paparazzi":
        return "espectaculos"
    tema = str((relevance or {}).get("tema") or "").lower()
    return tema or "noticia"


def build_editorial_user_prompt(
    row: Dict[str, Any],
    *,
    relevance: Optional[Dict[str, Any]] = None,
    location_hint: str = "",
    extra_text: str = "",
    update: bool = False,
    correction: str = "",
) -> str:
    """Datos de la nota, compactos. ``extra_text``: texto del video (tuit) cuando lo hay."""
    kind = content_kind(row, relevance)
    components = (relevance or {}).get("components") or {}
    gravedad = components.get("gravedad")
    body = str(row.get("body_text") or "").strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS].rsplit("\n", 1)[0]
    lines = [
        f"tipo={kind}",
        f"grupo={(relevance or {}).get('group') or ''}",
        f"actualizacion={'si' if update else 'no'}",
    ]
    if gravedad is not None:
        lines.append(f"gravedad={gravedad:.0f}/10")
    if location_hint:
        lines.append(f"lugar_probable={location_hint}")
    lines.append(f"fecha_publicacion={str(row.get('created_at') or '')[:16]}")
    lines.append(f"titulo_original: {str(row.get('title') or '').strip()}")
    summary = str(row.get("summary") or "").strip()
    if summary and summary not in body:
        lines.append(f"bajada: {summary}")
    if body:
        lines.append(f"texto:\n{body}")
    if extra_text:
        lines.append(f"texto_del_video: {extra_text.strip()[:800]}")
    if correction:
        lines.append(f"CORRECCION OBLIGATORIA: {correction}")
    return "\n".join(lines)
