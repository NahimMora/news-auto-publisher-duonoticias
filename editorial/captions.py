"""Validacion y armado final del caption canonico (mismo texto en IG y FB).

Todo local, sin IA:
- quita rotulos de plantilla ("Que paso:", "Por que importa:", "CTA:", "Fuente:"...)
  y lineas que nombran el medio de origen (el diseno ya muestra la fuente);
- corrige titulos en MAYUSCULAS sostenidas y el exceso de signos de exclamacion;
- verifica que cada cifra del caption figure en el material de origen;
- arma hashtags moderados (#Salta solo si el hecho es salteno; nunca partidarios);
- arma el texto final: gancho (primera linea, lo unico visible antes de "mas"),
  parrafos cortos con emoji, cierre y hashtags; garantiza el emoji inicial y saca
  emojis frivolos de las notas sensibles;
- garantiza menos de 2000 caracteres contando emojis, CTA y hashtags.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

MAX_CAPTION_CHARS = 2000
BODY_TARGET_CHARS = 1500
MAX_HASHTAGS = 4

_LABEL_RE = re.compile(
    r"^\s*(?:[^\w¿¡\s]{1,3}\s*)?(?:¿\s*)?(qu[eé] pas[oó]|por qu[eé] importa|los detalles|el detalle( clave)?|"
    r"lo que pas[oó]|el impacto( local| en salta)?|los hechos|la causa( judicial)?|el remate|cta|fuente|"
    r"contexto|en resumen|dato clave)\s*[?:]\s*",
    re.IGNORECASE,
)
_SOURCE_LINE_RE = re.compile(r"^\s*(fuente|v[ií]a|cr[eé]dito|foto|video original)\s*[:\-]", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PUNCT_SPACE_RE = re.compile(r"\s+([,.;:])")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]")

# Palabras comunes que en un titulo en mayusculas no son siglas.
_COMMON_WORDS = {
    "de", "del", "en", "la", "el", "los", "las", "con", "por", "para", "una", "uno", "un", "y", "e", "o",
    "a", "al", "que", "sin", "mas", "hoy", "ya", "agua", "luz", "gas", "paro", "tras", "ante", "sus", "su",
    "se", "es", "fue", "son", "muy", "pero", "este", "esta", "todo", "toda", "nuevo", "nueva", "gran",
    "dos", "tres", "seis", "ocho", "diez", "ruta", "calle", "video", "fotos", "murio", "corte", "cayo",
}
# Lugares que conservan mayuscula al normalizar un titulo en MAYUSCULAS.
_PROPER_PLACES = {"salta", "jujuy", "tucuman", "argentina", "oran", "cafayate", "metan", "tartagal", "cerrillos", "vaqueros", "cachi", "iruya", "mosconi"}

CATEGORY_HASHTAGS = {
    "policiales": "#Policiales",
    "justicia": "#Justicia",
    "transito": "#Transito",
    "servicios": "#Servicios",
    "clima": "#Clima",
    "salud": "#Salud",
    "educacion": "#Educacion",
    "deportes": "#Deportes",
    "cultura": "#Cultura",
    "economia": "#Economia",
    "politica": "#Politica",
    "espectaculos": "#Espectaculos",
    "tecnologia": "#Tecnologia",
    "turismo": "#Turismo",
}
# Emoji inicial del gancho cuando el modelo no puso uno (y del texto de respaldo sin IA).
CATEGORY_EMOJI = {
    "policiales": "🚨",
    "justicia": "⚖️",
    "politica": "🏛️",
    "economia": "💰",
    "sociedad": "📢",
    "salud": "🏥",
    "educacion": "🎓",
    "deportes": "⚽",
    "cultura": "🎭",
    "espectaculos": "🎬",
    "turismo": "🏔️",
    "clima": "🌦️",
    "tecnologia": "📱",
    "transito": "🚗",
    "servicios": "💡",
}
DEFAULT_EMOJI = "📌"
# Lo que Instagram muestra antes de "mas" (aprox.): el gancho tiene que entrar entero.
HOOK_MAX_CHARS = 125
# Nunca en muertes, violencia, policiales o justicia.
FRIVOLOUS_EMOJIS = ("😂", "🤣", "😅", "😜", "😎", "🥳", "🎉", "🔥", "😍", "💃", "🙌", "👏", "🤩", "😆", "😁", "🤪", "💥", "🍿")
SENSITIVE_CATEGORIES = {"policiales", "justicia"}
MAX_EMOJIS = 9

BLOCKED_HASHTAGS = {"#milei2027", "#kirchnerismo", "#antik", "#libertarios", "#peronismo"}


@dataclass
class CaptionCheck:
    caption: str
    issues: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def _ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def fix_title(title: str, max_chars: int = 90) -> str:
    clean = re.sub(r"\s+", " ", _EMOJI_RE.sub("", str(title or ""))).strip().strip('"')
    letters = [ch for ch in clean if ch.isalpha()]
    if letters and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.6:
        # Mayusculas sostenidas -> oracion, conservando siglas cortas (TN, AFA, YPF).
        words = []
        for index, word in enumerate(clean.split(" ")):
            bare = re.sub(r"\W", "", word)
            lowered = _ascii(bare)
            if lowered in _PROPER_PLACES or (index == 0 and not (bare.isupper() and len(bare) <= 3)):
                words.append(word.capitalize())
            elif bare.isupper() and 2 <= len(bare) <= 5 and lowered not in _COMMON_WORDS:
                words.append(word)  # sigla: TN, AFA, YPF, SAETA
            else:
                words.append(word.lower())
        clean = " ".join(words)
    clean = re.sub(r"!{2,}", "!", clean)
    if clean.count("!") > 1:
        first = clean.find("!")
        clean = clean[: first + 1] + clean[first + 1 :].replace("!", "")
    if len(clean) > max_chars:
        clean = clean[:max_chars].rsplit(" ", 1)[0].rstrip(",;:")
    return clean


def strip_labels(text: str, source_names: Sequence[str] = ()) -> str:
    lines: List[str] = []
    mentions = [
        re.compile(
            rf",?\s*\(?(?:seg[uú]n (?:inform[oó]|public[oó]|indic[oó]|detall[oó])\s+)?(?:el (?:diario|portal|medio|sitio)\s+)?{re.escape(name)}\)?(?=[\s.,;:]|$)",
            re.IGNORECASE,
        )
        for name in source_names
        if name and len(name) > 3
    ]
    for line in str(text or "").splitlines():
        if _SOURCE_LINE_RE.match(line):
            continue
        stripped = _LABEL_RE.sub("", line).strip()
        if not stripped and line.strip():
            continue  # linea que era solo un rotulo
        for pattern in mentions:
            # "segun informo El Tribuno" / "(Informate Salta)": el diseno ya muestra la fuente.
            stripped = pattern.sub("", stripped)
        lines.append(re.sub(r"\s{2,}", " ", stripped).rstrip())
    joined = "\n".join(lines)
    joined = re.sub(r"#[\w_]+", "", joined)
    joined = re.sub(r"https?://\S+|@\w+", "", joined)
    joined = re.sub(r"[ \t]+\n", "\n", joined)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def unsupported_numbers(caption: str, source_text: str) -> List[str]:
    def norm(raw: str) -> str:
        return raw.replace(".", "").replace(",", ".").lstrip("0") or "0"

    available = {norm(raw) for raw in _NUMBER_RE.findall(source_text or "")}
    missing = []
    for raw in _NUMBER_RE.findall(caption or ""):
        value = norm(raw)
        if value not in available and raw not in missing:
            missing.append(raw)
    return missing


def build_hashtags(*, group: str, category: str, salta_related: bool) -> List[str]:
    tags = ["#DuoNoticias"]
    if group == "local" or salta_related:
        tags.append("#Salta")
    elif group == "national":
        tags.append("#Argentina")
    category_tag = CATEGORY_HASHTAGS.get(_ascii(category))
    if category_tag and category_tag not in tags:
        tags.append(category_tag)
    return [tag for tag in tags if tag.lower() not in BLOCKED_HASHTAGS][:MAX_HASHTAGS]


def limit_body(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    while len(paragraphs) > 1 and len("\n\n".join(paragraphs)) > max_chars:
        paragraphs.pop()
    text = "\n\n".join(paragraphs)
    if len(text) > max_chars:
        cut = text[:max_chars]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: end + 1] if end > max_chars * 0.5 else cut.rsplit(" ", 1)[0] + "…"
    return text.strip()


def assemble(body: str, hashtags: Iterable[str]) -> str:
    tags = " ".join(hashtags)
    room = MAX_CAPTION_CHARS - 1 - (len(tags) + 2 if tags else 0)
    body = limit_body(body.strip(), min(room, MAX_CAPTION_CHARS))
    return f"{body}\n\n{tags}".strip() if tags else body


def check_caption(caption: str, *, source_text: str) -> CaptionCheck:
    issues: List[str] = []
    if len(caption) >= MAX_CAPTION_CHARS:
        issues.append(f"largo:{len(caption)}")
    missing = unsupported_numbers(re.sub(r"#\S+", "", caption), source_text)
    if missing:
        issues.append("cifras_sin_respaldo:" + ",".join(missing[:5]))
    for line in caption.splitlines():
        if _LABEL_RE.match(line):
            issues.append("rotulo_de_plantilla")
            break
    return CaptionCheck(caption=caption, issues=issues)


def _is_emoji_char(ch: str) -> bool:
    return unicodedata.category(ch) == "So" or 0x1F000 <= ord(ch) <= 0x1FAFF


def starts_with_emoji(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and _is_emoji_char(stripped[0])


def lead_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(_ascii(category), DEFAULT_EMOJI)


def is_sensitive(category: str, gravedad: Optional[float] = None) -> bool:
    return _ascii(category) in SENSITIVE_CATEGORIES or (gravedad is not None and gravedad >= 6)


def clean_emojis(text: str, *, sensitive: bool) -> str:
    """Saca los emojis frivolos en notas sensibles y corta el exceso (deja los primeros)."""
    if sensitive:
        for emoji in FRIVOLOUS_EMOJIS:
            text = text.replace(emoji, "")
    seen = 0
    out = []
    for ch in text:
        if _is_emoji_char(ch):
            seen += 1
            if seen > MAX_EMOJIS:
                continue
        out.append(ch)
    text = "".join(out)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def compose_body(payload: dict, *, category: str, sensitive: bool) -> str:
    """Gancho + parrafos + cierre (formato nuevo); si el modelo devolvio un "caption" plano, ese."""
    hook = re.sub(r"\s+", " ", str(payload.get("gancho") or "")).strip()
    paragraphs = payload.get("cuerpo")
    if isinstance(paragraphs, str):
        paragraphs = [p for p in paragraphs.split("\n\n")]
    parts = [str(p).strip() for p in (paragraphs or []) if str(p or "").strip()]
    closing = str(payload.get("cierre") or "").strip()
    if not hook and not parts:
        plain = str(payload.get("caption") or "").strip()
        if not plain:
            return ""
        lines = plain.split("\n\n")
        hook, parts = lines[0].strip(), [x.strip() for x in lines[1:] if x.strip()]
    if hook and not starts_with_emoji(hook):
        hook = f"{lead_emoji(category)} {hook}"
    blocks = [hook] + parts + ([closing] if closing else [])
    return clean_emojis("\n\n".join(b for b in blocks if b), sensitive=sensitive)


def apply_hook_variant(payload: dict, content_key: str) -> dict:
    """Prueba A/B de ganchos: la mitad de las notas (segun su clave) sale con ``gancho_b``.

    Instagram no permite dos versiones del mismo post: se alternan dos angulos en notas
    comparables y el reporte compara las vistas. Queda registrado en ``variante_gancho``.
    """
    if payload.get("variante_gancho"):
        return payload
    alternative = re.sub(r"\s+", " ", str(payload.get("gancho_b") or "")).strip()
    use_b = bool(alternative) and len(alternative) <= HOOK_MAX_CHARS and int(hashlib.sha1(content_key.encode("utf-8")).hexdigest(), 16) % 2 == 1
    if not use_b:
        return {**payload, "variante_gancho": "A"}
    return {**payload, "gancho_a": payload.get("gancho"), "gancho": alternative, "variante_gancho": "B"}


def hook_issues(body: str) -> List[str]:
    first = (body or "").split("\n", 1)[0]
    return [f"gancho_largo:{len(first)}"] if len(first) > HOOK_MAX_CHARS else []


def fallback_body(title: str, summary: str, body_text: str, *, max_chars: int = 900, category: str = "") -> str:
    """Sin IA: solo texto de la fuente (titulo + bajada + primeros parrafos), nada inventado."""
    parts = [f"{lead_emoji(category)} {fix_title(title, max_chars=220)}"]
    if summary and _ascii(summary)[:60] != _ascii(title)[:60]:
        parts.append(summary.strip())
    cleaned = [_PUNCT_SPACE_RE.sub(lambda m: m.group(1), p.strip()) for p in str(body_text or "").splitlines() if len(p.strip()) > 40]
    for paragraph in cleaned[:2]:
        if all(_ascii(paragraph)[:50] != _ascii(existing)[:50] for existing in parts):
            parts.append(paragraph)
    return limit_body("\n\n".join(parts), max_chars)
