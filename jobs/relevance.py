"""Relevancia periodistica 0-100, interpretable y economica.

Una sola llamada a Gemini evalua un lote de notas (``relevance.batch_size``) y
devuelve componentes 0-10 (impacto, urgencia, interes publico, gravedad,
novedad, repercusion, protagonista) mas dos marcas: comunicado institucional de
rutina y politica nacional de rutina. El puntaje final NO lo decide el modelo:
se calcula aca con los pesos y penalidades de ``config/editorial_scoring.yaml``,
asi cada decision se puede explicar ("impacto 8 x 0.25 + ... - rutina 25").

Antes de gastar evaluacion ya se descarto todo lo resoluble con codigo (fuente,
duplicados, vigencia, video obligatorio, validez). Las versiones duplicadas de
un mismo hecho no se evaluan: heredan el puntaje del acontecimiento.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from storage.editorial_config import EditorialConfig
from utils.llm_client import LLMConfig, LLMError, LLMUsage, generate_json_with_usage

LOGGER = logging.getLogger("duo.relevance")

COMPONENTS = ("impacto", "urgencia", "interes_publico", "gravedad", "novedad", "repercusion", "protagonista")
GROUP_LABELS = {"local": "SALTA", "national": "NACIONAL", "paparazzi": "ESPECTACULOS", "x_feed": "VIDEO_X"}

SYSTEM_PROMPT = """Sos jefe de redaccion de DUO Noticias, medio digital de Salta, Argentina.
Evalua cada nota para decidir si merece uno de los pocos lugares por hora en Instagram/Facebook.
Puntua cada componente de 0 a 10 con honestidad: la mayoria de las notas comunes valen 2-5.
No premies el sensacionalismo ni la emocion: medi relevancia real para el publico.

Componentes: impacto (personas afectadas), urgencia, interes_publico (importancia y utilidad),
gravedad (si aplica; 0 si no), novedad (hecho nuevo vs. refrito), repercusion (cuanto se va a hablar),
protagonista (solo ESPECTACULOS: que tan conocido es; 0 en el resto).

Por grupo:
- SALTA: impacto en habitantes de Salta Capital y la provincia. Transito, cortes, servicios, salud,
  clima, seguridad, educacion, deportes y cultura salteños pueden ser muy relevantes. relacion_salta:
  2 si el hecho ocurre en Salta o la afecta directamente, 1 si es indirecto, 0 si no tiene que ver.
  Si la fuente es oficial, solo vale alto lo que afecta a muchas personas (paros, cortes de agua,
  alertas, emergencias, cambios de transito o circulacion, medidas masivas). Actos, cursos,
  capacitaciones, inscripciones genericas, reuniones y visitas protocolares: rutina_institucional=true.
- NACIONAL: vara muy alta. Solo catastrofes, emergencias, hechos policiales graves, sucesos
  excepcionales o con consecuencias importantes para el pais. No exige relacion con Salta.
  Internas, cruces y declaraciones de la politica nacional: politica_nacional_rutinaria=true.
- ESPECTACULOS: fama real del protagonista, repercusion, actualidad y novedad del hecho.
- VIDEO_X: video de redes con poco texto. contexto_suficiente=false si con el texto no se puede
  saber minimamente que muestra el video.

Responde solo JSON compacto con claves cortas: {"items":[{"id","im" impacto,"ur" urgencia,
"ip" interes_publico,"gr" gravedad,"nv" novedad,"rp" repercusion,"pr" protagonista,
"rs" relacion_salta,"ri" rutina_institucional (0/1),"pn" politica_nacional_rutinaria (0/1),
"cs" contexto_suficiente (0/1),"t" tema,"m" motivo}]}. t: una palabra (policiales, transito,
servicios, clima, salud, educacion, deportes, cultura, politica, economia, sociedad, espectaculos,
tecnologia, otro). m: maximo 8 palabras."""

# Claves cortas -> nombres internos (menos tokens de salida por nota).
SHORT_KEYS = {
    "im": "impacto", "ur": "urgencia", "ip": "interes_publico", "gr": "gravedad", "nv": "novedad",
    "rp": "repercusion", "pr": "protagonista", "rs": "relacion_salta", "ri": "rutina_institucional",
    "pn": "politica_nacional_rutinaria", "cs": "contexto_suficiente", "t": "tema", "m": "motivo",
}


def expand_item(item: Dict[str, Any]) -> Dict[str, Any]:
    expanded = {SHORT_KEYS.get(key, key): value for key, value in item.items()}
    for flag in ("rutina_institucional", "politica_nacional_rutinaria", "contexto_suficiente"):
        if flag in expanded and not isinstance(expanded[flag], bool):
            expanded[flag] = bool(int(_clip(expanded[flag])))
    return expanded

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    **{key: {"type": "INTEGER"} for key in ("im", "ur", "ip", "gr", "nv", "rp", "pr", "rs", "ri", "pn", "cs")},
                    "t": {"type": "STRING"},
                    "m": {"type": "STRING"},
                },
                "required": ["id", "im", "ur", "ip", "nv", "rp", "rs", "cs"],
            },
        }
    },
    "required": ["items"],
}

LLMCall = Callable[[str, str], Tuple[Dict[str, Any], LLMUsage]]


@dataclass
class RelevanceResult:
    content_key: str
    score: float
    group: str
    components: Dict[str, float]
    penalties: Dict[str, float] = field(default_factory=dict)
    flags: Dict[str, Any] = field(default_factory=dict)
    motivo: str = ""
    tema: str = ""

    def as_payload(self, *, model: str, version: str) -> Dict[str, Any]:
        return {
            "score": self.score,
            "group": self.group,
            "components": self.components,
            "penalties": self.penalties,
            "flags": self.flags,
            "motivo": self.motivo,
            "tema": self.tema,
            "model": model,
            "version": version,
        }


def _clip(value: Any) -> float:
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def compute_score(group: str, item: Dict[str, Any], config: EditorialConfig, *, official: bool = False) -> RelevanceResult:
    """Puntaje 0-100 interpretable a partir de los componentes del modelo."""
    weights = config.weights.get(group) or config.weights.get("local") or {"impacto": 0.4, "interes_publico": 0.4, "novedad": 0.2}
    total_weight = sum(weights.values()) or 1.0
    components = {name: _clip(item.get(name)) for name in COMPONENTS}
    base = sum(components.get(name, 0.0) * weight for name, weight in weights.items()) / total_weight * 10.0
    penalties: Dict[str, float] = {}
    if item.get("rutina_institucional") and (official or group == "local"):
        penalties["rutina_institucional"] = config.penalties.get("rutina_institucional", 25.0)
    if item.get("politica_nacional_rutinaria"):
        penalties["politica_nacional_rutinaria"] = config.penalties.get("politica_nacional_rutinaria", 30.0)
    relation = int(_clip(item.get("relacion_salta")))
    if group == "local" and relation == 0:
        # Nota nacional/internacional de un medio salteno: no compite como local.
        penalties["sin_relacion_salta"] = config.penalties.get("sin_relacion_salta", 25.0)
    score = round(max(0.0, min(100.0, base - sum(penalties.values()))), 1)
    flags = {
        "relacion_salta": relation,
        "rutina_institucional": bool(item.get("rutina_institucional")),
        "politica_nacional_rutinaria": bool(item.get("politica_nacional_rutinaria")),
        "contexto_suficiente": item.get("contexto_suficiente") is not False,
        "official": official,
        "base": round(base, 1),
    }
    return RelevanceResult(
        content_key=str(item.get("content_key") or ""),
        score=score,
        group=group,
        components={name: components[name] for name in weights if name in components},
        penalties=penalties,
        flags=flags,
        motivo=str(item.get("motivo") or "")[:160],
        tema=str(item.get("tema") or "")[:30],
    )


def item_text(row: Dict[str, Any], limit: int) -> str:
    body = str(row.get("body_text") or "")
    summary = str(row.get("summary") or "")
    text = f"{summary} {body}".strip()
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def build_user_prompt(batch: Sequence[Dict[str, Any]], config: EditorialConfig) -> str:
    lines = []
    for index, row in enumerate(batch, start=1):
        group = config.group_of(row.get("source"), row.get("source_type"))
        video = row.get("_video_seconds")
        parts = [
            f"id=r{index}",
            f"grupo={GROUP_LABELS.get(group, 'SALTA')}",
            "fuente=oficial" if config.is_official(row.get("source")) else "fuente=medio",
            f"video={'si' if row.get('_has_video') else 'no'}" + (f" ({int(video)}s)" if video else ""),
        ]
        if row.get("event_role") == "update":
            parts.append("actualizacion_de_hecho_ya_publicado=si")
        lines.append(" | ".join(parts))
        lines.append(f"titulo: {str(row.get('title') or '').strip()}")
        lines.append(f"texto: {item_text(row, config.max_chars_per_item)}")
        lines.append("")
    return "Notas a evaluar:\n\n" + "\n".join(lines).strip()


class RelevanceEvaluator:
    def __init__(
        self,
        config: EditorialConfig,
        llm_config: LLMConfig,
        *,
        call: Optional[LLMCall] = None,
        usage_sink: Optional[Callable[..., None]] = None,
    ) -> None:
        self.config = config
        self.llm_config = llm_config
        self.call = call or self._call_gemini
        self.usage_sink = usage_sink
        self.version = f"{config.prompt_version}|{llm_config.model}"

    @property
    def available(self) -> bool:
        return self.llm_config.ready or self.call is not self._call_gemini

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> Tuple[Dict[str, Any], LLMUsage]:
        return generate_json_with_usage(
            system_prompt,
            user_prompt,
            temperature=0.0,
            max_output_tokens=150 * max(1, self.config.batch_size) + 400,
            config=self.llm_config,
            response_schema=RESPONSE_SCHEMA,
        )

    def evaluate(self, rows: Sequence[Dict[str, Any]], *, cycle_id: str | None = None) -> Dict[str, RelevanceResult]:
        results: Dict[str, RelevanceResult] = {}
        size = self.config.batch_size
        for start in range(0, len(rows), size):
            batch = list(rows[start : start + size])
            results.update(self._evaluate_batch(batch, cycle_id=cycle_id))
        return results

    def _evaluate_batch(self, batch: List[Dict[str, Any]], *, cycle_id: str | None) -> Dict[str, RelevanceResult]:
        prompt = build_user_prompt(batch, self.config)
        keys = [str(row.get("content_key") or "") for row in batch]
        try:
            payload, usage = self.call(SYSTEM_PROMPT, prompt)
        except (LLMError, ValueError, RuntimeError) as exc:
            LOGGER.warning("relevancia: lote de %s notas fallo: %s", len(batch), exc)
            self._record(None, items=len(batch), ok=False, error=str(exc), cycle_id=cycle_id, keys=keys)
            return {}
        self._record(usage, items=len(batch), ok=True, cycle_id=cycle_id, keys=keys)
        by_id = {str(item.get("id") or ""): expand_item(item) for item in payload.get("items") or [] if isinstance(item, dict)}
        results: Dict[str, RelevanceResult] = {}
        for index, row in enumerate(batch, start=1):
            item = by_id.get(f"r{index}")
            if item is None:
                continue  # sin respuesta para esa nota: se reintenta en el proximo ciclo
            group = self.config.group_of(row.get("source"), row.get("source_type"))
            result = compute_score(group, {**item, "content_key": row.get("content_key")}, self.config, official=self.config.is_official(row.get("source")))
            results[str(row.get("content_key") or "")] = result
        return results

    def _record(self, usage: Optional[LLMUsage], *, items: int, ok: bool, cycle_id: str | None, keys: Sequence[str], error: str = "") -> None:
        if self.usage_sink is None:
            return
        input_tokens = usage.input_tokens if usage else None
        output_tokens = usage.output_tokens if usage else None
        self.usage_sink(
            purpose="relevance_batch",
            model=usage.model if usage else self.llm_config.model,
            items=items,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=usage.latency_ms if usage else 0,
            ok=ok,
            error=error,
            estimated_cost_usd=self.config.estimated_cost_usd(input_tokens or 0, output_tokens or 0) if usage else None,
            cycle_id=cycle_id,
            content_keys=keys,
        )


def fair_order(rows: Iterable[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Intercala por fuente: el orden del scraping nunca deja a una fuente sin evaluar."""
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_source.setdefault(str(row.get("source") or ""), []).append(row)
    ordered: List[Dict[str, Any]] = []
    while len(ordered) < limit and any(by_source.values()):
        for source in sorted(by_source):
            queue = by_source[source]
            if queue:
                ordered.append(queue.pop(0))
                if len(ordered) >= limit:
                    break
    return ordered
