"""Arma las piezas de los formatos (datos para las plantillas board/story/weekly del
motor visual) y sus textos. Los textos salen de plantillas y de lo que la IA ya
genero para cada nota: ningun formato de este modulo llama a Gemini."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date, datetime, timedelta
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
    "defrentesalta": "De Frente Salta", "saltanews": "SaltaNews", "gendarmeria": "Gendarmería Nacional", "amtsalta": "AMT Salta",
}
ALERT_NAMES = {2: "amarilla", 3: "naranja", 4: "roja"}


def parse_ts(raw: Any) -> Optional[datetime]:
    """ISO de la base (con "Z" o fracciones de 1-6 digitos, que fromisoformat de 3.10 rechaza)."""
    text = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), str(raw or "").replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


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


def one_per_event(notes: Sequence[NoteView]) -> List[NoteView]:
    """Primera nota de cada acontecimiento (``event_key``), respetando el orden recibido (por vistas en
    el resumen de las 20). Notas sin acontecimiento cuentan cada una por separado."""
    seen: set = set()
    kept: List[NoteView] = []
    for note in notes:
        key = str(note.row.get("event_key") or "")
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(note)
    return kept


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
    # El SMN manda "23-octubre-2026 08:00"; Open-Meteo, ISO con zona. En ambos la hora es el primer HH:MM.
    found = re.search(r"(?<![\d:])(\d{1,2}:\d{2})", str(weather["now"].get("at") or ""))
    time_label = found.group(1) if found else ""
    level = weather["alert_levels"].get(today.isoformat(), 1)
    return {"kind": "weather", "dateLabel": long_date(today), "now": {**weather["now"], "time": time_label}, "days": days, "alertLevel": level, "tip": weather_tip(days[0] if days else None, level)}


def weather_tip(day: Optional[Dict[str, Any]], level: int) -> str:
    """Consejo fijo segun el pronostico del dia (sin IA); con alerta manda el aviso del SMN."""
    if not day or level >= 2:
        return ""
    lo, hi, rain = float(day["min"]), float(day["max"]), int(day["rain"] or 0)
    if rain >= 60:
        return "Llevá paraguas: hay muchas chances de lluvia."
    if hi >= 34:
        return "Calor fuerte: hidratate y evitá el sol del mediodía."
    if hi - lo >= 14:
        return "Mucha amplitud térmica: abrigo a la mañana y ropa liviana a la tarde."
    if lo <= 5:
        return "Mañana muy fría: salí abrigado."
    return ""


def weather_caption(weather: Dict[str, Any], today: date) -> str:
    level = weather["alert_levels"].get(today.isoformat(), 1)
    day = weather["days"][0]
    head = f"⚠️ Alerta {ALERT_NAMES[level]} del SMN para Salta" if level >= 2 else "🌦️ El tiempo en Salta"
    return (
        f"{head} 👇\n\n🌡️ Ahora: {float(weather['now']['temp']):.0f}°, {weather['now']['desc'].lower()}.\n"
        f"📈 Hoy: mínima de {day['min']:.0f}° y máxima de {day['max']:.0f}°, con {day['rain']}% de probabilidad de lluvia.\n\n"
        "Fuente: Servicio Meteorológico Nacional.\n\n#DuoNoticias #Salta #Clima"
    )


# Fondo de foto fija por tipo de placa (aprobado 2026-10-23: C1p, A1p, P1p, D1p). Las fotos viven en
# motion/public/bg; son de Wikimedia Commons y la del Paso de Jama (CC BY 3.0) exige el credito.
BG_PHOTOS = {
    "luz": {"photo": "bg/luz.jpg", "credit": "FOTO: WIKIMEDIA COMMONS (CC0)"},
    "agua": {"photo": "bg/agua.jpg", "credit": "FOTO: WIKIMEDIA COMMONS (CC0)"},
    "paso": {"photo": "bg/paso.jpg", "credit": "FOTO: PANORAMIO / WIKIMEDIA COMMONS (CC BY 3.0)"},
    "dolar": {"photo": "bg/dolar.jpg", "credit": "FOTO: WIKIMEDIA COMMONS (DOMINIO PÚBLICO)"},
}


def bg(theme: str) -> Dict[str, Any]:
    return {"mode": "photo", "theme": theme, **BG_PHOTOS[theme]}


def dollar_extra(quotes: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Tablero "¿A cuanto esta el dolar?": oficial y blue en grande, brecha y el resto en tarjetas."""
    oficial = next((q for q in quotes if q["id"] == "oficial"), None)
    blue = next((q for q in quotes if q["id"] == "blue"), None)
    stamps = [parse_ts(q.get("updated")) for q in quotes]
    stamps = [s for s in stamps if s and s.tzinfo]
    updated = max(stamps).astimezone(now.tzinfo) if stamps and now.tzinfo else now
    return {
        "kind": "dollar2",
        "dateLabel": long_date(now.date()),
        "quotes": [{"id": q["id"], "name": q["name"], "buy": q.get("buy"), "sell": q["sell"], "prev": q.get("prev")} for q in quotes],
        "gap": (float(blue["sell"]) / float(oficial["sell"]) - 1) * 100 if oficial and blue and oficial.get("sell") and blue.get("sell") else None,
        "updated": f"actualizado {updated:%d/%m %H:%M} h",
        "bg": bg("dolar"),
    }


# ---------------------------------------------------------------------------
# Cortes de luz (EDESA) y agua (Aguas del Norte): una placa por corte
# ---------------------------------------------------------------------------

# Capital y ciudades cabecera de departamento: sus cortes van tambien al feed de IG.
MAJOR_PLACES = (
    "salta capital", "capital", "oran", "tartagal", "metan", "rosario de la frontera", "guemes", "cafayate", "cerrillos",
    "rosario de lerma", "joaquin v. gonzalez", "embarcacion", "chicoana", "campo santo", "la caldera", "cachi",
    "coronel moldes", "la vina", "molinos", "san antonio de los cobres", "iruya", "guachipas", "la poma", "el carril",
)
EDESA_BRANCH_PLACES = {"SALTA": "Salta Capital", "ORAN": "Orán", "TARTAGAL": "Tartagal", "METAN": "Metán", "GUEMES": "General Güemes", "CAFAYATE": "Cafayate", "ROSARIO": "Rosario de la Frontera"}


def _plain(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def is_major_place(place: str) -> bool:
    p = _plain(place)
    return any(re.search(rf"\b{re.escape(m)}\b", p) for m in MAJOR_PLACES)


def edesa_zone(zone: str, branch: str) -> Optional[Dict[str, str]]:
    """Localidad y barrios tal como los escribe EDESA. Formatos vistos: "LOCALIDAD: ATOCHA - Barrio: X - ...",
    "Salta Capital: barrios ...", "En Metán: Barrios ...", "En localidad de Oran Barrios ...". Si no se
    puede sacar la localidad del texto se usa la de la sucursal; sin ninguna, no hay placa."""
    text = re.sub(r"\s+", " ", zone).strip(" .-")
    place, rest = "", text
    m = re.match(r"(?i)LOCALIDAD:\s*([^-]+?)\s*-\s*(.*)", text)
    if m:
        place, rest = m[1].title(), re.sub(r"(?i)\s*-\s*barrio:\s*", ", ", "- " + m[2]).strip(" ,")
    else:
        m = re.match(r"(?i)(?:en\s+(?:la\s+)?(?:localidad\s+de\s+)?)?([A-ZÁÉÍÓÚÑa-záéíóúñ. ]{3,40}?)\s*(?::|\bbarrios?\b)\s*(.*)", text)
        if m and not re.search(r"(?i)(\bruta\b|\bkm\b|derivaci|\bsobre\b|per[ií]metro)", m[1]):
            place, rest = m[1].strip(), m[2]
    if not place:
        key = _plain(branch.split()[0]).upper() if branch.split() else ""
        place = EDESA_BRANCH_PLACES.get(key, "")
        if not place:
            return None
    rest = re.sub(r"(?i)^(barrios?\s*:?\s*)", "", rest.strip(" :,-"))
    rest = re.sub(r"(?i)^per[ií]metro comprendido entre (las )?calles", "Entre", rest)
    if rest.isupper():
        rest = re.sub(r"\b[IVX]{1,4}\b", lambda r: r[0].upper(), rest.title(), flags=re.I)
    rest = re.sub(r"(?i)\s*(?:,|\by\b)?\s*-?\s*zonas aleda[ñn]as\.?-?$", " y zonas aledañas", rest).strip(" ,.-")
    if place.lower() == "salta":
        place = "Salta Capital"
    return {"place": place.title() if place.isupper() else place, "detail": rest[:180]}


def cut_extra(service: str, cut: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    """Placa de corte (aprobada C1p/A1p). Luz: horario de EDESA (fin = inicio + duracion). Agua: Aguas del
    Norte casi nunca da horas, entonces "Hasta normalizar"."""
    if service == "luz":
        zone = edesa_zone(str(cut.get("zone") or ""), str(cut.get("branch") or ""))
        if not zone:
            return None
        start = datetime.fromisoformat(cut["start"])
        end = datetime.fromisoformat(cut["end"]) if cut.get("end") else None
        day = start.date()
        status = "cancelado" if cut.get("state") == "cancelado" else "hoy" if day == today else "manana" if day == today + timedelta(days=1) else "programado"
        return {
            "kind": "cut", "service": "luz", "status": status, "statusLabel": f"{DAYS[day.weekday()][:3]} {day:%d/%m}",
            "place": zone["place"], "sub": f"{DAYS[day.weekday()][:3]} {day:%d/%m} · sucursal {str(cut.get('branch') or '').title()}",
            "start": f"{start:%H:%M}", "end": f"{end:%H:%M}" if end else "", "detail": zone["detail"], "reason": cut.get("reason", ""),
            "source": "Fuente: EDESA · listado oficial de cortes", "bg": bg("luz"),
        }
    zone_name = str(cut.get("zone") or "").strip()
    if not zone_name or zone_name.lower() == "cortes programados":
        return None  # sin zona no hay placa (la linea general de estado va en el tablero de las 9)
    day = date.fromisoformat(cut["date"])
    return {
        "kind": "cut", "service": "agua", "status": "ahora" if day <= today else "manana", "place": zone_name,
        "sub": f"{DAYS[day.weekday()][:3]} {day:%d/%m}", "start": "", "end": "", "since": "Desde hoy" if day <= today else "Desde mañana",
        "detail": str(cut.get("detail") or "")[:180], "reason": "", "source": "Fuente: Aguas del Norte", "bg": bg("agua"),
    }


def cut_caption(extra: Dict[str, Any]) -> str:
    water = extra["service"] == "agua"
    what = "Corte de agua" if water else "Corte de luz programado"
    when = {"hoy": "hoy", "ahora": "hoy", "manana": "mañana"}.get(extra["status"], extra.get("statusLabel", ""))
    if extra["status"] == "cancelado":
        head = f"✅ Se canceló el corte de luz anunciado en {extra['place']} ({extra.get('statusLabel', '')})"
        body = []
    else:
        head = f"{'🚰' if water else '💡'} {what} {when} en {extra['place']} 👇"
        body = [f"🕗 De {extra['start']} a {extra['end']}" if extra.get("end") else "🕗 Hasta normalizar el servicio"]
    if extra.get("detail"):
        body.append(f"📍 {extra['detail']}")
    if extra.get("reason"):
        body.append(f"🔧 Motivo: {extra['reason']}")
    tags = "#DuoNoticias #Salta #CorteDeAgua" if water else "#DuoNoticias #Salta #CorteDeLuz"
    return "\n".join([head, "", *body, "", f"Fuente: {'Aguas del Norte' if water else 'EDESA'}.", tags])


# ---------------------------------------------------------------------------
# Paso fronterizo cerrado en su horario (aprobada P1p)
# ---------------------------------------------------------------------------


def pass_extra(p: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    name = str(p["name"])
    at = parse_ts(str(p.get("at") or "").replace(" ", "T")) or now.replace(tzinfo=None)
    return {
        "kind": "pass", "name": name if " - " in name else f"Paso de {name}", "route": f"Argentina – {p.get('country', '')}",
        "state": p.get("state", "CERRADO"), "sinceLabel": f"Informado a las {at:%H:%M} h · dentro de su horario",
        "hours": str(p.get("hours") or ""), "nowH": at.hour + at.minute / 60, "note": p.get("note") or "",
        "source": f"Fuente: Ministerio de Seguridad · {at:%H:%M} h", "bg": bg("paso"),
    }


def pass_caption(extra: Dict[str, Any]) -> str:
    lines = [f"⛔ {extra['name']} ({extra['route']}): figura CERRADO dentro de su horario habitual 👇", ""]
    if extra.get("hours"):
        lines.append(f"🕗 Horario habitual: {extra['hours'].replace('-', ' a ')}")
    if extra.get("note"):
        lines.append(f"ℹ️ {extra['note']}")
    lines += ["Consultá el estado del paso antes de viajar: puede cambiar durante el día.", "", "Fuente: Ministerio de Seguridad de la Nación.", "#DuoNoticias #Salta #PasosFronterizos"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sueldos de la Administracion Publica de Salta (aprobada S2: calendario del mes)
# ---------------------------------------------------------------------------

PAYDAY_TITLE = re.compile(r"(?i)\b(sueldos|haberes)\b.*\b(pagar|pago|abon|cobr)|\b(pagar|pago|abon|cobr)\w*\b.*\b(sueldos|haberes)\b")
PAYDAY_DATE = re.compile(r"(?i)\b(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s+(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\b")
PAYDAY_SECTORS = (("Salud", r"\bsalud\b"), ("Seguridad", r"\bseguridad\b"), ("Educación", r"\beducaci[óo]n\b"), ("Resto de la Administración", r"resto de la administraci[óo]n"))


def payday_extra(row: Dict[str, Any], today: date) -> Optional[Dict[str, Any]]:
    """Fecha de cobro tal como la anuncia el Gobierno de Salta. Solo con una unica fecha (si el pago viene
    escalonado no hay placa: no se adivina que sector cobra cada dia)."""
    title = str(row.get("title") or "")
    body = str(row.get("body_text") or row.get("summary") or "")
    if not PAYDAY_TITLE.search(title):
        return None
    text = f"{title}. {body}"
    dates = {(int(m[2]), MONTHS.index(m[3].lower())) for m in PAYDAY_DATE.finditer(text)}
    if len(dates) != 1:
        return None
    day, month0 = dates.pop()
    year = today.year + (1 if month0 + 1 < today.month - 6 else 0)
    try:
        pay = date(year, month0 + 1, day)
    except ValueError:
        return None
    if pay < today:
        return None
    sectors = [label for label, rx in PAYDAY_SECTORS if re.search(rx, text, re.I)]
    extra_parts = []
    if re.search(r"(?i)compensaci[óo]n transitoria", text):
        extra_parts.append("Con los sueldos se paga la Compensación Transitoria Docente.")
    if re.search(r"(?i)misma jornada|mismo d[íi]a|todos los sectores", text):
        extra_parts.append("Todos los sectores cobran el mismo día.")
    first = date(pay.year, pay.month, 1)
    month_days = ((first.replace(month=first.month % 12 + 1, year=first.year + first.month // 12)) - first).days
    return {
        "kind": "payday", "variant": "B", "day": pay.day, "date": pay.isoformat(), "weekday": DAYS[pay.weekday()].capitalize(), "month": MONTHS[pay.month - 1],
        "monthDays": month_days, "firstWeekday": first.weekday(), "today": today.day if today.month == pay.month else 0,
        "daysLeft": (pay - today).days, "sectors": sectors, "extra": " ".join(extra_parts),
        "source": f"Fuente: Gobierno de Salta · {parse_ts(row.get('created_at')).strftime('%d/%m') if parse_ts(row.get('created_at')) else ''}".rstrip(" ·"),
    }


def payday_caption(extra: Dict[str, Any]) -> str:
    who = ", ".join(extra["sectors"]) if extra["sectors"] else "la Administración Pública Provincial"
    lines = [f"💰 Los estatales de Salta cobran el {extra['weekday'].lower()} {extra['day']} de {extra['month']} 👇", "", f"✅ {who}"]
    if extra.get("extra"):
        lines.append(f"📌 {extra['extra']}")
    lines += ["", "Fuente: Gobierno de la Provincia de Salta.", "#DuoNoticias #Salta #Sueldos"]
    return "\n".join(lines)


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


ANSES_SHORT = {"pnc": "Pensiones no contributivas", "minimo": "Jubilaciones hasta el mínimo", "superior": "Jubilaciones que superan el mínimo"}


def anses_extra(calendar: Dict[str, Any], today: date, holidays: Optional[List[Dict[str, Any]]] = None, *, next_days: int = 5, max_lines: int = 6) -> Optional[Dict[str, Any]]:
    """Quienes empiezan a cobrar hoy y en los proximos dias de pago, tal como dice el calendario oficial.
    Sin pagos hoy, o si hoy es feriado (ANSES corre esos pagos por otra resolucion), no hay placa."""
    if any(h.get("fecha") == today.isoformat() for h in holidays or []):
        return None
    groups = calendar.get("groups") or []
    now = [g for g in groups if g["date"] == today.isoformat()]
    if not now:
        return None
    days: Dict[str, List[Dict[str, Any]]] = {}
    for g in groups:
        if g["date"] > today.isoformat():
            days.setdefault(g["date"], []).append(g)
    upcoming = []
    lines = 0
    for day in sorted(days)[:next_days]:
        lines += len(days[day])
        if upcoming and lines > max_lines:
            break
        d = date.fromisoformat(day)
        upcoming.append({"label": f"{DAYS[d.weekday()][:3]} {d.day}", "items": [{"label": ANSES_SHORT[g["kind"]], "digits": g["digits"]} for g in days[day]]})
    valid = (calendar.get("valid_until") or {}).get(str(today.month))
    return {
        "kind": "anses",
        "dateLabel": long_date(today),
        "groups": [{"who": g["label"], "digits": g["digits"]} for g in now],
        "upcoming": upcoming,
        "validUntil": f"{date.fromisoformat(valid):%d/%m}" if valid else "",
        "source": f"Fuente: ANSES · {calendar.get('resolucion') or 'calendario oficial'} (Boletín Oficial)",
    }


def anses_caption(extra: Dict[str, Any]) -> str:
    lines = [f"💳 ANSES: quién cobra hoy, {extra['dateLabel']} 👇", ""]
    for g in extra["groups"]:
        lines.append(f"✅ {g['who']}: DNI terminados en {' y '.join(g['digits'])}")
    if extra.get("upcoming"):
        lines += ["", "📅 Próximos pagos:"]
        for day in extra["upcoming"][:3]:
            lines.append(f"• {day['label'].capitalize()}: " + "; ".join(f"{i['label'].lower()}, DNI {' y '.join(i['digits'])}" for i in day["items"]))
    lines += ["", "Consultá tu fecha exacta en Mi ANSES con tu CUIL.", "Fuente: calendario oficial de ANSES (Boletín Oficial).", "#DuoNoticias #Salta #ANSES"]
    return "\n".join(lines)


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
    today = [c for c in (power or {}).get("cuts") or [] if c["start"][:10] == now.date().isoformat() and c["state"] != "cancelado"]
    if power is None:
        power_box = {"ok": None, "text": "EDESA no publica hoy su listado de cortes programados. Reclamos: 0800 777 33372."}
    elif not today:
        power_box = {"ok": True, "text": "Sin cortes programados para hoy."}
    else:
        power_box = {"ok": False, "text": "; ".join(f"{c['zone'][:90]} ({c['start'][11:16]} h)" for c in today[:2])[:260]}
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


def story_update(
    note: NoteView, headline: str, before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]], previous: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """``previous``: titular y hora del post original, para que se lea como actualizacion."""
    extra: Dict[str, Any] = {"kind": "story-update", "headline": headline, "photo": note.photo(), "location": note.location, "points": note.points}
    if previous and previous.get("headline"):
        extra["previous"] = previous
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


# ---------------------------------------------------------------------------
# Sismos (INPRES, 2026-10-22): placa fija, sin IA
# ---------------------------------------------------------------------------

# Localidades de referencia para ubicar el epicentro ("a 45 km de San Antonio de los Cobres").
SALTA_PLACES = (
    ("Salta Capital", -24.79, -65.41), ("Orán", -23.13, -64.33), ("Tartagal", -22.52, -63.80),
    ("Salvador Mazza", -22.05, -63.69), ("Embarcación", -23.21, -64.10), ("Güemes", -24.67, -65.05),
    ("Metán", -25.50, -64.97), ("Rosario de la Frontera", -25.80, -64.97), ("Joaquín V. González", -25.12, -64.13),
    ("Cafayate", -26.07, -65.97), ("Cachi", -25.12, -66.16), ("San Antonio de los Cobres", -24.22, -66.32),
    ("Tolar Grande", -24.59, -67.39),
)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def quake_extra(quake: Dict[str, Any], local_time: datetime) -> Dict[str, Any]:
    place, distance = min(((name, _km(quake["lat"], quake["lon"], lat, lon)) for name, lat, lon in SALTA_PLACES), key=lambda pair: pair[1])
    capital = _km(quake["lat"], quake["lon"], -24.79, -65.41)
    return {
        "kind": "quake",
        "magnitude": quake["magnitude"],
        "depthKm": round(quake["depth_km"]),
        "near": place,
        "nearKm": round(distance),
        "capitalKm": round(capital),
        "felt": quake["state"] == "sentido",
        "state": quake["state"],
        "timeLabel": f"{local_time:%H:%M} h",
        "dateLabel": f"{DAYS[local_time.weekday()]} {short_date(local_time.date())}",
    }


def quake_caption(extra: Dict[str, Any]) -> str:
    where = "en Salta" if extra["nearKm"] < 15 else f"a {extra['nearKm']} km de {extra['near']}"
    felt = "Fue un sismo sentido. " if extra["felt"] else ""
    return (
        f"🌎 Sismo de magnitud {extra['magnitude']:.1f} {where} 👇\n\n"
        f"🕒 {extra['dateLabel'].capitalize()}, {extra['timeLabel']}\n"
        f"📍 Epicentro a {extra['capitalKm']} km de la Capital salteña\n"
        f"↕️ Profundidad: {extra['depthKm']} km\n\n"
        f"{felt}Datos del Instituto Nacional de Prevención Sísmica (INPRES).\n\n"
        "💬 ¿Lo sentiste? Contanos desde dónde.\n\n#DuoNoticias #Sismo #Salta"
    )
