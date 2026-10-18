"""Seguimiento de acontecimientos: el mismo hecho contado por varios medios.

Adaptado de La Voz Riojana (``utils/news_dedup.py``, ``utils/editorial_router.py``,
``editorial_context/retrieval.py``), todo local, sin IA ni embeddings:

- Mismo hecho, mismo titular reescrito: Jaccard de raices de 6 letras de los
  titulos (palabras >= 4 letras, sin stopwords) >= 0.5.
- Mismo hecho con otras palabras: puntaje de relacion explicable (entidades
  propias compartidas, localidades saltenas especificas, terminos significativos,
  cercania temporal). En policiales, espectaculos y deportes se exige entidad Y
  termino compartido: la misma persona sola no alcanza (dos causas distintas del
  mismo imputado no son el mismo hecho).
- Actualizacion material: un hecho ya publicado vuelve a ser publicable solo si
  la nueva nota agrega datos sustanciales (victima fatal, detencion, condena,
  imputacion, hallazgo, cifras nuevas...). Si no, es un duplicado.

Limitacion conocida (igual que en LVR): dos notas del mismo hecho sin ninguna
entidad ni termino en comun no se agrupan.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

_STOPWORDS = {
    "a", "al", "ante", "como", "con", "de", "del", "desde", "el", "en", "entre", "esta", "este",
    "fue", "hacia", "la", "las", "lo", "los", "para", "por", "que", "se", "sin", "son", "sus",
    "tras", "una", "uno", "y", "pero", "mas", "muy", "tambien", "sobre", "hasta", "donde", "cual",
}
# "y" no une: "Kicillof y Maximo Kirchner" son dos entidades. San/Santa abren nombres (Santa Ana).
_CONNECTOR_WORDS = {"de", "del", "la", "las", "los", "el", "al", "da"}
# Inicio de oracion con forma verbal ("Aparecio Sofia", "Encontraron a"): no es parte del nombre.
_VERB_START_RE = re.compile(r"(?:ó|aron|ieron|aba|ían|ará|erá|irá|aban)$", re.I)
_GENERIC_SINGLE_WORDS = {
    "gobierno", "policia", "provincia", "municipio", "ministerio", "hospital", "escuela", "hoy",
    "ayer", "manana", "noticia", "noticias", "informe", "operativo", "incendio", "accidente",
    "partido", "choque", "temporal", "denuncia", "comunicado", "ultimo", "momento", "situacion",
    "caso", "hecho", "nota", "video", "videos", "salta", "argentina", "fuerte", "grave",
}
_GENERIC_TERMS = _GENERIC_SINGLE_WORDS | {
    "para", "con", "sus", "este", "esta", "fueron", "despues", "luego", "cuando", "medida", "medidas",
    "jornada", "semana", "horas", "personas", "lugar", "parte", "marco", "traves", "durante", "donde",
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
    # Jerga de los partes policiales: aparece en casi todos y no identifica un hecho.
    "controles", "control", "preventivo", "preventivos", "prevencion", "distritos", "distrito", "efectivos",
    "personal", "patrullaje", "patrullajes", "operativos", "procedimiento", "intervino", "fiscalias",
}
_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+")
_NUMBER_RE = re.compile(r"\b\d{1,3}(?:\.\d{3})+\b|\b\d+\b")

# Localidades saltenas: senal de lugar especifico para agrupar y para el hashtag #Salta.
SALTA_LOCALITIES = {
    "salta capital", "oran", "san ramon de la nueva oran", "tartagal", "metan", "cafayate",
    "rosario de la frontera", "rosario de lerma", "general guemes", "cerrillos", "vaqueros",
    "la caldera", "chicoana", "campo quijano", "embarcacion", "pichanal", "coronel moldes",
    "el carril", "cachi", "iruya", "joaquin v. gonzalez", "apolinario saravia", "valle de lerma",
    "valles calchaquies", "san bernardo", "aguaray", "mosconi", "general mosconi", "colonia santa rosa",
    "hipolito yrigoyen", "las lajitas", "la merced", "san lorenzo", "salvador mazza", "la vina",
    "el galpon", "molinos", "san carlos", "santa victoria", "nazareno", "rivadavia", "anta",
    "el quebrachal", "urundel", "el tala", "la candelaria", "guachipas", "animana", "seclantas",
}
SALTA_WIDE = {"salta", "salteno", "saltena", "saltenos", "saltenas", "provincia de salta"}

MATERIAL_UPDATE_KEYWORDS = {
    "victima fatal", "murio", "murieron", "fallecio", "fallecieron", "sin vida", "muerto", "muertos",
    "evacuado", "evacuados", "detenido", "detenidos", "detuvieron", "detencion", "aprehendido",
    "imputado", "imputaron", "imputacion", "condenado", "condenaron", "condena", "sentencia",
    "procesado", "liberado", "liberaron", "hallado", "hallada", "hallaron", "encontraron", "aparecio",
    "identificado", "identificada", "identificaron", "confirmo", "confirmaron", "resultado definitivo",
    "reabre", "reapertura", "cerrado", "cierre", "se entrego", "prision preventiva", "rescatado",
}
STRICT_CATEGORIES = {"policiales", "espectaculos", "deportes"}
# Instituciones y lugares que aparecen en casi todas las notas de una fuente: no identifican un hecho.
GENERIC_ENTITIES = {
    "policia de salta", "policia de la provincia", "policia", "fiscalia", "ministerio publico fiscal",
    "capital", "salta capital", "gobierno de salta", "gobierno de la provincia", "provincia de salta",
    "municipalidad de salta", "municipalidad", "ministerio de seguridad", "ministerio de salud",
    "argentina", "buenos aires", "gobierno nacional", "nacion", "fiscalias", "fiscalia penal",
    "division", "comisaria", "distritos de prevencion", "personal",
}
# Una entidad presente en tantas notas recientes distintas se considera generica.
GENERIC_DOCUMENT_FREQUENCY = 4
TITLE_DUPLICATE_THRESHOLD = 0.5
# Coseno TF-IDF (titulo x2 + bajada + inicio del cuerpo) contra las notas recientes. Calibrado
# 2026-10-17 con 77 notas reales: mismo hecho 0.33-0.81; hechos distintos < 0.30.
CONTENT_SIMILARITY_THRESHOLD = 0.33
DEFAULT_RELATION_THRESHOLD = 0.45
STRICT_RELATION_THRESHOLD = 0.55


def ascii_lower(text: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def normalize_tokens(text: object) -> Set[str]:
    words = re.findall(r"[a-z0-9]+", ascii_lower(text))
    return {word[:6] for word in words if len(word) >= 4 and word not in _STOPWORDS}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _is_sentence_start(text: str, pos: int) -> bool:
    # Solo espacios: un salto de linea separa titulo/bajada/parrafo y cuenta como inicio de oracion.
    prefix = text[:pos].rstrip(" \t")
    return not prefix or prefix[-1] in ".!?:\n\"'«“¡¿"


def extract_entities(*texts: object, max_entities: int = 20) -> List[str]:
    """Nombres propios y siglas (corridas de palabras capitalizadas, con conectores)."""
    text = "\n".join(str(t or "") for t in texts if t)
    entities: List[str] = []
    seen: Set[str] = set()
    buffer: List[str] = []
    starts_sentence = False
    has_acronym = False
    pending: List[str] = []
    prev_end = 0

    def flush() -> None:
        nonlocal buffer, starts_sentence, has_acronym
        words = list(buffer)
        while words and words[0].lower() in _CONNECTOR_WORDS:
            words.pop(0)
        while words and words[-1].lower() in _CONNECTOR_WORDS:
            words.pop()
        if words and starts_sentence and len(words) > 1 and not words[0].isupper() and _VERB_START_RE.search(words[0]):
            # "Aparecio Sofia en Salta": la mayuscula de inicio de oracion no es parte del nombre.
            words.pop(0)
            while words and words[0].lower() in _CONNECTOR_WORDS:
                words.pop(0)
        if words:
            key = ascii_lower(" ".join(words))
            lone_start = len(words) == 1 and starts_sentence and not has_acronym and key not in {ascii_lower(w) for w in buffer[1:]}
            if not lone_start and key not in seen and not (len(words) == 1 and (key in _GENERIC_SINGLE_WORDS or len(key) < 3)):
                seen.add(key)
                entities.append(key)
        buffer, starts_sentence, has_acronym = [], False, False

    for match in _WORD_RE.finditer(text):
        gap = text[prev_end : match.start()]
        prev_end = match.end()
        if any(ch.isdigit() for ch in gap) or any(ch in gap for ch in ".,;:!?()\n"):
            pending = None
            flush()
        word = match.group(0)
        acronym = word.isupper() and len(word) >= 2
        capitalized = word[0].isupper() and not word.isupper()
        if acronym or capitalized:
            if pending and buffer:
                buffer.extend(pending)
            pending = []
            if not buffer:
                starts_sentence = _is_sentence_start(text, match.start())
            buffer.append(word)
            has_acronym = has_acronym or acronym
        elif word.lower() in _CONNECTOR_WORDS and buffer:
            pending.append(word)
        else:
            pending = []
            flush()
        if len(entities) >= max_entities:
            break
    flush()
    return entities[:max_entities]


def extract_localities(*texts: object) -> List[str]:
    blob = f" {ascii_lower(' '.join(str(t or '') for t in texts))} "
    blob = re.sub(r"[^a-z0-9. ]+", " ", blob)
    found = [term for term in SALTA_LOCALITIES if f" {term} " in blob]
    if any(f" {term} " in blob for term in SALTA_WIDE):
        found.append("salta")
    return sorted(set(found))


def mentions_salta(*texts: object) -> bool:
    return bool(extract_localities(*texts))


def significant_terms(*texts: object, exclude: Iterable[str] = ()) -> Set[str]:
    excluded: Set[str] = set()
    for entity in exclude:
        normalized = ascii_lower(entity)
        excluded.add(normalized)
        excluded.update(normalized.split())
    tokens = {ascii_lower(m.group(0)) for m in _WORD_RE.finditer(" ".join(str(t or "") for t in texts)) if len(m.group(0)) >= 5}
    return {token for token in tokens if token not in _GENERIC_TERMS and token not in excluded and token not in _STOPWORDS}


def numbers_in(text: object) -> Set[str]:
    return {raw.replace(".", "") for raw in _NUMBER_RE.findall(str(text or "")) if not (len(raw) == 4 and raw.startswith(("19", "20")))}


def material_update_signals(new_text: str, previous_text: str) -> List[str]:
    """Datos sustanciales que aparecen en la nota nueva y no estaban antes."""
    new_lower, old_lower = ascii_lower(new_text), ascii_lower(previous_text)
    signals = [kw for kw in sorted(MATERIAL_UPDATE_KEYWORDS) if re.search(rf"\b{re.escape(kw)}\b", new_lower) and not re.search(rf"\b{re.escape(kw)}\b", old_lower)]
    fresh_numbers = sorted(numbers_in(new_text) - numbers_in(previous_text))
    if fresh_numbers and signals:
        signals.append("cifras_nuevas:" + ",".join(fresh_numbers[:4]))
    return signals


def event_category(source: object, url: object = "", group: str = "") -> str:
    text = ascii_lower(f"{source} {url}")
    if group == "paparazzi" or "espectaculo" in text or "zapping" in text or "teleshow" in text or "/show/" in text:
        return "espectaculos"
    if "polic" in text:
        return "policiales"
    if "deporte" in text or "tiro-libre" in text or "/futbol/" in text:
        return "deportes"
    return "general"


def _parse_ts(value: object) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass
class EventProbe:
    """Lo minimo de una nota para compararla con un acontecimiento."""

    content_key: str
    title: str
    summary: str = ""
    lead: str = ""
    category: str = "general"
    published_at: str = ""
    entities: List[str] = field(default_factory=list)
    localities: List[str] = field(default_factory=list)

    @classmethod
    def build(cls, content_key: str, title: str, summary: str = "", lead: str = "", category: str = "general", published_at: str = "") -> "EventProbe":
        return cls(
            content_key=content_key,
            title=title or "",
            summary=summary or "",
            lead=lead or "",
            category=category,
            published_at=published_at,
            entities=extract_entities(title, summary),
            localities=extract_localities(title, summary, lead),
        )

    @property
    def text(self) -> str:
        return " ".join(part for part in (self.title, self.summary, self.lead) if part)

    def stems(self) -> Counter:
        words = re.findall(r"[a-z0-9]+", ascii_lower(f"{self.title} {self.title} {self.summary} {self.lead}"))
        return Counter(word[:6] for word in words if len(word) >= 4 and word not in _STOPWORDS)


def content_vectors(probes: Sequence[EventProbe]) -> Dict[str, Dict[str, float]]:
    """TF-IDF normalizado por nota, con la frecuencia documental de la ventana reciente."""
    stems = {probe.content_key: probe.stems() for probe in probes}
    df: Counter = Counter()
    for counts in stems.values():
        df.update(set(counts))
    total = len(stems)
    vectors: Dict[str, Dict[str, float]] = {}
    for key, counts in stems.items():
        vector = {t: (1 + math.log(n)) * math.log((total + 1) / (df[t] + 1)) for t, n in counts.items()}
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        vectors[key] = {t: v / norm for t, v in vector.items()}
    return vectors


def cosine(left: Dict[str, float], right: Dict[str, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(term, 0.0) for term, value in left.items())


@dataclass
class EventMatch:
    event_key: str
    score: float
    reason: str
    matched_entities: List[str] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)


def shared_entities(left: Iterable[str], right: Iterable[str], generic: Set[str] = frozenset()) -> List[str]:
    """Entidades en comun, aceptando contencion ("barrio miguel ortiz" ~ "miguel ortiz")."""
    a = [e for e in left if e not in generic and e not in GENERIC_ENTITIES]
    b = [e for e in right if e not in generic and e not in GENERIC_ENTITIES]
    shared = set()
    for x in a:
        for y in b:
            if x == y:
                shared.add(x)
                continue
            short, long_ = (x, y) if len(x) < len(y) else (y, x)
            if len(short) < len(long_) and len(short) >= 6 and f" {short} " in f" {long_} ":
                shared.add(short)
    return sorted(shared)


def relation_score(probe: EventProbe, other: EventProbe, generic: Set[str] = frozenset()) -> Tuple[float, List[str], List[str], List[str]]:
    """Formula de LVR (retrieval.score_candidate) con localidades saltenas."""
    entities = shared_entities(probe.entities, other.entities, generic)
    localities = sorted(set(probe.localities) & set(other.localities))
    specific = [loc for loc in localities if loc != "salta"]
    terms = sorted(
        significant_terms(probe.title, probe.summary, exclude=probe.entities)
        & significant_terms(other.title, other.summary, exclude=other.entities)
    )
    score = 0.0
    reasons: List[str] = []
    if entities:
        score += min(len(entities), 2) * 0.35
        reasons.append("entidad:" + ",".join(entities[:3]))
    if specific:
        score += min(len(specific), 2) * 0.15
        reasons.append("localidad:" + ",".join(specific[:2]))
    elif localities:
        score += 0.05
    if probe.category == other.category and probe.category != "general":
        score += 0.10
    if terms:
        score += min(len(terms), 3) * 0.05
        reasons.append("terminos:" + ",".join(terms[:3]))
    a, b = _parse_ts(probe.published_at), _parse_ts(other.published_at)
    if a is not None and b is not None:
        days = abs(a - b) / 86400.0
        score += max(0.0, 0.15 - (days / 3.0) * 0.15)
    return min(round(score, 4), 1.0), entities, terms, reasons


def meets_bar(category: str, score: float, entities: Sequence[str], terms: Sequence[str], localities_shared: bool) -> bool:
    # Un lugar compartido no es una entidad del hecho (dos partes distintos en Oran).
    named = [e for e in entities if e not in SALTA_LOCALITIES and e != "salta"]
    if category in STRICT_CATEGORIES:
        return score >= STRICT_RELATION_THRESHOLD and bool(named) and len(terms) >= 2
    return score >= DEFAULT_RELATION_THRESHOLD and (bool(named) or localities_shared) and (len(terms) >= 2 or len(named) >= 2)


def generic_entities(members: Dict[str, List[EventProbe]]) -> Set[str]:
    counts: Dict[str, int] = {}
    for notes in members.values():
        for note in notes:
            for entity in set(note.entities):
                counts[entity] = counts.get(entity, 0) + 1
    return {entity for entity, count in counts.items() if count >= GENERIC_DOCUMENT_FREQUENCY}


def match_event(probe: EventProbe, members: Dict[str, List[EventProbe]], generic: Optional[Set[str]] = None) -> Optional[EventMatch]:
    """Mejor acontecimiento existente para la nota, o None si es un hecho nuevo."""
    generic = generic_entities(members) if generic is None else generic
    probe_tokens = normalize_tokens(probe.title)
    everyone = [probe] + [note for notes in members.values() for note in notes if note.content_key != probe.content_key]
    vectors = content_vectors(everyone)
    best: Optional[EventMatch] = None
    for event_key, notes in members.items():
        for other in notes:
            if other.content_key == probe.content_key:
                continue
            similarity = jaccard(probe_tokens, normalize_tokens(other.title))
            content = cosine(vectors[probe.content_key], vectors.get(other.content_key, {}))
            if similarity >= TITLE_DUPLICATE_THRESHOLD:
                candidate = EventMatch(event_key, round(0.6 + similarity * 0.4, 4), f"titulo_similar:{similarity:.2f}")
            elif content >= CONTENT_SIMILARITY_THRESHOLD and len(everyone) >= 3:
                candidate = EventMatch(event_key, round(0.5 + content * 0.5, 4), f"contenido_similar:{content:.2f}")
            else:
                score, entities, terms, reasons = relation_score(probe, other, generic)
                category = probe.category if probe.category != "general" else other.category
                shared_place = bool(set(l for l in probe.localities if l != "salta") & set(l for l in other.localities if l != "salta"))
                if not meets_bar(category, score, entities, terms, shared_place):
                    continue
                candidate = EventMatch(event_key, score, ";".join(reasons), entities, terms)
            if best is None or candidate.score > best.score:
                best = candidate
    return best


def new_event_key(content_key: str) -> str:
    """Clave deterministica atada a la primera nota real del hecho (como el story_key de LVR)."""
    return "event:" + hashlib.sha1(content_key.encode("utf-8")).hexdigest()[:12]


def version_quality(row: Dict[str, Any], *, has_usable_video: bool = False) -> float:
    """Que version del hecho conviene producir: video valido, texto completo, actualidad."""
    body = str(row.get("body_text") or "")
    assets = str(row.get("assets_json") or "")
    score = 0.0
    if has_usable_video or '"kind": "video"' in assets:
        score += 3.0
    score += min(len(body) / 1000.0, 3.0)
    if '"kind": "image"' in assets:
        score += 0.5
    ts = _parse_ts(row.get("created_at"))
    if ts is not None:
        score += min(0.5, max(0.0, 0.5 - (datetime.now(timezone.utc).timestamp() - ts) / 86400.0))
    return round(score, 3)
