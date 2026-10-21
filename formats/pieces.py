"""Arma las piezas de los formatos (datos para las plantillas board/story/weekly del
motor visual) y sus textos. Los textos salen de plantillas y de lo que la IA ya
genero para cada nota: ningun formato de este modulo llama a Gemini."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

from formatter.service import PLACEHOLDER_URL, is_placeholder_image
from utils.watermark import SOURCE_BRANDS, check_image

LOGGER = logging.getLogger("duo.formats.pieces")
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
NUMBER_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
SOURCE_NAMES = {
    "informatesalta": "Informate Salta", "eltribuno": "El Tribuno", "quepasasalta": "Qué Pasa Salta", "tn": "TN", "infobae": "Infobae",
    "paparazzi": "Paparazzi", "saltagob": "Gobierno de Salta", "policiasalta": "Policía de Salta", "x": "X",
}
ALERT_NAMES = {2: "amarilla", 3: "naranja", 4: "roja"}


def long_date(d: date) -> str:
    return f"{DAYS[d.weekday()]} {d.day} de {MONTHS[d.month - 1]}"


def short_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1][:3]}"


def money(value: Any) -> str:
    number = float(value or 0)
    text = f"{number:,.1f}" if number % 1 else f"{number:,.0f}"
    return "$" + text.replace(",", "X").replace(".", ",").replace("X", ".")


def _json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}") or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Notas publicadas -> datos de pieza
# ---------------------------------------------------------------------------


class NoteView:
    """Lo que los formatos necesitan de una nota ya publicada."""

    def __init__(self, row: Dict[str, Any], photo_dir: Path, ffmpeg: str = "ffmpeg") -> None:
        self.row = row
        self.key = str(row["content_key"])
        editorial = _json(row.get("editorial_json"))
        raw = editorial.get("raw_response") if isinstance(editorial.get("raw_response"), dict) else {}
        visual = raw.get("visual") if isinstance(raw.get("visual"), dict) else {}
        self.title = str(row.get("title") or "")
        self.headline = str(visual.get("titular_audiovisual") or raw.get("titulo") or self.title)
        self.category = str(visual.get("categoria") or "actualidad")
        self.location = str(visual.get("ubicacion") or "")
        self.urgent = bool(visual.get("urgente"))
        self.points = [str(p) for p in (raw.get("que_se_sabe") or []) if str(p).strip()][:3]
        self.hook = str(raw.get("gancho") or "")
        self.source = str(row.get("source") or "")
        self.source_name = SOURCE_NAMES.get(self.source, self.source.title())
        self.relevance = float(row.get("relevance_score") or 0)
        self.group = str(row.get("source_group") or "")
        self.event_key = str(row.get("event_key") or "") or self.key
        self.views = int(row.get("views") or 0)
        self.photo_dir = photo_dir
        self.ffmpeg = ffmpeg
        self._photo: Optional[str] = None

    @property
    def has_points(self) -> bool:
        return bool(self.points)

    def rendered_post(self) -> str:
        """La pieza ya publicada (post o portada del reel), para la historia de "nuevo post"."""
        formatted = _json(self.row.get("formatted_json"))
        meta = formatted.get("meta") if isinstance(formatted.get("meta"), dict) else {}
        cover = str(meta.get("cover_path") or "")
        if cover and Path(cover).exists():
            return cover
        for asset in formatted.get("assets") or []:
            path = str((asset or {}).get("path") or "")
            if (asset or {}).get("kind") == "image" and path and Path(path).exists():
                return path
        return ""

    def photo(self) -> str:
        """Foto limpia: cuadro del video verificado, o la primera foto sin marca de agua."""
        if self._photo is not None:
            return self._photo
        self._photo = self._video_frame() or self._clean_source_photo() or ""
        return self._photo

    def _video_frame(self) -> str:
        media = _json(self.row.get("media_json"))
        video = media.get("video") if isinstance(media.get("video"), dict) else {}
        path = str(video.get("path") or "")
        if not path or not Path(path).exists():
            return ""
        out = self.photo_dir / f"{self.key[:16]}_frame.jpg"
        if out.exists():
            return str(out)
        at = max(1.5, min(12.0, float(video.get("duration_seconds") or 10) * 0.2))
        try:
            subprocess.run([self.ffmpeg, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1", "-q:v", "2", str(out)], capture_output=True, timeout=60, check=True)
        except Exception as exc:
            LOGGER.warning("cuadro de video %s: %s", self.key, exc)
            return ""
        return str(out) if out.exists() else ""

    def _clean_source_photo(self) -> str:
        try:
            assets = json.loads(str(self.row.get("assets_json") or "[]"))
        except ValueError:
            assets = []
        brands = SOURCE_BRANDS.get(self.source, [])
        urls = [a.get("remote_url") for a in assets if isinstance(a, dict) and a.get("kind") == "image" and a.get("remote_url") and not PLACEHOLDER_URL.search(str(a.get("remote_url")))][:4]
        for n, url in enumerate(urls):
            target = self.photo_dir / f"{self.key[:16]}_{n}.jpg"
            try:
                if not target.exists():
                    response = httpx.get(url, timeout=25, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                    if response.status_code != 200:
                        continue
                    target.write_bytes(response.content)
                verdict = check_image(str(target), brands or ["eltribuno"])
                if verdict.status == "error":
                    target.unlink(missing_ok=True)
                    continue
                if is_placeholder_image(str(target)):
                    continue
                if brands and verdict.blocks:
                    LOGGER.info("foto %s descartada por marca de agua (%s)", self.key, verdict.reason)
                    continue
                return str(target)
            except Exception as exc:
                LOGGER.warning("foto %s: %s", self.key, exc)
        return ""


def pick_digest(notes: Sequence[NoteView], *, size: int = 5, per_category: int = 2, max_national: int = 2) -> List[NoteView]:
    """Las mas relevantes, un solo hecho por acontecimiento, tope por categoria y de
    notas no locales; si faltan, se completa con las mejores restantes."""
    ranked = sorted([n for n in notes if n.has_points], key=lambda n: -n.relevance) or sorted(notes, key=lambda n: -n.relevance)
    chosen: List[NoteView] = []
    events, per_cat, outside = set(), {}, 0
    for note in ranked:
        if note.event_key in events or per_cat.get(note.category, 0) >= per_category:
            continue
        if note.group != "local" and outside >= max_national:
            continue
        if not note.photo():
            continue
        chosen.append(note)
        events.add(note.event_key)
        per_cat[note.category] = per_cat.get(note.category, 0) + 1
        outside += note.group != "local"
        if len(chosen) == size:
            break
    for note in ranked:
        if len(chosen) == size:
            break
        if note.event_key not in events and note.photo():
            chosen.append(note)
            events.add(note.event_key)
    return sorted(chosen, key=lambda n: -n.relevance)


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------


def piece(pid: str, template: str, fmt: str, extra: Dict[str, Any], *, seconds: float = 5) -> Dict[str, Any]:
    """Pieza para el motor visual. Las rutas locales viajan en content.photos ("photo:N")."""
    photos: List[Dict[str, str]] = []

    def refs(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: refs(v) for k, v in value.items()}
        if isinstance(value, list):
            return [refs(v) for v in value]
        if isinstance(value, str) and value and (re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("/")) and Path(value).exists():
            photos.append({"src": value})
            return f"photo:{len(photos) - 1}"
        return value

    extra = refs(extra)
    return {
        "content": {
            "id": pid,
            "originalTitle": pid,
            "headline": pid,
            "date": datetime.now().astimezone().isoformat(),
            "source": {"name": "Dúo Noticias"},
            "photos": photos,
            "extra": extra,
        },
        "presentation": {"template": template, "format": fmt, "durationSeconds": seconds},
    }


def digest_pieces(notes: Sequence[NoteView], weather: Optional[Dict[str, Any]], dollar: Optional[List[Dict[str, Any]]], holidays: Optional[List[Dict[str, Any]]], today: date) -> List[Dict[str, Any]]:
    total = len(notes) + 2
    pieces = []
    cover: Dict[str, Any] = {"kind": "digest-cover", "dateLabel": long_date(today), "items": [{"headline": n.headline, "category": n.category} for n in notes]}
    if weather:
        day = weather["days"][0]
        cover["weather"] = {"temp": weather["now"]["temp"], "min": day["min"], "max": day["max"], "desc": day["desc"], "rain": day["rain"]}
    pieces.append(piece("digest-0", "board", "portrait", cover))
    for i, note in enumerate(notes, start=1):
        pieces.append(
            piece(
                f"digest-{i}",
                "board",
                "portrait",
                {"kind": "digest-item", "n": i, "slide": i + 1, "total": total, "headline": note.headline, "points": note.points, "category": note.category, "photo": note.photo(), "source": note.source_name},
            )
        )
    close: Dict[str, Any] = {"kind": "digest-close", "n": total, "total": total}
    quotes = {q["id"]: q for q in dollar or []}
    if "oficial" in quotes and "blue" in quotes:
        close["dollar"] = [{"name": "oficial", "sell": quotes["oficial"]["sell"]}, {"name": "blue", "sell": quotes["blue"]["sell"]}]
    if holidays:
        hd = date.fromisoformat(holidays[0]["fecha"])
        close["holiday"] = {"name": holidays[0]["nombre"], "dateLabel": long_date(hd).capitalize(), "daysLeft": (hd - today).days}
    pieces.append(piece(f"digest-{total - 1}", "board", "portrait", close))
    return pieces


def digest_caption(notes: Sequence[NoteView], weather: Optional[Dict[str, Any]], today: date) -> str:
    lines = [f"☀️ Lo que tenés que saber hoy, {long_date(today)} 👇", ""]
    for i, note in enumerate(notes):
        lines.append(f"{NUMBER_EMOJI[i]} {note.headline.replace('*', '')}")
    if weather:
        day = weather["days"][0]
        lines += ["", f"🌦️ Clima en Salta: {float(weather['now']['temp']):.0f}° ahora, mínima de {day['min']:.0f}° y máxima de {day['max']:.0f}°. {day['desc']} (SMN)."]
    lines += ["", "Deslizá para ver cada noticia ➡️", "", "#DuoNoticias #Salta"]
    return "\n".join(lines)


def weather_extra(weather: Dict[str, Any], today: date) -> Dict[str, Any]:
    days = []
    for i, d in enumerate(weather["days"][:4]):
        dd = date.fromisoformat(d["date"])
        days.append({"label": "Hoy" if i == 0 else DAYS[dd.weekday()][:3], "min": d["min"], "max": d["max"], "desc": d["desc"], "rain": d["rain"]})
    at = str(weather["now"].get("at") or "")
    try:
        time_label = datetime.fromisoformat(at).strftime("%H:%M")
    except ValueError:
        time_label = ""
    return {"kind": "weather", "now": {**weather["now"], "time": time_label}, "days": days, "alertLevel": weather["alert_levels"].get(today.isoformat(), 1)}


def weather_caption(weather: Dict[str, Any], today: date) -> str:
    level = weather["alert_levels"].get(today.isoformat(), 1)
    day = weather["days"][0]
    head = f"⚠️ Alerta {ALERT_NAMES[level]} del SMN para Salta" if level >= 2 else "🌦️ El tiempo en Salta"
    return (
        f"{head} 👇\n\n🌡️ Ahora: {float(weather['now']['temp']):.0f}°, {weather['now']['desc'].lower()}.\n"
        f"📈 Hoy: mínima de {day['min']:.0f}° y máxima de {day['max']:.0f}°, con {day['rain']}% de probabilidad de lluvia.\n\n"
        "Fuente: Servicio Meteorológico Nacional.\n\n#DuoNoticias #Salta #Clima"
    )


def dollar_extra(quotes: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    blue = next((q for q in quotes if q["id"] == "blue"), quotes[0])
    delta = float(blue["sell"] or 0) - float(blue.get("prev") or blue["sell"] or 0)
    verb = "sube" if delta > 0 else "baja" if delta < 0 else "se mantiene"
    return {
        "kind": "dollar",
        "title": f"El {blue['name'].lower()} {verb} a {money(blue['sell'])}",
        "quotes": [{"name": q["name"], "buy": q.get("buy"), "sell": q["sell"], "prev": q.get("prev")} for q in quotes],
        "updated": f"{short_date(now.date())} {now:%H:%M} h",
    }


def dollar_caption(quotes: List[Dict[str, Any]]) -> str:
    rows = "\n".join(f"💵 {q['name']}: {money(q['sell'])}" for q in quotes)
    blue = next((q for q in quotes if q["id"] == "blue"), None)
    head = "💰 Dólar hoy: así cotiza en Argentina"
    if blue and blue.get("prev"):
        delta = float(blue["sell"]) - float(blue["prev"])
        if delta:
            head = f"💰 Dólar hoy: el blue {'sube' if delta > 0 else 'baja'} {money(abs(delta))} y cotiza a {money(blue['sell'])}"
    return f"{head} 👇\n\n{rows}\n\nValores de venta. Fuente: DolarApi.\n\n#DuoNoticias #Dolar #Economia"


def holidays_extra(holidays: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    first = holidays[0]
    hd = date.fromisoformat(first["fecha"])
    more = []
    for h in holidays[1:4]:
        d = date.fromisoformat(h["fecha"])
        more.append({"name": h["nombre"], "dateLabel": f"{DAYS[d.weekday()][:3]} {short_date(d)}", "type": h.get("tipo", "")})
    return {"kind": "holidays", "next": {"name": first["nombre"], "dateLabel": long_date(hd).capitalize(), "daysLeft": (hd - today).days, "type": first.get("tipo", "")}, "more": more}


def holidays_caption(holidays: List[Dict[str, Any]], today: date) -> str:
    first = holidays[0]
    hd = date.fromisoformat(first["fecha"])
    days = (hd - today).days
    when = "mañana" if days == 1 else f"en {days} días"
    return f"📅 El próximo feriado es {when}: {long_date(hd)}, {first['nombre']} (feriado {first.get('tipo', '')}) 👇\n\n¿Ya tenés planes? 🙌\n\n#DuoNoticias #Feriado #Salta"


def services_extra(water: Optional[Dict[str, Any]], power: Optional[Dict[str, Any]], passes: Optional[List[Dict[str, Any]]], now: datetime) -> Dict[str, Any]:
    if water is None:
        water_box = {"ok": None, "text": "Aguas del Norte no informa hoy el estado del servicio."}
    elif water["cuts"]:
        water_box = {"ok": False, "text": "; ".join(f"{c['zone']}: {c['detail'][:140]}" for c in water["cuts"][:2])}
    else:
        water_box = {"ok": True, "text": f"Sin cortes programados: «{water['status']}»"}
    if power is None:
        power_box = {"ok": None, "text": "EDESA no publica hoy su listado de cortes programados. Reclamos: 0800 777 33372."}
    else:
        power_box = {"ok": False, "text": " ".join(power["lines"][:6])[:260]}
    return {
        "kind": "services",
        "dateLabel": f"{short_date(now.date())} · {now:%H:%M} h",
        "water": water_box,
        "power": power_box,
        "passes": [{"name": p["name"].replace(" - ", "–"), "country": p["country"], "state": p["state"]} for p in passes or []],
    }


def services_caption(extra: Dict[str, Any]) -> str:
    lines = ["🔎 Servicios en Salta hoy: agua, luz y pasos fronterizos 👇", "", f"🚰 Agua: {extra['water']['text']}", f"💡 Luz: {extra['power']['text']}"]
    closed = [p["name"] for p in extra["passes"] if p["state"] != "ABIERTO"]
    lines.append("🛣️ Pasos: " + (f"cerrados {', '.join(closed)}; el resto, habilitados." if closed else "todos habilitados."))
    lines += ["", "Fuentes: Aguas del Norte, EDESA y Ministerio de Seguridad.", "", "#DuoNoticias #Salta"]
    return "\n".join(lines)


def story_post(note: NoteView) -> Optional[Dict[str, Any]]:
    image = note.rendered_post()
    if not image:
        return None
    return piece(f"story-post-{note.key[:8]}", "story", "reel", {"kind": "story-post", "image": image, "headline": note.headline})


def story_breaking(note: NoteView, published_at: datetime) -> Optional[Dict[str, Any]]:
    photo = note.photo()
    if not photo:
        return None
    return piece(
        f"story-breaking-{note.key[:8]}",
        "story",
        "reel",
        {"kind": "story-breaking", "headline": note.headline, "photo": photo, "location": note.location, "time": f"{published_at:%H:%M} h · {note.source_name}"},
    )


def story_recap(notes: Sequence[NoteView], today: date) -> Dict[str, Any]:
    return piece(
        "story-recap",
        "story",
        "reel",
        {"kind": "story-recap", "dateLabel": long_date(today), "items": [{"headline": n.headline, "photo": n.photo(), "views": n.views, "category": n.category} for n in notes]},
    )


def story_update(note: NoteView, headline: str, before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    extra: Dict[str, Any] = {"kind": "story-update", "headline": headline, "photo": note.photo()}
    if before and after:
        extra.update({"before": before, "after": after})
    else:
        extra["timeLabel"] = (after or {}).get("time", "")
    return piece(f"story-update-{note.key[:8]}", "story", "reel", extra)


def weekly_piece(notes: Sequence[NoteView], start: date, end: date) -> Dict[str, Any]:
    seconds = round(2.2 + 4 * len(notes) + 2.1, 1)
    items = []
    for note in notes:
        published = str(note.row.get("published_at") or "")
        try:
            label = short_date(datetime.fromisoformat(published).astimezone().date())
        except ValueError:
            label = ""
        items.append({"headline": note.headline, "photo": note.photo(), "views": note.views, "category": note.category, "dateLabel": label})
    built = piece("weekly", "weekly", "reel", {"rangeLabel": f"{short_date(start)} al {short_date(end)}", "items": items}, seconds=seconds)
    built["content"]["headline"] = "Top 5 de la semana"
    return built


def weekly_caption(notes: Sequence[NoteView]) -> str:
    lines = ["🔥 Las 5 noticias más vistas de la semana en Dúo 👇", ""]
    for i, note in enumerate(notes):
        lines.append(f"{NUMBER_EMOJI[i]} {note.headline.replace('*', '')}")
    lines += ["", "💬 ¿Cuál te sorprendió más? Te leemos.", "", "#DuoNoticias #Salta"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cifras de una actualizacion (antes -> ahora)
# ---------------------------------------------------------------------------

WORD_NUMBERS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
                "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "cien": 100}
FIGURE_NOUNS = {
    "muertos": "muertos", "fallecidos": "muertos", "victimas fatales": "muertos", "víctimas fatales": "muertos",
    "heridos": "heridos", "lesionados": "heridos", "evacuados": "evacuados", "detenidos": "detenidos", "desaparecidos": "desaparecidos",
}
_FIGURE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*|" + "|".join(WORD_NUMBERS) + r")\s+(?:\w+\s+){0,2}?(" + "|".join(re.escape(k) for k in FIGURE_NOUNS) + r")\b", re.I)


def figures(text: str) -> Dict[str, int]:
    """Cifras de impacto ("cuatro muertos", "400 evacuados") -> {"muertos": 4, ...} (maximo de cada una)."""
    found: Dict[str, int] = {}
    for raw, noun in _FIGURE_RE.findall(text or ""):
        value = WORD_NUMBERS.get(raw.lower()) if raw.lower() in WORD_NUMBERS else int(raw.replace(".", ""))
        key = FIGURE_NOUNS[noun.lower()]
        found[key] = max(found.get(key, 0), int(value or 0))
    return found


def figure_change(old_text: str, new_text: str) -> Optional[Dict[str, Any]]:
    """La cifra que cambio entre la version publicada y la actualizacion."""
    old, new = figures(old_text), figures(new_text)
    for key in ("muertos", "heridos", "desaparecidos", "evacuados", "detenidos"):
        if key in old and key in new and old[key] != new[key]:
            return {"noun": key, "before": old[key], "after": new[key]}
    return None
