"""Generate Instagram title + caption for X videos using OpenAI."""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from utils.http_client import HttpClient

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
OPENAI_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "300"))
CAPTION_EMOJI_POOL = ["🔥", "🚨", "😳", "👀", "🤯", "😱"]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def format_caption_paragraphs(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    text = re.sub(r"\.\s+(?=[A-ZÁÉÍÓÚÑÜ¿¡\?\!\(])", ".\n\n", text)
    return text.strip()


def _strip_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "", text or "").strip()


def _strip_emojis(text: str) -> str:
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F700-\U0001F77F"  # alchemical symbols
        "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
        "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
        "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
        "\U0001FA00-\U0001FA6F"  # Chess Symbols
        "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027B0"  # Dingbats
        "\U000024C2-\U0001F251"  # Enclosed characters
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _contains_emoji(text: str) -> bool:
    return _strip_emojis(text or "") != (text or "").strip()


def _pick_caption_emoji(seed_text: str) -> str:
    normalized = (seed_text or "").lower()
    keyword_map = {
        "robo": "🚨",
        "inseguridad": "🚨",
        "peligro": "🚨",
        "accidente": "😱",
        "moto": "😱",
        "gracioso": "😂",
        "japon": "😳",
        "perd": "😳",
        "viral": "🔥",
        "insolito": "🤯",
    }
    for keyword, emoji in keyword_map.items():
        if keyword in normalized:
            return emoji
    return CAPTION_EMOJI_POOL[hash(seed_text or "caption") % len(CAPTION_EMOJI_POOL)]


def _ensure_caption_emojis(caption: str, title: str) -> str:
    clean = format_caption_paragraphs(caption)
    if not clean:
        return clean
    if _contains_emoji(clean):
        return clean
    lead = _pick_caption_emoji(f"{title}|lead")
    tail = "👇"
    return format_caption_paragraphs(f"{lead} {clean} {tail}")


def _build_payload(user_prompt: str) -> Dict[str, Any]:
    return {
        "model": OPENAI_MODEL,
        "temperature": OPENAI_TEMPERATURE,
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Sos editor senior de reels virales para Duo Noticias. "
                            "Genera JSON con dos campos EXACTOS: titulo_instagram y texto_instagram.\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "TITULO_INSTAGRAM:\n"
                            "- SIN emojis\n"
                            "- maximo 10 palabras\n"
                            "- maximo 80 caracteres\n"
                            "- directo, fuerte, sin contexto innecesario\n"
                            "- estilo titular de impacto (no descriptivo, no neutro)\n"
                            "- debe generar curiosidad o tension\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "TEXTO_INSTAGRAM:\n"
                            "- entre 180 y 420 caracteres\n"
                            "- formato obligatorio:\n"
                            "1) PRIMERA LINEA: hook fuerte (max 12 palabras) -> debe generar sorpresa, indignacion o tension inmediata\n"
                            "2) DESARROLLO: -> contexto minimo (solo lo necesario) -> agregar un giro, contradiccion o dato que aumente tension\n"
                            "3) CIERRE: -> CTA NO generico -> debe invitar a opinar o reaccionar desde una emocion (enojo, incredulidad, debate)\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "REGLAS:\n"
                            "- usar entre 1 y 3 emojis (solo en texto, nunca en titulo)\n"
                            "- tono humano, picante, directo (como editor real, no IA)\n"
                            "- cero burocratico\n"
                            "- NO hashtags\n"
                            "- NO URLs\n"
                            "- NO frases genericas tipo 'no te lo pierdas'\n"
                            "- NO repetir estructuras tipo '¿que harias?'\n"
                            "- NO inventar datos\n"
                            "- respetar nombres propios\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "CRITERIO EDITORIAL (CLAVE):\n"
                            "Antes de escribir, elegi un angulo dominante:\n"
                            "- indignacion\n"
                            "- absurdo\n"
                            "- impotencia\n"
                            "- tension social\n"
                            "- peligro\n"
                            "Y construi todo el caption desde ese angulo. "
                            "Evitar repetir estructuras entre captions consecutivos. "
                            "Cada caption debe sentirse distinto en ritmo y enfoque."
                        ),
                    }
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


def _build_user_prompt(item: Dict[str, Any]) -> str:
    lines = [
        f"tweet_id: {item.get('tweet_id') or item.get('id') or ''}",
        f"author: {item.get('author') or item.get('uploader') or ''}",
        f"timestamp: {item.get('timestamp') or ''}",
        f"tweet_url: {item.get('tweet_url') or item.get('url') or ''}",
        "descripcion_original:",
        _clean_text(_strip_urls(item.get("original_text") or item.get("description") or "")),
    ]
    return "\n".join(lines)


def _fallback(item: Dict[str, Any]) -> Dict[str, str]:
    base = _clean_text(_strip_urls(item.get("original_text") or item.get("description") or "Video"))
    title = _strip_emojis(base)[:80] or "Video"
    caption = _ensure_caption_emojis(
        f"{title}. Lo que muestra el video ya esta haciendo ruido. ¿Vos como lo ves?",
        title,
    )
    return {"titulo_instagram": title, "texto_instagram": caption}


def generate_instagram_metadata(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    updated: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        try:
            prompt = _build_user_prompt(enriched)
            result = _call_openai(prompt)
            title = _strip_emojis(_clean_text(result.get("titulo_instagram") or ""))[:80]
            caption = _ensure_caption_emojis(
                result.get("texto_instagram") or "",
                title,
            )
            if not title:
                raise RuntimeError("titulo_instagram vacio")
            if not caption:
                raise RuntimeError("texto_instagram vacio")
        except Exception:
            fallback = _fallback(enriched)
            title = fallback["titulo_instagram"]
            caption = fallback["texto_instagram"]

        enriched["titulo_instagram"] = title
        enriched["texto_instagram"] = caption
        updated.append(enriched)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate IG title + caption for X videos")
    parser.add_argument("--input", required=True, help="Input JSON (results_*.json)")
    parser.add_argument("--output", help="Output JSON")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print("Input file not found")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        print("Input format not supported")
        return

    updated = generate_instagram_metadata(items)

    if args.dry_run:
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_path = Path(args.output) if args.output else DATA_DIR / f"x_videos_ai_{stamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
    print(f"Archivo guardado: {out_path}")


if __name__ == "__main__":
    main()
