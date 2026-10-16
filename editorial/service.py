from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from editorial.prompting import build_editorial_user_prompt, is_x_editorial_row, load_master_prompt
from growth.heuristics import classify_hook_type, classify_tone, text_signature
from storage.models import EditorialPackage
from storage.settings import PipelineSettings, get_settings
from utils.llm_client import generate_json


_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_TRUNCATION_MARKER_RE = re.compile(r"(\[…\]|\[\.\.\.\]|&hellip;|\.\.\.)")


class EditorialAI:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def generate(self, row: Dict[str, Any], growth_feedback: str = "", *, force_fallback: bool = False) -> EditorialPackage:
        system_prompt = load_master_prompt(self.settings, row=row)
        prompt = build_editorial_user_prompt(row, growth_feedback=growth_feedback)
        input_payload = self._build_input_payload(
            row,
            growth_feedback=growth_feedback,
            system_prompt=system_prompt,
            user_prompt=prompt,
        )
        if force_fallback:
            return self._fallback(
                row,
                growth_feedback=growth_feedback,
                prompt=prompt,
                input_payload=input_payload,
            )
        if not self.settings.llm.ready:
            return self._fallback(
                row,
                growth_feedback=growth_feedback,
                prompt=prompt,
                input_payload=input_payload,
            )
        try:
            payload = self._call_llm(system_prompt, prompt)
            normalized = self._normalize_payload(
                payload,
                row=row,
                prompt=prompt,
                input_payload=input_payload,
                growth_feedback=growth_feedback,
            )
        except Exception:
            return self._fallback(row, growth_feedback=growth_feedback, prompt=prompt, input_payload=input_payload)
        return EditorialPackage(**normalized)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        return generate_json(
            system_prompt,
            user_prompt,
            temperature=self.settings.llm_temperature,
            max_output_tokens=self.settings.llm_max_output_tokens,
            config=self.settings.llm,
        )

    def _normalize_payload(
        self,
        payload: Dict[str, Any],
        *,
        row: Dict[str, Any],
        prompt: str,
        input_payload: Dict[str, Any],
        growth_feedback: str,
    ) -> Dict[str, Any]:
        source = str(row.get("source") or "").lower().strip()
        x_style = is_x_editorial_row(row)
        raw_title = payload.get("titulo_instagram") or payload.get("hook") or row.get("title") or row.get("summary") or ""
        hook = self._clean_visual_text(raw_title)
        context = self._clean_copy_text(payload.get("context") or payload.get("resumen") or row.get("summary") or "")
        tension = self._clean_copy_text(payload.get("tension") or self._body_excerpt(row))
        remate = self._clean_copy_text(payload.get("remate") or "")
        cta = self._clean_copy_text(payload.get("cta") or "")
        overlay = self._trim_overlay_words(
            payload.get("overlay") or row.get("title") or raw_title,
            max_words=10,
        )
        caption = self._clean_caption_text(
            payload.get("caption")
            or payload.get("texto_instagram")
            or self._compose_fallback_caption(row, context, tension, remate, cta)
        )
        if x_style:
            caption = self._prepare_x_caption(caption, payload=payload, row=row)
        caption = self._ensure_caption_depth(caption, row=row, source="x" if x_style else source, cta=cta)
        caption = self._ensure_caption_emojis(caption, source="x" if x_style else source)
        reason = str(
            payload.get("reason")
            or payload.get("decision_reason")
            or payload.get("motivo")
            or "editorial_ok"
        )
        publish = self._should_publish(payload)
        style = str(payload.get("style") or payload.get("tono") or f"{source or 'duo'}_legacy")
        hook_type = classify_hook_type(hook)
        tone = classify_tone(hook, caption, style)
        return {
            "hook": hook,
            "context": context,
            "tension": tension,
            "remate": remate,
            "cta": cta,
            "caption": caption,
            "overlay": overlay,
            "publish": publish,
            "reason": reason,
            "angle": str(payload.get("angle") or payload.get("tono") or "informativo"),
            "style": style,
            "prompt_used": prompt,
            "input_payload": input_payload,
            "feedback_summary": growth_feedback,
            "hook_type": hook_type,
            "tone": tone,
            "pattern_signature": text_signature(hook, overlay, caption),
            "anti_fatigue_notes": self._extract_anti_fatigue_notes(growth_feedback),
            "raw_response": payload,
        }

    def _fallback(
        self,
        row: Dict[str, Any],
        *,
        growth_feedback: str,
        prompt: str,
        input_payload: Dict[str, Any],
    ) -> EditorialPackage:
        title = self._clean_visual_text(str(row.get("title") or row.get("summary") or "Actualizacion").strip())
        context = self._clean_copy_text(str(row.get("summary") or "").strip())
        tension = self._clean_copy_text(self._body_excerpt(row))
        remate = ""
        caption = self._clean_caption_text(self._compose_fallback_caption(row, context, tension, remate, ""))
        x_style = is_x_editorial_row(row)
        if x_style:
            caption = self._prepare_x_caption(caption, payload={}, row=row)
        caption = self._ensure_caption_depth(
            caption,
            row=row,
            source="x" if x_style else str(row.get("source") or "").lower().strip(),
            cta="",
        )
        caption = self._ensure_caption_emojis(
            caption,
            source="x" if x_style else str(row.get("source") or "").lower().strip(),
        )
        return EditorialPackage(
            hook=title,
            context=context,
            tension=tension,
            remate=remate,
            cta="",
            caption=caption,
            overlay=self._trim_overlay_words(title, max_words=10),
            publish=True,
            reason="fallback_editorial",
            angle="informativo",
            style=f"{('x' if x_style else str(row.get('source') or 'duo'))}_fallback",
            prompt_used=prompt,
            input_payload=input_payload,
            feedback_summary=growth_feedback,
            hook_type=classify_hook_type(title),
            tone=classify_tone(title, caption, f"{('x' if x_style else str(row.get('source') or 'duo'))}_fallback"),
            pattern_signature=text_signature(title, title, caption),
            anti_fatigue_notes=self._extract_anti_fatigue_notes(growth_feedback),
            raw_response={},
        )

    @classmethod
    def _clean_copy_text(cls, value: object) -> str:
        cleaned = cls._remove_truncated_tail(str(value or ""))
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _clean_visual_text(cls, value: object) -> str:
        cleaned = cls._strip_emojis(str(value or ""))
        cleaned = cls._strip_hashtags(cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def _strip_emojis(cls, value: str) -> str:
        return _EMOJI_RE.sub("", value or "").strip()

    @staticmethod
    def _strip_hashtags(value: str) -> str:
        cleaned = re.sub(r"#[\w_]+", "", value or "")
        return re.sub(r"\s+\n", "\n", cleaned).strip()

    @classmethod
    def _trim_overlay_words(cls, value: object, max_words: int) -> str:
        words = cls._clean_visual_text(value).split(" ")
        result = " ".join(word for word in words if word)[:240]
        return " ".join(result.split()[:max_words])[:90].strip()

    @classmethod
    def _clean_caption_text(cls, value: object) -> str:
        cleaned = cls._remove_truncated_tail(str(value or "")).strip()
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _remove_truncated_tail(cls, value: str) -> str:
        text = str(value or "")
        match = _TRUNCATION_MARKER_RE.search(text)
        if not match:
            return text
        prefix = text[: match.start()].rstrip()
        last_sentence = max(prefix.rfind("."), prefix.rfind("!"), prefix.rfind("?"))
        if last_sentence >= 0:
            return prefix[: last_sentence + 1].strip()
        return ""

    @classmethod
    def _append_x_attribution(cls, caption: str, *, payload: Dict[str, Any], row: Dict[str, Any]) -> str:
        source_attr = str(payload.get("source_attribution") or "").strip()
        handle = str(row.get("source_handle") or row.get("author") or "").strip().lstrip("@")
        attribution = source_attr or (f"Fuente: X / {handle}" if handle else "Fuente: X")
        attribution = re.sub(r"https?://\S+", "", attribution)
        attribution = attribution.replace("@", "")
        attribution = re.sub(r"\s+", " ", attribution).strip()
        if not attribution or attribution.lower() in caption.lower():
            return caption
        candidate = f"{caption}\n\n{attribution}".strip()
        if len(candidate) <= 420:
            return candidate
        return f"{caption}\n\nFuente: X".strip() if "fuente:" not in caption.lower() and len(caption) <= 410 else caption

    @classmethod
    def _prepare_x_caption(cls, caption: str, *, payload: Dict[str, Any], row: Dict[str, Any]) -> str:
        cleaned = cls._strip_x_attribution(caption)
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        cleaned = re.sub(r"@\w+", "", cleaned)
        cleaned = re.sub(r"#[\w_]+", "", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if len(cleaned) > 650:
            cleaned = cleaned[:649].rsplit(" ", 1)[0].strip() or cleaned[:650].strip()
        include_source = os.getenv("X_CAPTION_INCLUDE_SOURCE", "0").strip().lower() in {"1", "true", "yes", "on"}
        if include_source:
            return cls._append_x_attribution(cleaned, payload=payload, row=row)
        return cleaned

    @classmethod
    def _ensure_caption_depth(cls, caption: str, *, row: Dict[str, Any], source: str, cta: str) -> str:
        min_chars = 320 if source == "x" else 420
        max_chars = 650 if source == "x" else 900
        cleaned = cls._clean_caption_text(caption)
        if len(cleaned) >= min_chars and len([line for line in cleaned.splitlines() if line.strip()]) >= 4:
            return cls._limit_caption(cleaned, max_chars=max_chars)

        title = cls._clean_copy_text(row.get("title") or "")
        summary = cls._clean_copy_text(row.get("summary") or "")
        facts = cls._fact_lines(row)
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        if not lines and title:
            lines.append(title)
        if summary and not any(cls._is_duplicateish(line, summary) for line in lines):
            lines.append(summary)
        for fact in facts:
            if not any(cls._is_duplicateish(line, fact) for line in lines):
                lines.append(fact)
            if len(lines) >= 6:
                break
        closing = cta or ("¿Vos cómo lo ves?" if source == "x" else "¿Qué opinás?")
        if closing and not any(cls._is_duplicateish(line, closing) for line in lines):
            lines.append(closing)
        return cls._limit_caption("\n\n".join(lines), max_chars=max_chars)

    @classmethod
    def _fact_lines(cls, row: Dict[str, Any]) -> list[str]:
        body = str(row.get("body_text") or "")
        candidates = []
        for part in re.split(r"(?<=[.!?])\s+|\n+", body):
            if _TRUNCATION_MARKER_RE.search(part):
                continue
            clean = cls._clean_copy_text(part)
            if len(clean) < 45:
                continue
            candidates.append(clean)
            if len(candidates) >= 3:
                break
        return candidates

    @classmethod
    def _limit_caption(cls, caption: str, *, max_chars: int) -> str:
        cleaned = cls._clean_caption_text(caption)
        cleaned = re.sub(r"https?://\S+", "", cleaned)
        cleaned = re.sub(r"@\w+", "", cleaned)
        cleaned = re.sub(r"#[\w_]+", "", cleaned)
        cleaned = cls._clean_caption_text(cleaned)
        if len(cleaned) <= max_chars:
            return cls._trim_incomplete_ending(cleaned)
        trimmed = cleaned[: max_chars - 1].rstrip()
        trimmed = trimmed.rsplit(" ", 1)[0].strip() or cleaned[:max_chars].strip()
        return cls._trim_incomplete_ending(trimmed)

    @classmethod
    def _trim_incomplete_ending(cls, caption: str) -> str:
        cleaned = cls._clean_caption_text(caption)
        if not cleaned or cleaned[-1] in ".!?":
            return cleaned
        last_sentence = max(cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?"))
        if last_sentence >= max(0, len(cleaned) - 260):
            return cleaned[: last_sentence + 1].strip()
        parts = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
        if len(parts) > 1:
            return "\n\n".join(parts[:-1]).strip()
        return cleaned

    @classmethod
    def _strip_x_attribution(cls, caption: str) -> str:
        cleaned_lines = []
        for line in str(caption or "").splitlines():
            stripped = line.strip()
            normalized = stripped.lower()
            if re.match(r"^(fuente|via|vía|credito|crédito|video original)\b", normalized):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines).strip()
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(
            r"(?i)(?:\n\n|\s+)(?:video original de|fuente:|credito:|crédito:)\s+[^.\n]{1,90}$",
            "",
            cleaned,
        ).strip()
        return cleaned

    @classmethod
    def _compose_fallback_caption(
        cls,
        row: Dict[str, Any],
        context: str,
        tension: str,
        remate: str,
        cta: str,
    ) -> str:
        source = str(row.get("source") or "").lower().strip()
        title = str(row.get("title") or row.get("summary") or "").strip()
        if source == "noticiasargentinas":
            lines = [title if title else ""]
            if context:
                lines.append(context)
            if tension and tension not in context:
                lines.append(tension)
            question = cta or "¿Como lo ves?"
            lines.append(question)
            return "\n\n".join(line for line in lines if line)
        if is_x_editorial_row(row):
            lead = title or context or tension or "El video ya esta dando que hablar"
            lead = cls._ensure_x_caption_emoji(lead)
            lines = [lead]
            if context and not cls._is_duplicateish(lead, context):
                lines.append(context)
            if cta:
                lines.append(cta)
            else:
                lines.append("¿Qué te generó esta historia?")
            return "\n\n".join(line for line in lines if line)
        return cls._compose_plain_caption(title, context, tension, remate, cta)

    @classmethod
    def _ensure_x_caption_emoji(cls, text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            return ""
        if _EMOJI_RE.search(clean):
            return clean
        lowered = clean.lower()
        if any(token in lowered for token in ("robo", "inseguridad", "policia", "policía", "banda")):
            return f"🚨 {clean}"
        if any(token in lowered for token in ("insolito", "insólito", "absurdo", "raro")):
            return f"🤯 {clean}"
        if any(token in lowered for token in ("susto", "accidente", "peligro")):
            return f"😱 {clean}"
        return f"🔥 {clean}"

    @classmethod
    def _compose_plain_caption(cls, *parts: object) -> str:
        cleaned_parts = []
        for part in parts:
            text = cls._clean_copy_text(part)
            if not text:
                continue
            if cleaned_parts and cls._is_duplicateish(cleaned_parts[-1], text):
                continue
            cleaned_parts.append(text)
            if len(cleaned_parts) >= 3:
                break
        caption = "\n\n".join(cleaned_parts)
        if len(caption) <= 700:
            return caption
        trimmed = caption[:699].rstrip()
        trimmed = trimmed.rsplit(" ", 1)[0].strip() or trimmed
        return trimmed

    @classmethod
    def _ensure_caption_emojis(cls, caption: str, *, source: str) -> str:
        cleaned = cls._clean_caption_text(caption)
        if not cleaned:
            return cleaned
        normalized_source = str(source or "").lower().strip()
        target = 4 if normalized_source == "x" else 4 if normalized_source == "paparazzi" else 3
        if len(_EMOJI_RE.findall(cleaned)) >= target:
            return cleaned
        paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
        if not paragraphs:
            return cleaned
        emoji_pool = cls._emoji_pool_for_source(normalized_source, cleaned)
        emoji_index = 0
        for index, paragraph in enumerate(paragraphs):
            if len(_EMOJI_RE.findall("\n\n".join(paragraphs))) >= target:
                break
            if _EMOJI_RE.search(paragraph):
                continue
            emoji = emoji_pool[min(emoji_index, len(emoji_pool) - 1)]
            emoji_index += 1
            paragraphs[index] = f"{emoji} {paragraph}".strip()
        return "\n\n".join(paragraphs).strip()

    @classmethod
    def _emoji_pool_for_source(cls, source: str, caption: str) -> list[str]:
        lowered = str(caption or "").lower()
        if source == "x":
            pool = ["🔥", "😱", "📹", "👉", "😳", "🚨"]
            if any(token in lowered for token in ("robo", "policia", "policía", "allanamiento", "detenido", "seguridad")):
                pool = ["🚨", "😱", "📹", "👉", "⚠️", "😳"]
            elif any(token in lowered for token in ("insolito", "insólito", "viral", "escandalo", "escándalo")):
                pool = ["🤯", "🔥", "📹", "👉", "😳", "👀"]
            return pool
        if source == "paparazzi":
            return ["😱", "🔥", "👀", "💥", "😮", "👉"]
        if any(token in lowered for token in ("dolar", "dólar", "mercado", "economia", "economía", "inflacion", "inflación")):
            return ["📌", "💸", "📉", "👉"]
        if any(token in lowered for token in ("gobierno", "congreso", "presidente", "ministro", "ley")):
            return ["📌", "🗳️", "📰", "👉"]
        if any(token in lowered for token in ("crimen", "policial", "detenido", "allanamiento", "alerta")):
            return ["🚨", "📌", "📰", "👉"]
        return ["📰", "📌", "👉", "📍"]

    @staticmethod
    def _is_duplicateish(left: str, right: str) -> bool:
        left_norm = _EMOJI_RE.sub("", left or "").lower().strip(". ")
        right_norm = _EMOJI_RE.sub("", right or "").lower().strip(". ")
        left_norm = re.sub(r"\s+", " ", left_norm)
        right_norm = re.sub(r"\s+", " ", right_norm)
        if not left_norm or not right_norm:
            return False
        if left_norm == right_norm or left_norm in right_norm or right_norm in left_norm:
            return True
        min_prefix = min(50, len(left_norm), len(right_norm))
        return min_prefix >= 25 and left_norm[:min_prefix] == right_norm[:min_prefix]

    @classmethod
    def _body_excerpt(cls, row: Dict[str, Any]) -> str:
        body = cls._clean_copy_text(row.get("body_text") or "")
        if not body:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", body)
        for sentence in sentences:
            cleaned = cls._clean_copy_text(sentence)
            if cleaned:
                return cleaned
        return body[:220].strip()

    @staticmethod
    def _build_input_payload(
        row: Dict[str, Any],
        *,
        growth_feedback: str,
        system_prompt: str,
        user_prompt: str,
    ) -> Dict[str, Any]:
        return {
            "source": str(row.get("source") or ""),
            "source_handle": str(row.get("source_handle") or ""),
            "title": str(row.get("title") or ""),
            "summary": str(row.get("summary") or ""),
            "body_text": str(row.get("body_text") or ""),
            "score_json": str(row.get("score_json") or ""),
            "visible_metrics_json": str(row.get("visible_metrics_json") or ""),
            "ranking_signals_json": str(row.get("ranking_signals_json") or ""),
            "growth_feedback": growth_feedback,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

    @staticmethod
    def _extract_anti_fatigue_notes(growth_feedback: str) -> list[str]:
        notes = []
        for line in (growth_feedback or "").splitlines():
            line = line.strip()
            if line.startswith("- ") and "repet" in line.lower():
                notes.append(line[2:])
        return notes[:5]

    @staticmethod
    def _should_publish(payload: Dict[str, Any]) -> bool:
        if "publish" in payload:
            return bool(payload.get("publish"))
        decision = str(payload.get("decision") or "").strip().lower()
        if not decision:
            return True
        return decision in {"publish", "publicar", "published", "ok"}
