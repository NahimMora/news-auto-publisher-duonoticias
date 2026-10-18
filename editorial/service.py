"""Caption canonico de cada pieza seleccionada (una llamada a Gemini, con cache).

- Solo se redacta lo que ya gano un cupo (antes se redactaba todo lo que pasaba
  el scoring, aunque nunca se publicara).
- Un solo texto para Instagram y Facebook: no hay dos llamadas equivalentes.
- Cache por (version de prompt, modelo, contenido): un reintento de render o de
  publicacion reutiliza el caption; si la nota cambia, la clave cambia.
- Validacion local (``editorial/captions.py``): sin rotulos de plantilla, sin el
  nombre del medio, cifras respaldadas por la fuente, menos de 2000 caracteres.
  Si el modelo inventa una cifra se le pide una correccion una vez; si insiste,
  se usa un texto armado solo con la fuente.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from editorial import captions
from editorial.prompting import SYSTEM_PROMPT, build_editorial_user_prompt, content_kind
from jobs.events import mentions_salta
from storage.editorial_config import EditorialConfig, load_editorial_config
from storage.models import EditorialPackage
from storage.settings import PipelineSettings, get_settings
from utils.llm_client import LLMError, LLMUsage, generate_json_with_usage

LOGGER = logging.getLogger("duo.editorial")
UsageSink = Callable[..., None]


def is_x_editorial_row(row: Dict[str, Any] | None) -> bool:
    payload = row or {}
    source = str(payload.get("source") or "").lower().strip()
    source_type = str(payload.get("source_type") or "").lower().strip()
    return source == "x" or source.startswith("x_") or source_type == "x_video"


def editorial_cache_key(row: Dict[str, Any], *, version: str, extra_text: str = "", update: bool = False) -> str:
    basis = "|".join(
        [
            version,
            str(row.get("title") or ""),
            str(row.get("summary") or ""),
            str(row.get("body_text") or "")[:6000],
            extra_text,
            "update" if update else "",
        ]
    )
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


class EditorialAI:
    def __init__(
        self,
        settings: PipelineSettings | None = None,
        config: EditorialConfig | None = None,
        *,
        call: Optional[Callable[[str, str], Tuple[Dict[str, Any], LLMUsage]]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = config or load_editorial_config(self.settings)
        self.call = call or self._call_gemini
        self.version = f"{self.config.prompt_version}|{self.settings.llm.model}"

    @property
    def llm_available(self) -> bool:
        return self.settings.llm.ready or self.call is not self._call_gemini

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> Tuple[Dict[str, Any], LLMUsage]:
        return generate_json_with_usage(
            system_prompt,
            user_prompt,
            temperature=min(0.7, float(self.settings.llm_temperature)),
            max_output_tokens=max(900, int(self.settings.llm_max_output_tokens)),
            config=self.settings.llm,
        )

    def generate(
        self,
        row: Dict[str, Any],
        growth_feedback: str = "",
        *,
        relevance: Optional[Dict[str, Any]] = None,
        extra_text: str = "",
        update: bool = False,
        force_fallback: bool = False,
        usage_sink: Optional[UsageSink] = None,
        cycle_id: str | None = None,
    ) -> EditorialPackage:
        relevance = relevance or self._stored_relevance(row)
        cache_key = editorial_cache_key(row, version=self.version, extra_text=extra_text, update=update)
        cached = self._cached(row, cache_key)
        if cached is not None:
            if usage_sink:
                usage_sink(purpose="caption", model=self.settings.llm.model, items=1, input_tokens=0, output_tokens=0,
                           latency_ms=0, ok=True, cache_hit=True, cycle_id=cycle_id, content_keys=[str(row.get("content_key") or "")])
            return cached
        source_text = " ".join(str(row.get(k) or "") for k in ("title", "summary", "body_text")) + " " + extra_text
        prompt = build_editorial_user_prompt(row, relevance=relevance, extra_text=extra_text, update=update)
        if force_fallback or not self.llm_available:
            return self._fallback(row, relevance, cache_key, prompt, reason="fallback_sin_ia")

        payload: Dict[str, Any] = {}
        body = ""
        issues: list = []
        for attempt in range(2):
            try:
                payload, usage = self.call(SYSTEM_PROMPT, prompt)
            except (LLMError, ValueError, RuntimeError) as exc:
                self._record(usage_sink, None, ok=False, error=str(exc), cycle_id=cycle_id, row=row)
                LOGGER.warning("caption %s: %s", row.get("content_key"), exc)
                # Falla transitoria (503, cuota, red): la pieza vuelve a la cola y se reintenta
                # en el proximo ciclo; no se publica un texto de respaldo pobre.
                raise RuntimeError(f"caption_ia_no_disponible:{str(exc)[:120]}") from exc
            self._record(usage_sink, usage, ok=True, cycle_id=cycle_id, row=row)
            if payload.get("contexto_suficiente") is False:
                break
            body = captions.strip_labels(str(payload.get("caption") or ""), self._source_names(row))
            check = captions.check_caption(body, source_text=source_text)
            issues = check.issues
            if not issues:
                break
            prompt = build_editorial_user_prompt(
                row, relevance=relevance, extra_text=extra_text, update=update,
                correction="Tu version anterior tenia: " + "; ".join(issues) + ". Usa solo cifras que figuren en el material y no uses rotulos.",
            )

        if payload.get("contexto_suficiente") is False:
            return self._package(row, relevance, cache_key, prompt, payload, title=str(row.get("title") or ""), body="",
                                 publish=False, reason="contexto_insuficiente")
        if issues or not body:
            LOGGER.info("caption %s: se usa texto de la fuente (%s)", row.get("content_key"), ";".join(issues) or "vacio")
            return self._fallback(row, relevance, cache_key, prompt, reason="fallback_validacion:" + ";".join(issues)[:120], payload=payload)
        title = captions.fix_title(str(payload.get("titulo") or row.get("title") or ""))
        return self._package(row, relevance, cache_key, prompt, payload, title=title, body=body, publish=True, reason="caption_ia_validado")

    # -- armado ---------------------------------------------------------------

    def _package(
        self,
        row: Dict[str, Any],
        relevance: Optional[Dict[str, Any]],
        cache_key: str,
        prompt: str,
        payload: Dict[str, Any],
        *,
        title: str,
        body: str,
        publish: bool,
        reason: str,
    ) -> EditorialPackage:
        group = str((relevance or {}).get("group") or self.config.group_of(row.get("source"), row.get("source_type")))
        visual = payload.get("visual") if isinstance(payload.get("visual"), dict) else {}
        category = str(visual.get("categoria") or (relevance or {}).get("tema") or "")
        relation = int(((relevance or {}).get("flags") or {}).get("relacion_salta") or 0)
        salta = group == "local" or relation >= 2 or (group != "national" and mentions_salta(row.get("title"), row.get("summary")))
        caption = captions.assemble(body, captions.build_hashtags(group=group, category=category, salta_related=salta)) if body else ""
        overlay = captions.fix_title(title, max_chars=80)
        return EditorialPackage(
            hook=title,
            context=str(row.get("summary") or "")[:300],
            tension="",
            remate="",
            cta="",
            caption=caption,
            overlay=overlay,
            publish=publish and bool(caption),
            reason=reason,
            angle=content_kind(row, relevance),
            style=f"duo_unificado:{self.config.prompt_version}",
            prompt_used=prompt,
            input_payload={"cache_key": cache_key, "version": self.version, "group": group, "salta_hashtag": salta},
            feedback_summary="",
            hook_type="",
            tone=content_kind(row, relevance),
            pattern_signature=cache_key[:16],
            anti_fatigue_notes=[],
            raw_response=payload or {},
        )

    def _fallback(
        self,
        row: Dict[str, Any],
        relevance: Optional[Dict[str, Any]],
        cache_key: str,
        prompt: str,
        *,
        reason: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> EditorialPackage:
        if is_x_editorial_row(row):
            # Un video de redes sin IA no tiene contexto verificable suficiente: no se publica solo.
            return self._package(row, relevance, cache_key, prompt, payload or {}, title=str(row.get("title") or ""), body="",
                                 publish=False, reason=f"{reason};video_x_sin_redaccion")
        body = captions.fallback_body(str(row.get("title") or ""), str(row.get("summary") or ""), str(row.get("body_text") or ""))
        visual_payload = {"visual": (payload or {}).get("visual")} if payload and payload.get("visual") else {}
        return self._package(row, relevance, cache_key, prompt, visual_payload, title=captions.fix_title(str(row.get("title") or "")),
                             body=body, publish=True, reason=reason)

    def _cached(self, row: Dict[str, Any], cache_key: str) -> Optional[EditorialPackage]:
        if str(row.get("editorial_cache_key") or "") != cache_key:
            return None
        try:
            payload = json.loads(str(row.get("editorial_json") or ""))
        except ValueError:
            return None
        if not isinstance(payload, dict) or not payload.get("caption"):
            return None
        try:
            return EditorialPackage(**{k: v for k, v in payload.items() if k in EditorialPackage.__dataclass_fields__})
        except TypeError:
            return None

    def _source_names(self, row: Dict[str, Any]) -> Sequence[str]:
        names = {spec.display_name for spec in self.config.sources.values()}
        names.update({"Que Pasa Salta", "QuePasaSalta", "Informate", "El Tribuno de Salta"})
        return sorted(names, key=len, reverse=True)

    @staticmethod
    def _stored_relevance(row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = json.loads(str(row.get("relevance_json") or "{}"))
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _record(self, sink: Optional[UsageSink], usage: Optional[LLMUsage], *, ok: bool, cycle_id: str | None, row: Dict[str, Any], error: str = "") -> None:
        if sink is None:
            return
        input_tokens = usage.input_tokens if usage else None
        output_tokens = usage.output_tokens if usage else None
        sink(
            purpose="caption",
            model=usage.model if usage else self.settings.llm.model,
            items=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=usage.latency_ms if usage else 0,
            ok=ok,
            error=error,
            estimated_cost_usd=self.config.estimated_cost_usd(input_tokens or 0, output_tokens or 0) if usage else None,
            cycle_id=cycle_id,
            content_keys=[str(row.get("content_key") or "")],
        )
