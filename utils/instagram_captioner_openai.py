"""Generate Instagram captions + editorial decisions using OpenAI Responses API."""
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
from utils.editorial_agent import BASE_PROMPT, build_user_prompt
DATA_DIR = BASE_DIR / "data"


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
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/responses")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.6"))
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "500"))

CAPTION_LIMIT = int(os.getenv("IG_CAPTION_LIMIT", "2200"))


def _latest_news_file() -> Optional[Path]:
    files = list(DATA_DIR.glob("nuevas_noticias_paparazzi*.json"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _clean_text(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return text


def _strip_emojis(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[\U00010000-\U0010ffff]", "", value).strip()


def _truncate_caption(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    trimmed = text[: max(0, limit - 1)].rstrip()
    trimmed = trimmed.rsplit(" ", 1)[0].strip() or trimmed
    return f"{trimmed}…"


def _fallback_caption(noticia: Dict[str, Any]) -> str:
    titulo = _clean_text(noticia.get("titulo", ""))
    extracto = _clean_text(noticia.get("extracto", ""))
    if titulo and extracto:
        text = f"{titulo}\n\n{extracto}"
    elif titulo:
        text = titulo
    else:
        text = "Noticia completa en Paparazzi"
    return _truncate_caption(text, CAPTION_LIMIT)


def _build_payload(user_prompt: str) -> Dict[str, Any]:
    return {
        "model": OPENAI_MODEL,
        "temperature": OPENAI_TEMPERATURE,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": BASE_PROMPT},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                ],
            },
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


def _call_openai(user_prompt: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY")
    payload = _build_payload(user_prompt)
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


def _generate_editorial(noticia: Dict[str, Any], recent_titles: List[str], dedup_hint: str) -> Dict[str, Any]:
    user_prompt = build_user_prompt(noticia, recent_titles, dedup_hint)
    try:
        result = _call_openai(user_prompt)
    except Exception:
        caption = _fallback_caption(noticia)
        return {
            "decision": "publicar",
            "motivo": "fallback",
            "tono": "informativo",
            "caption": caption,
            "cta": "Que opinas?",
            "resumen": caption.split("\n", 1)[0],
        }

    caption = result.get("caption") or _fallback_caption(noticia)
    caption = _strip_emojis(caption)
    caption = _truncate_caption(caption, CAPTION_LIMIT)
    result["caption"] = caption
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Instagram captions with OpenAI.")
    parser.add_argument("--input", "--file", dest="input_file", help="Input noticias JSON file")
    parser.add_argument("--output", dest="output_file", help="Output JSON file")
    parser.add_argument("--max", type=int, default=None, help="Max items to process")
    parser.add_argument("--force", action="store_true", help="Overwrite existing texto_instagram")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output")
    args = parser.parse_args()

    data_file = Path(args.input_file) if args.input_file else _latest_news_file()
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
            item["texto_instagram"] = item.get("texto_instagram") or _fallback_caption(item)
            updated.append(item)
            processed += 1
            continue

        try:
            recent_titles = store.recent_titles(limit=8)
            dedup_hint = f"score={dedup.score:.2f}, reason={dedup.reason}"
            editorial = _generate_editorial(item, recent_titles, dedup_hint)
            item["decision"] = editorial.get("decision", "publicar")
            item["decision_reason"] = editorial.get("motivo", "")
            item["tono"] = editorial.get("tono", "informativo")
            item["texto_instagram"] = editorial.get("caption") or _fallback_caption(item)
            item["cta"] = editorial.get("cta")
            item["resumen"] = editorial.get("resumen")
            processed += 1
            if item.get("decision") == "publicar":
                to_ingest.append(item)
                to_ingest_vectors.append(vec[0])
        except Exception as exc:
            failed += 1
            item["texto_instagram"] = item.get("texto_instagram") or _fallback_caption(item)
            item["decision"] = "publicar"
            item["decision_reason"] = f"fallback: {exc}"
        updated.append(item)
        if args.max and processed >= args.max:
            break

    if to_ingest_vectors:
        ingest_items(store, to_ingest, np.array(to_ingest_vectors, dtype="float32"))

    print(f"Procesadas: {processed}, Saltadas: {skipped}, Fallidas: {failed}")

    if args.dry_run:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = Path(args.output_file) if args.output_file else DATA_DIR / f"nuevas_noticias_paparazzi_ai_{timestamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    print(f"Archivo guardado: {out_path}")


if __name__ == "__main__":
    main()
