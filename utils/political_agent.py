"""Agente politico para Noticias Argentinas (decide y genera textos IG)."""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.http_client import HttpClient
from utils.dedup import EmbeddingClient, DedupStore, build_text_for_embedding, check_duplicate, ingest_items

DATA_DIR = BASE_DIR / "data"
IDELOGY_PATH = Path(os.getenv("POLITICAL_IDEOLOGY_PATH", str(BASE_DIR / "ideologia_politica.md")))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("POLITICAL_OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
OPENAI_TEMPERATURE = float(os.getenv("POLITICAL_OPENAI_TEMPERATURE", "0.5"))
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("POLITICAL_OPENAI_MAX_OUTPUT_TOKENS", "600"))

CAPTION_LIMIT = int(os.getenv("IG_CAPTION_LIMIT", "2200"))


def _clean_text(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _strip_partisan(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"el gobierno que .*?no va a permitir.*?(?:\.\s|$)",
        r"es hora de .*?(?:\.\s|$)",
        r"apoyar a .*?(?:\.\s|$)",
        r"modelo empobrecedor",
        r"menos estado",
        r"m?s libertad",
        r"baja impuestos",
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _strip_hashtags(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_urls(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"https?://\S+", "", text).strip()




def _strip_lla_hashtags(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"#(LaLibertadAvanza|VivaLaLibertadCarajo|MileiPresidente|FinDelKirchnerismo)", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def _strip_political_sentences(text: str) -> str:
    if not text:
        return ""
    terms = [
        "gobierno", "kirchner", "oposicion", "partido", "milit", "campa?a",
        "impuestos", "estado", "libertad", "corrupcion", "modelo",
    ]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for s in sentences:
        lower = s.lower()
        if any(t in lower for t in terms):
            continue
        kept.append(s)
    return " ".join(kept).strip()


def _hashtags_from_title(title: str, max_tags: int = 5) -> str:
    if not title:
        return ""
    stop = {
        "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
        "en", "del", "al", "por", "para", "con", "sin", "a", "que", "se", "su",
        "sus", "es", "fue", "son", "tras", "ante", "sobre", "entre",
    }
    words = re.findall(r"[A-Za-z????????????]+", title)
    tags = []
    for w in words:
        lw = w.lower()
        if lw in stop or len(lw) <= 3:
            continue
        tag = "#" + re.sub(r"[^A-Za-z????????????0-9]", "", w.title())
        if tag not in tags:
            tags.append(tag)
        if len(tags) >= max_tags:
            break
    return " ".join(tags)

def _strip_emojis(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"[\U00010000-\U0010ffff]", "", text).strip()


def _tone_down(text: str) -> str:
    if not text:
        return ""
    # Remove excessive uppercase and slogans
    text = re.sub(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b", lambda m: m.group(0).capitalize(), text)
    text = text.replace("¡VIVA LA LIBERTAD CARAJO!", "")
    text = text.replace("VIVA LA LIBERTAD CARAJO", "")
    text = text.replace("BASTA", "")
    text = text.replace("ALTO ALERTA", "")
    text = text.replace("SE LES VIENE LA NOCHE", "")
    return re.sub(r"\s+", " ", text).strip()


def _truncate_caption(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    trimmed = text[: max(0, limit - 1)].rstrip()
    trimmed = trimmed.rsplit(" ", 1)[0].strip() or trimmed
    return f"{trimmed}..."


def _extract_hashtags(text: str) -> List[str]:
    tags = re.findall(r"#[A-Za-z0-9_]+", text or "")
    seen = set()
    result = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _clean_hashtags(tags: List[str]) -> List[str]:
    cleaned: List[str] = []
    for tag in tags:
        word = tag.lstrip("#")
        if len(word) < 4:
            continue
        if re.fullmatch(r"\d+", word):
            continue
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def _ensure_hashtags_last(text: str) -> str:
    if not text:
        return ""
    tags = _extract_hashtags(text)
    if not tags:
        return text.strip()
    cleaned = re.sub(r"#\w+", "", text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return "\n".join(lines + [" ".join(tags)]).strip()


def _split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _format_caption(text: str, *, title: str, mention_milei: bool, sensitive: bool) -> str:
    if not text:
        text = ""
    body = re.sub(r"#\w+", "", text).strip()
    lines = _split_sentences(body)
    lines = [ln for ln in lines if re.sub(r"[\W_]+", "", ln)]

    # Ensure CTA as last content line
    cta = None
    for i in range(len(lines) - 1, -1, -1):
        if "?" in lines[i]:
            cta = lines.pop(i)
            break
    if not cta:
        cta = "¿Cómo lo ves?"

    # Limit number of body lines to keep it short
    if len(lines) > 5:
        head = lines[:4]
        tail = " ".join(lines[4:])
        lines = head + [tail]

    # Ensure 1-2 emojis per paragraph/line
    def pick_emoji(line: str) -> str:
        lower = line.lower()
        if any(k in lower for k in ("tormenta", "granizo", "lluv", "clima")):
            return "⛈️"
        if any(k in lower for k in ("senado", "congreso", "reforma", "ley", "proyecto")):
            return "🏛️"
        if any(k in lower for k in ("seguridad", "polic", "robo", "crimen", "violencia")):
            return "🚨"
        if any(k in lower for k in ("econom", "inflacion", "impuestos", "mercado")):
            return "📉"
        return "📰"

    def has_emoji(line: str) -> bool:
        return bool(re.search(r"[\U00010000-\U0010ffff]", line))

    new_lines = []
    for line in lines:
        if not has_emoji(line):
            line = f"{pick_emoji(line)} {line}"
        new_lines.append(line)
    lines = new_lines

    tags = _clean_hashtags(_extract_hashtags(text))
    if not mention_milei:
        tags = [t for t in tags if t.lower() not in ("#lalibertadavanza", "#mileipresidente")]
    if not tags:
        tags_line = _hashtags_from_title(title, max_tags=5)
        tags = _clean_hashtags(tags_line.split()) if tags_line else []
    if mention_milei and not sensitive:
        for tag in ("#LaLibertadAvanza", "#MileiPresidente"):
            if tag not in tags and len(tags) < 6:
                tags.append(tag)

    formatted = "\n\n".join([ln for ln in lines if ln])
    if not has_emoji(cta):
        cta = f"❓ {cta}"
    if formatted:
        formatted = f"{formatted}\n\n{cta}"
    else:
        formatted = cta
    if tags:
        formatted = f"{formatted}\n\n{' '.join(tags)}"
    return formatted.strip()


def _load_ideology() -> str:
    try:
        return IDELOGY_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def _build_system_prompt(ideology_text: str) -> str:
    return (
        "Sos redactor argentino para Instagram. Segui la linea editorial con moderacion y sin militancia.\n\n"
        f"{ideology_text}\n\n"
        "Salida obligatoria: JSON valido con las claves: decision, decision_reason, titulo_instagram, texto_instagram.\n"
        "decision: 'publicar' o 'descartar'. Usar 'descartar' SOLO si no hay informacion verificable.\n"
        "titulo_instagram: incluir 1-2 emojis relevantes, sin URLs, max 90 caracteres, claro y atractivo.\n"
        "texto_instagram: 4-7 lineas cortas, facil de leer, sin URLs, sin @menciones.\n"
        "Inclui datos clave (quien, que, donde, cuando) sin perder detalles.\n"
        "Usa emojis moderados (1-3) para enfatizar, sin excesos.\n"
        "Ultima linea: CTA con pregunta breve.\n"
        "Linea final: hashtags (3-6) relacionados a la noticia.\n"
        "Si menciona explicitamente a Javier Milei: tono positivo y celebratorio sin slogans, sin ataques a otros.\n"
        "Si NO menciona a Javier Milei: tono informativo neutral, sin militancia ni consignas.\n"
        "Noticias sensibles (crimen, muerte, violencia, abuso): tono respetuoso y estrictamente informativo.\n"
        "Hashtags: si menciona a Milei, incluir 1-2 tags LLA. Si no, solo tags tematicos.\n"
        "No inventes datos. No agregues nombres no presentes. No uses mayusculas excesivas."
    )



def _build_user_prompt(noticia: Dict[str, Any]) -> str:
    titulo = noticia.get("titulo", "")
    extracto = noticia.get("extracto", "")
    parrafos = noticia.get("parrafos", [])
    body = "\n".join([p for p in parrafos[:4] if isinstance(p, str)])
    return (
        "NOTICIA\n"
        f"Titulo: {titulo}\n"
        f"Extracto: {extracto}\n"
        f"Parrafos: {body}\n"
        f"URL: {noticia.get('url', '')}\n"
    )


def _build_payload(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    return {
        "model": OPENAI_MODEL,
        "temperature": OPENAI_TEMPERATURE,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
    }


def _extract_output_text(payload: Dict[str, Any]) -> str:
    text = (payload.get("output_text") or "").strip()
    if text:
        return text
    outputs = payload.get("output") or []
    chunks: List[str] = []
    for item in outputs:
        content = item.get("content") or []
        for block in content:
            if block.get("type") == "output_text" and block.get("text"):
                chunks.append(block["text"])
    return "\n".join(chunks).strip()


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _call_openai(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")
    payload = _build_payload(system_prompt, user_prompt)
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    client = HttpClient(headers=headers, timeout=60, retries=3, backoff_base=2, backoff_max=20)
    try:
        resp = client.post(OPENAI_BASE_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
    finally:
        client.close()
    text = _extract_output_text(data)
    parsed = _parse_json(text)
    if not parsed:
        raise RuntimeError("Respuesta IA invalida")
    return parsed


def _mentions_milei(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return "milei" in lower or "javier milei" in lower


def _is_sensitive(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    keywords = [
        "asesinado", "asesinato", "homicidio", "muerto", "murio", "muerte",
        "tiroteo", "disparo", "balazo", "robo", "asalto", "violencia",
        "secuestr", "violacion", "abuso", "femicidio", "crimen",
    ]
    return any(k in lower for k in keywords)


def _fallback_generate(noticia: Dict[str, Any], ideology_text: str) -> Dict[str, Any]:
    titulo = _strip_emojis(_strip_urls(_clean_text(noticia.get("titulo", ""))))
    extracto = _strip_urls(_clean_text(noticia.get("extracto", "")))
    parrafos = noticia.get("parrafos", [])
    resumen = extracto or (parrafos[0] if parrafos else "")
    text_blob = f"{titulo} {extracto} {' '.join(parrafos)}".strip()

    if not titulo and not resumen:
        return {
            "decision": "descartar",
            "decision_reason": "Sin contenido suficiente",
            "titulo_instagram": "",
            "texto_instagram": "",
        }
    titulo_instagram = titulo[:90]
    hashtags = _hashtags_from_title(titulo, max_tags=5)
    mention_milei = _mentions_milei(text_blob)
    sensitive = _is_sensitive(text_blob)
    lines = []
    if resumen:
        lines.append(f"📰 {resumen}")
    if len(parrafos) > 1:
        extra = _clean_text(parrafos[1])
        if extra and extra not in resumen:
            lines.append(f"📍 {extra[:200].rstrip()}")
    if mention_milei and not sensitive:
        lines.append("✅ La nota menciona acciones del Gobierno de Milei.")
    lines.append("¿Cómo lo ves?")
    if mention_milei and not sensitive:
        lla = "#LaLibertadAvanza #MileiPresidente"
        tag_line = (hashtags + " " + lla).strip()
    else:
        tag_line = hashtags
    if tag_line:
        lines.append(tag_line)
    texto_instagram = "\n".join(lines).strip()

    return {
        "decision": "publicar",
        "decision_reason": "fallback",
        "titulo_instagram": titulo_instagram,
        "texto_instagram": _truncate_caption(texto_instagram, CAPTION_LIMIT),
    }


def _normalize_output(result: Dict[str, Any], *, mention_milei: bool, sensitive: bool) -> Dict[str, Any]:
    decision = (result.get("decision") or "").strip().lower()
    if decision not in ("publicar", "descartar"):
        decision = "descartar" if "descart" in decision else "publicar"
    was_descartar = decision == "descartar"
    titulo = _strip_urls(_clean_text(result.get("titulo_instagram", "")))
    texto = _strip_urls(result.get("texto_instagram", "") or "")
    texto = re.sub(r"@\w+", "", texto).strip()
    titulo = _tone_down(titulo)
    texto = _tone_down(texto)
    if sensitive:
        texto = _strip_partisan(texto)
        texto = _strip_lla_hashtags(texto)
    if not mention_milei:
        texto = _strip_partisan(texto)
        texto = _strip_lla_hashtags(texto)

    texto = _format_caption(texto, title=titulo, mention_milei=mention_milei, sensitive=sensitive)
    texto = _truncate_caption(texto.strip(), CAPTION_LIMIT)

    if decision == "descartar":
        if titulo or texto:
            decision = "publicar"
        else:
            titulo = ""
            texto = ""

    if was_descartar and decision == "publicar":
        decision_reason = "override: contenido válido"
    else:
        decision_reason = result.get("decision_reason") or result.get("motivo") or ""

    return {
        "decision": decision,
        "decision_reason": decision_reason,
        "titulo_instagram": titulo[:90],
        "texto_instagram": texto,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente politico para Noticias Argentinas")
    parser.add_argument("--input", "--file", dest="input_file", help="Input noticias JSON")
    parser.add_argument("--output", dest="output_file", help="Output JSON")
    parser.add_argument("--max", type=int, default=None, help="Max items")
    parser.add_argument("--force", action="store_true", help="Sobrescribir texto_instagram existente")
    parser.add_argument("--dry-run", action="store_true", help="No escribir output")
    args = parser.parse_args()

    data_file = Path(args.input_file) if args.input_file else None
    if not data_file:
        files = list(DATA_DIR.glob("nuevas_noticias_noticiasargentinas*.json"))
        if files:
            data_file = max(files, key=lambda p: p.stat().st_mtime)
    if not data_file or not data_file.exists():
        print("No news file found in data/")
        return

    with open(data_file, "r", encoding="utf-8") as f:
        items = json.load(f)

    if isinstance(items, dict):
        items = items.get("items") or items.get("noticias") or []

    if not isinstance(items, list):
        print("Input format not supported.")
        return

    ideology_text = _load_ideology()
    system_prompt = _build_system_prompt(ideology_text)

    embedding_client = EmbeddingClient()
    texts = [build_text_for_embedding(item) for item in items]
    vectors = embedding_client.embed(texts)
    dim = vectors.shape[1] if vectors.ndim == 2 else 0

    store = DedupStore.load(dim=dim or 1536)
    if store.index.d != dim and store.index.ntotal > 0:
        print("[WARN] Dimensiones de embeddings cambiaron, reiniciando indice.")
        store = DedupStore(dim=dim or 1536)

    updated: List[Dict[str, Any]] = []
    processed = 0
    skipped = 0
    failed = 0
    to_ingest = []
    to_ingest_vectors = []

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if item.get("texto_instagram") and not args.force:
            updated.append(item)
            skipped += 1
            continue

        vec = vectors[idx: idx + 1]
        dedup = check_duplicate(store, vec)
        item["dedup_status"] = dedup.decision
        item["dedup_score"] = round(dedup.score, 4)
        item["dedup_reason"] = dedup.reason
        if dedup.match:
            item["dedup_match"] = {"titulo": dedup.match.get("titulo"), "url": dedup.match.get("url")}

        if dedup.decision == "descartar":
            item["decision"] = "descartar"
            item["decision_reason"] = dedup.reason
            item["titulo_instagram"] = ""
            item["texto_instagram"] = ""
            updated.append(item)
            processed += 1
            continue

        try:
            user_prompt = _build_user_prompt(item)
            result = _call_openai(system_prompt, user_prompt)
            text_blob = f"{item.get('titulo','')} {item.get('extracto','')} {' '.join(item.get('parrafos', []) if isinstance(item.get('parrafos', []), list) else [])}"
            mention_milei = _mentions_milei(text_blob)
            sensitive = _is_sensitive(text_blob)
            normalized = _normalize_output(result, mention_milei=mention_milei, sensitive=sensitive)
        except Exception as exc:
            failed += 1
            normalized = _fallback_generate(item, ideology_text)
            normalized["decision_reason"] = f"fallback: {exc}"

        if normalized.get("decision") == "descartar":
            has_content = bool(item.get("titulo") or item.get("extracto") or item.get("parrafos"))
            if has_content and item.get("dedup_status") != "descartar":
                normalized = _fallback_generate(item, ideology_text)
                normalized["decision_reason"] = "override: contenido válido"

        if normalized.get("decision") == "publicar":
            if not normalized.get("titulo_instagram"):
                normalized["titulo_instagram"] = _strip_emojis(_strip_urls(_clean_text(item.get("titulo", ""))))[:90]
            if not normalized.get("texto_instagram"):
                normalized = _fallback_generate(item, ideology_text)
                normalized["decision_reason"] = (normalized.get("decision_reason") or "").strip() or "fallback"

        item.update(normalized)
        if item.get("decision") == "publicar":
            to_ingest.append(item)
            to_ingest_vectors.append(vec[0])
        updated.append(item)
        processed += 1
        if args.max and processed >= args.max:
            break

    if to_ingest_vectors:
        ingest_items(store, to_ingest, np.array(to_ingest_vectors, dtype="float32"))

    print(f"Procesadas: {processed}, Saltadas: {skipped}, Fallidas: {failed}")

    if args.dry_run:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = Path(args.output_file) if args.output_file else DATA_DIR / f"nuevas_noticias_noticiasargentinas_ai_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    print(f"Archivo guardado: {out_path}")


if __name__ == "__main__":
    main()

