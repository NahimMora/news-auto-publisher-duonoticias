from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher


def normalize_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip().lower()
    return re.sub(r"[^a-z0-9@#? ]+", "", cleaned)


def classify_hook_type(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return "directo"
    if "?" in (value or ""):
        return "pregunta"
    if any(token in text for token in ("alerta", "urgente", "ultimo momento", "escandalo")):
        return "alerta"
    if any(token in text for token in ("nadie esperaba", "no lo vio venir", "inesperado", "sorpresa")):
        return "shock"
    if any(token in text for token in ("dijo", "disparo", "sentencio", "respondio")):
        return "declaracion"
    if any(token in text for token in ("vs", "contra", "cruce", "pelea", "furia")):
        return "conflicto"
    return "directo"


def classify_tone(hook: str, caption: str = "", style: str = "") -> str:
    text = " ".join(part for part in (hook, caption, style) if part).lower()
    if any(token in text for token in ("bronca", "indign", "escandalo", "furia")):
        return "indignado"
    if any(token in text for token in ("te parece", "que opinas", "de que lado")):
        return "debate"
    if any(token in text for token in ("impacto", "emocion", "dram", "conmoc")):
        return "emocional"
    if any(token in text for token in ("dato", "confirmado", "explica", "contexto")):
        return "informativo"
    return "confrontativo"


def caption_length_bucket(caption: str) -> str:
    words = [word for word in re.split(r"\s+", caption or "") if word]
    length = len(words)
    if length < 35:
        return "corta"
    if length <= 80:
        return "media"
    return "larga"


def text_signature(*parts: str) -> str:
    payload = " | ".join(normalize_text(part) for part in parts if part).strip()
    if not payload:
        return ""
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=normalize_text(left), b=normalize_text(right)).ratio()
