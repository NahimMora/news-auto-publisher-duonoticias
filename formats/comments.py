"""Respuestas a comentarios en posts informativos (sin moderacion).

Solo preguntas concretas, respondidas con lo que dice la nota, en tono de medio
local: sin opinar, sin discutir, sin tocar culpas ni victimas. Primero un filtro
local (que sea una pregunta real) y despues Gemini, en UN lote por ciclo.

Modos (``config/formats.yaml`` -> comments.mode):
- shadow: se evalua y se guarda, no se publica (va al reporte).
- auto: shadow durante ``shadow_days`` desde el primer comentario evaluado; despues, live.
- live: se publica, con tope diario.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from formats.publish import FormatsPublisher
from formats.store import FormatsStore
from publishers.meta_api import MetaGraphPublisher
from storage.editorial_config import load_editorial_config
from storage.settings import PipelineSettings
from utils.llm_client import generate_json_with_usage

LOGGER = logging.getLogger("duo.formats.comments")
# Pedidos de dato sin signo de pregunta.
ASKING_PHRASES = ("se sabe", "saben si", "alguien sabe", "a que hora", "a qué hora", "hasta cuando", "hasta cuándo", "donde queda", "dónde queda")
SYSTEM = (
    "Sos la persona que responde comentarios de Dúo Noticias, un medio local de Salta (Argentina). Reglas: respondés SOLO preguntas "
    "concretas o pedidos de un dato; usás únicamente lo que dice la nota (si la nota no lo dice, lo decís con honestidad y no inventás); "
    "tono cercano, respetuoso y breve (máximo 220 caracteres), 0 o 1 emoji sobrio; nunca opinás de política, de la culpabilidad de "
    "personas ni de víctimas; no discutís ni respondés provocaciones o insultos; en tragedias, respeto. Si el comentario no es una "
    "pregunta concreta (opinión, emoji, insulto, chiste, spam), NO se responde."
)


def looks_like_question(text: str) -> bool:
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    if len(t.strip()) < 6 or t.count("@") > 2:
        return False
    return "?" in t or any(phrase in t for phrase in ASKING_PHRASES)


class CommentResponder:
    def __init__(
        self,
        settings: PipelineSettings,
        meta: MetaGraphPublisher,
        store: FormatsStore,
        cfg: Dict[str, Any],
        *,
        usage_sink: Optional[Callable[..., None]] = None,
        publisher: Optional[FormatsPublisher] = None,
        call: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    ) -> None:
        self.settings = settings
        self.meta = meta
        self.store = store
        self.cfg = cfg
        self.usage_sink = usage_sink
        self.publisher = publisher or FormatsPublisher(meta)
        self.call = call or self._gemini

    def mode(self, now: datetime) -> str:
        mode = str(self.cfg.get("mode", "auto"))
        if mode != "auto":
            return mode
        first = self.store.first_comment_at()
        if not first:
            return "shadow"
        since = datetime.fromisoformat(first)
        return "live" if now.astimezone(timezone.utc) - since >= timedelta(days=float(self.cfg.get("shadow_days", 3))) else "shadow"

    def run(self, now: datetime) -> Optional[Dict[str, Any]]:
        mode = self.mode(now)
        candidates = self._candidates(now)
        if not candidates:
            return None
        known = self.store.known_comments([c["id"] for c in candidates])
        fresh = [c for c in candidates if c["id"] not in known]
        questions, skipped = [], 0
        for c in fresh:
            if looks_like_question(c["text"]):
                questions.append(c)
            else:
                self.store.save_comment(c["id"], platform=c["platform"], media_id=c["media_id"], content_key=c["content_key"], text=c["text"], decision="skip", reason="no_es_pregunta", reply="", mode=mode)
                skipped += 1
        questions = questions[: int(self.cfg.get("max_per_cycle", 20))]
        decided = self._decide(questions) if questions else {}
        replied = 0
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
        sent_today = sum(1 for r in self.store.replies_since(day_start, "live") if r["reply_id"])
        for i, c in enumerate(questions):
            item = decided.get(i) or {}
            reply = str(item.get("respuesta") or "").strip()[:300] if item.get("responder") else ""
            reply_id = ""
            if reply and mode == "live" and sent_today < int(self.cfg.get("daily_cap", 15)):
                outcome = self.publisher.reply_comment(c["platform"], c["id"], reply)
                reply_id = outcome.media_id if outcome.status == "published" else ""
                sent_today += bool(reply_id)
                replied += bool(reply_id)
            self.store.save_comment(c["id"], platform=c["platform"], media_id=c["media_id"], content_key=c["content_key"], text=c["text"],
                                    decision="reply" if reply else "skip", reason=str(item.get("motivo") or ("sin_decision" if not item else ""))[:300],
                                    reply=reply, mode=mode, reply_id=reply_id)
        return {"mode": mode, "new": len(fresh), "questions": len(questions), "skipped": skipped, "replied": replied}

    def _candidates(self, now: datetime) -> List[Dict[str, Any]]:
        since = (now - timedelta(hours=float(self.cfg.get("lookback_hours", 24)))).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        excluded = list(self.cfg.get("exclude_groups") or ["paparazzi"])
        with self.store.connection() as conn:
            rows = conn.execute(
                f"""SELECT p.platform, p.platform_media_id, p.platform_post_id, p.permalink, p.published_at, i.content_key, i.title, i.summary, i.body_text, i.source_group
                    FROM publications p JOIN content_items i USING(content_key)
                    WHERE p.status = 'published' AND p.platform IN ('instagram', 'facebook') AND p.published_at >= ?
                      AND COALESCE(i.source_group, '') NOT IN ({','.join('?' * len(excluded))})""",
                [since, *excluded],
            ).fetchall()
        self._notes = {}
        out: List[Dict[str, Any]] = []
        own = {self.settings.ig_user_id}
        for r in rows:
            media = str(r["platform_media_id"] or r["platform_post_id"] or "")
            if not media or self.store.run_status(f"dead_media:{media}") == "done":
                continue  # post borrado o ilegible: no se vuelve a consultar
            try:
                comments = self.meta.fetch_publication_comments(r["platform"], media, permalink=r["permalink"] or "", published_at=r["published_at"] or "")
            except Exception as exc:
                if "does not exist" in str(exc) or "(#10)" in str(exc):
                    self.store.set_run(f"dead_media:{media}", "dead_media", "done", {"error": str(exc)[:200]})
                LOGGER.warning("comentarios de %s: %s", media, str(exc)[:160])
                continue
            self._notes[r["content_key"]] = {"titulo": r["title"], "texto": str(r["body_text"] or r["summary"] or "")[:1500]}
            for c in comments:
                if not c.get("id") or c.get("author_username") in own or str(c.get("author_username") or "").lower() == "duonoticiasok":
                    continue
                out.append({"id": c["id"], "platform": r["platform"], "media_id": media, "content_key": r["content_key"], "text": str(c.get("text") or "")})
        return out

    def _decide(self, questions: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        notes = {q["content_key"]: self._notes.get(q["content_key"], {}) for q in questions}
        prompt = (
            "Para cada comentario decidí si corresponde responder y escribí la respuesta. Devolvé JSON "
            '{"items":[{"i":indice,"responder":true|false,"motivo":"...","respuesta":"..."}]}\n\n'
            + json.dumps({"notas": notes, "comentarios": [{"i": i, "nota": q["content_key"], "texto": q["text"]} for i, q in enumerate(questions)]}, ensure_ascii=False)
        )
        try:
            data = self.call(SYSTEM, prompt)
        except Exception as exc:
            LOGGER.warning("respuestas a comentarios: %s", exc)
            return {}
        out: Dict[int, Dict[str, Any]] = {}
        for item in data.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("i"), int):
                out[item["i"]] = item
        return out

    def _gemini(self, system: str, prompt: str) -> Dict[str, Any]:
        started = time.monotonic()
        ok, error, usage = False, "", None
        try:
            data, usage = generate_json_with_usage(system, prompt, temperature=0.3, max_output_tokens=2500, config=self.settings.llm)
            ok = True
            return data
        except Exception as exc:
            error = str(exc)[:300]
            raise
        finally:
            if self.usage_sink:
                cost = None
                if usage:
                    cost = load_editorial_config(self.settings).estimated_cost_usd(usage.input_tokens or 0, usage.output_tokens or 0, usage.model)
                self.usage_sink(purpose="comment_replies", model=(usage.model if usage else self.settings.llm.model), items=1,
                                input_tokens=usage.input_tokens if usage else None, output_tokens=usage.output_tokens if usage else None,
                                latency_ms=int((time.monotonic() - started) * 1000), ok=ok, error=error, estimated_cost_usd=cost)
