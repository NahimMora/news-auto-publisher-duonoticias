"""Datos de servicio para Salta desde fuentes oficiales o publicas.

Cada funcion devuelve ``(datos, estado)``. ``estado`` = {"ok": bool, "detail": str}
y va al reporte de operaciones: si una fuente se cae, el dueño se entera.

- Clima y alertas: SMN. El servidor viejo (ws2.smn.gob.ar) ya no existe; la web
  actual usa ws1.smn.gob.ar/v1 con un token publico que viene embebido en
  www.smn.gob.ar. Cloudflare corta la huella TLS de httpx, por eso se usa curl.
  Desde el 21/10/2026 la web del SMN pide un desafio de Cloudflare y el token ya no se puede
  leer: el respaldo son los datos abiertos oficiales del SMN (ssl.smn.gob.ar/dpd, sin token):
  tiempo presente medido en la estacion Salta y alertas; el pronostico de 4 dias, de Open-Meteo.
- Dolar: DolarApi (respaldo: API oficial del BCRA). Historico: ArgentinaDatos.
- Feriados: ArgentinaDatos (calendario oficial).
- Cortes de agua: Aguas del Norte (aguasdelnortesalta.com.ar).
- Cortes de luz: EDESA (widget publico de cortes programados).
- Pasos fronterizos: Ministerio de Seguridad (argentina.gob.ar).
"""
from __future__ import annotations

import html as html_lib
import io
import json
import logging
import re
import shutil
import subprocess
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

LOGGER = logging.getLogger("duo.formats.sources")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
SALTA_LAT, SALTA_LON = -24.79, -65.41
Status = Dict[str, Any]
# Pasos que se muestran (los de Salta y Jama, el paso a Chile mas usado desde Salta).
PASSES_SHOWN = ("Sico", "Socompa", "Aguas Blancas - Bermejo", "Salvador Mazza - Yacuiba", "El Condado - La Mamora", "Jama")


def _ok(detail: str) -> Status:
    return {"ok": True, "detail": detail[:160]}


def _fail(detail: object) -> Status:
    return {"ok": False, "detail": str(detail)[:160]}


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"}, timeout=25, follow_redirects=True)


def _curl(url: str, *headers: str) -> str:
    curl = shutil.which("curl") or "curl"
    cmd = [curl, "-s", "-m", "25", "-A", UA, "-H", "Accept: text/html,application/json", "-H", "Accept-Language: es-AR,es;q=0.9"]
    for header in headers:
        cmd += ["-H", header]
    done = subprocess.run(cmd + [url], capture_output=True, timeout=40)
    return done.stdout.decode("utf-8", errors="ignore")


def _page_lines(raw: bytes) -> List[str]:
    text = raw.decode("utf-8", errors="ignore")
    if "Ã" in text:  # pagina en latin-1
        text = raw.decode("latin-1", errors="ignore")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", text, flags=re.S)
    return [line.strip() for line in html_lib.unescape(re.sub(r"<[^>]+>", "\n", text)).splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Clima (SMN)
# ---------------------------------------------------------------------------


TOKEN_CACHE: Optional[Path] = None


def _smn_token(fresh: bool = False) -> str:
    """Token publico de la web del SMN, cacheado en disco (Cloudflare a veces devuelve un desafio)."""
    if not fresh and TOKEN_CACHE and TOKEN_CACHE.exists():
        token = TOKEN_CACHE.read_text(encoding="utf-8").strip()
        if token:
            return token
    for attempt in range(3):
        match = re.search(r"setItem\('token',\s*'([^']+)'", _curl("https://www.smn.gob.ar/"))
        if match:
            if TOKEN_CACHE:
                TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
                TOKEN_CACHE.write_text(match.group(1), encoding="utf-8")
            return match.group(1)
        time.sleep(4 * (attempt + 1))
    return ""


def weather() -> Tuple[Optional[Dict[str, Any]], Status]:
    data, status = _smn_weather()
    if data is not None:
        return data, status
    open_data, open_status = _smn_open_data()
    if open_data is not None:
        return open_data, open_status
    fallback = _open_meteo()
    if fallback is not None:
        return fallback, _fail(f"{status['detail']} · se uso Open-Meteo (sin alertas del SMN)")
    return None, status


def _open_meteo() -> Optional[Dict[str, Any]]:
    """Respaldo sin alertas: temperatura actual y pronostico de 4 dias."""
    try:
        with _client() as http:
            d = http.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": SALTA_LAT, "longitude": SALTA_LON, "timezone": "America/Argentina/Salta", "forecast_days": 4,
                        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                        "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weather_code"},
            ).json()
        desc = lambda code: "Despejado" if code in (0, 1) else "Parcialmente nublado" if code == 2 else "Nublado" if code in (3, 45, 48) else "Lloviznas" if 51 <= code <= 57 else "Lluvias" if 61 <= code <= 82 else "Tormentas" if code >= 95 else "Nublado"  # noqa: E731
        cur, daily = d["current"], d["daily"]
        days = [{"date": daily["time"][i], "min": daily["temperature_2m_min"][i], "max": daily["temperature_2m_max"][i], "desc": desc(int(daily["weather_code"][i])),
                 "rain": int(daily["precipitation_probability_max"][i] or 0)} for i in range(len(daily["time"]))]
        return {"now": {"temp": cur["temperature_2m"], "desc": desc(int(cur["weather_code"])), "humidity": cur["relative_humidity_2m"], "wind": f"{cur['wind_speed_10m']:.0f} km/h",
                        "at": cur["time"]}, "days": days, "alert_levels": {}, "source": "Open-Meteo"}
    except Exception as exc:
        LOGGER.warning("Open-Meteo: %s", exc)
        return None


SMN_OPEN_DATA = "https://ssl.smn.gob.ar/dpd/zipopendata.php?dato={}"
ALERT_LEVELS = (("roj", 4), ("naranja", 3), ("amarill", 2))


def _smn_open_file(dato: str) -> str:
    """Un archivo de datos abiertos del SMN (zip con un .txt adentro)."""
    with _client() as http:
        raw = http.get(SMN_OPEN_DATA.format(dato)).content
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        return "".join(bundle.read(name).decode("utf-8", errors="ignore") for name in bundle.namelist())


def _smn_open_data() -> Tuple[Optional[Dict[str, Any]], Status]:
    """Datos abiertos del SMN: observacion oficial de la estacion Salta, alertas y pronostico de Open-Meteo."""
    try:
        line = next((ln for ln in _smn_open_file("tiepre").splitlines() if ln.strip().lower().startswith("salta;")), "")
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 10:
            return None, _fail("SMN datos abiertos: sin la estacion Salta en tiempo presente")
        # Salta;22-octubre-2026;08:00;Parcialmente nublado con neblina;12 km;15.6;No se calcula; 92;Sur  1;876.3 /
        temp = float(parts[5])
        wind = re.sub(r"\s+", " ", parts[8])
        wind = wind + " km/h" if re.search(r"\d$", wind) else wind
        forecast = _open_meteo()
        if forecast is None:
            return None, _fail("SMN datos abiertos: sin pronostico de Open-Meteo")
        levels: Dict[str, int] = {}
        try:
            for alert_line in _smn_open_file("alertas").splitlines():
                text = alert_line.lower()
                if "salta" in text:
                    level = next((lvl for word, lvl in ALERT_LEVELS if word in text), 0)
                    if level:
                        today = date.today().isoformat()
                        levels[today] = max(levels.get(today, 1), level)
        except Exception as exc:  # sin alertas no se frena el clima
            LOGGER.warning("SMN alertas (datos abiertos): %s", exc)
        data = {
            "now": {"temp": temp, "desc": parts[3], "humidity": int(float(parts[7])), "wind": wind, "at": f"{parts[1]} {parts[2]}"},
            "days": forecast["days"],
            "alert_levels": levels,
            "source": "SMN (estacion Salta) + Open-Meteo",
        }
        return data, _ok(f"SMN datos abiertos: {temp} °C, alerta nivel {max(levels.values() or [1])}")
    except Exception as exc:
        return None, _fail(f"SMN datos abiertos: {exc}")


def _smn_weather() -> Tuple[Optional[Dict[str, Any]], Status]:
    try:
        token = _smn_token()
        if not token:
            return None, _fail("SMN: no se encontro el token publico en la web")

        def api(path: str) -> Any:
            nonlocal token
            for attempt in range(2):
                raw = _curl(f"https://ws1.smn.gob.ar/v1/{path}", f"Authorization: JWT {token}")
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = None
                if isinstance(payload, (dict, list)) and not (isinstance(payload, dict) and payload.get("status") in (401, 403)):
                    return payload
                token = _smn_token(fresh=True)  # token vencido o desafio: se renueva una vez
            raise RuntimeError(f"respuesta invalida de {path}")

        loc = api(f"georef/location/coord?lat={SALTA_LAT}&lon={SALTA_LON}")
        now = api(f"weather/location/{loc['id']}")
        forecast = api(f"forecast/location/{loc['id']}")
        alerts = api(f"warning/alert/area/{loc['ref']['area_id']}")
        days = []
        for day in forecast.get("forecast", [])[:4]:
            parts = [day.get(k) for k in ("early_morning", "morning", "afternoon", "night") if day.get(k)]
            main = day.get("afternoon") or day.get("night") or day.get("morning") or {}
            rain = max([max(p.get("rain_prob_range") or [0]) for p in parts] or [0])
            days.append({"date": day["date"], "min": day.get("temp_min"), "max": day.get("temp_max"), "desc": (main.get("weather") or {}).get("description", ""), "rain": rain})
        levels = {w["date"]: int(w.get("max_level") or 1) for w in alerts.get("warnings", [])}
        data = {
            "now": {
                "temp": now.get("temperature"),
                "desc": (now.get("weather") or {}).get("description", ""),
                "humidity": now.get("humidity"),
                "wind": f"{(now.get('wind') or {}).get('direction', '')} {float((now.get('wind') or {}).get('speed') or 0):.0f} km/h".strip(),
                "at": now.get("date"),
            },
            "days": days,
            "alert_levels": levels,
        }
        if data["now"]["temp"] is None or not days:
            return None, _fail("SMN: respuesta sin temperatura o pronostico")
        return data, _ok(f"{data['now']['temp']} °C, alerta nivel {max(levels.values() or [1])}")
    except Exception as exc:
        return None, _fail(f"SMN: {exc}")


# ---------------------------------------------------------------------------
# Dolar
# ---------------------------------------------------------------------------

DOLLAR_NAMES = {"oficial": "Oficial", "blue": "Blue", "bolsa": "MEP", "contadoconliqui": "CCL", "tarjeta": "Tarjeta"}


def dollar(today: date) -> Tuple[Optional[List[Dict[str, Any]]], Status]:
    try:
        with _client() as http:
            rows = http.get("https://dolarapi.com/v1/dolares").json()
            quotes = []
            for row in rows:
                if row.get("casa") not in DOLLAR_NAMES:
                    continue
                quote = {"id": row["casa"], "name": DOLLAR_NAMES[row["casa"]], "buy": row.get("compra"), "sell": row.get("venta"), "updated": row.get("fechaActualizacion")}
                if row["casa"] in ("oficial", "blue"):
                    try:
                        hist = http.get(f"https://api.argentinadatos.com/v1/cotizaciones/dolares/{row['casa']}").json()
                        previous = [h for h in hist if h.get("fecha", "") < today.isoformat()]
                        if previous:
                            quote["prev"] = previous[-1].get("venta")
                    except Exception:
                        pass
                quotes.append(quote)
        order = list(DOLLAR_NAMES)
        quotes.sort(key=lambda q: order.index(q["id"]))
        if not quotes:
            return None, _fail("DolarApi: sin cotizaciones")
        return quotes, _ok(", ".join(f"{q['name']} {q['sell']}" for q in quotes))
    except Exception as exc:
        try:
            with _client() as http:
                data = http.get("https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/USD").json()
            rate = (data.get("results") or [{}])[0].get("detalle", [{}])[0].get("tipoCotizacion")
            if rate:
                return [{"id": "oficial", "name": "Oficial (BCRA)", "buy": None, "sell": rate, "updated": today.isoformat()}], _ok(f"respaldo BCRA {rate} (DolarApi fallo: {exc})")
        except Exception:
            pass
        return None, _fail(f"dolar: {exc}")


# ---------------------------------------------------------------------------
# Feriados
# ---------------------------------------------------------------------------


def holidays(today: date) -> Tuple[Optional[List[Dict[str, Any]]], Status]:
    try:
        with _client() as http:
            rows = http.get(f"https://api.argentinadatos.com/v1/feriados/{today.year}").json()
            if today.month == 12:
                rows += http.get(f"https://api.argentinadatos.com/v1/feriados/{today.year + 1}").json()
        upcoming = [r for r in rows if r.get("fecha", "") >= today.isoformat()][:5]
        return upcoming, _ok(", ".join(f"{r['fecha']} {r['nombre']}" for r in upcoming[:2]))
    except Exception as exc:
        return None, _fail(f"feriados: {exc}")


# ---------------------------------------------------------------------------
# Cortes de agua y luz
# ---------------------------------------------------------------------------


def water_cuts(today: date) -> Tuple[Optional[Dict[str, Any]], Status]:
    try:
        with _client() as http:
            programmed = _page_lines(http.get("https://www.aguasdelnortesalta.com.ar/cortes.php").content)
            extra = _page_lines(http.get("https://www.aguasdelnortesalta.com.ar/afectaciones.php").content)
        start = next(i for i, line in enumerate(programmed) if line.upper().startswith("CORTES PROGRAMADOS"))
        status_line = programmed[start + 1] if start + 1 < len(programmed) else ""
        cuts = []
        idx = next((i for i, line in enumerate(extra) if "AFECTACIONES EXTRAORDINARIAS" in line.upper()), None)
        if idx is not None:
            block = extra[idx + 1 : idx + 80]
            for n, line in enumerate(block):
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", line)
                if not m:
                    continue
                when = date(int(m[3]), int(m[2]), int(m[1]))
                if when >= today - timedelta(days=1):
                    cuts.append({"zone": block[n - 1] if n else "", "date": when.isoformat(), "detail": " ".join(block[n + 1 : n + 10])[:400]})
        no_cuts = "no afectan" in status_line.lower()
        if not no_cuts and status_line and not status_line.lower().startswith(("empresa", "carta")):
            cuts.insert(0, {"zone": "Cortes programados", "date": today.isoformat(), "detail": status_line[:400]})
        return {"status": status_line, "cuts": cuts}, _ok(f"{len(cuts)} afectaciones vigentes")
    except Exception as exc:
        return None, _fail(f"Aguas del Norte: {exc}")


def power_cuts() -> Tuple[Optional[Dict[str, Any]], Status]:
    try:
        with _client() as http:
            lines = _page_lines(http.get("https://www.edesa.com.ar/widgets/cortes.php").content)
        if any("problema recuperando" in line.lower() for line in lines):
            return None, _fail("EDESA: su listado de cortes programados no responde")
        return {"lines": lines[:40]}, _ok(f"{len(lines)} lineas")
    except Exception as exc:
        return None, _fail(f"EDESA: {exc}")


# ---------------------------------------------------------------------------
# Pasos fronterizos
# ---------------------------------------------------------------------------


def border_passes() -> Tuple[Optional[List[Dict[str, Any]]], Status]:
    try:
        with _client() as http:
            rows = http.get("https://www.argentina.gob.ar/seguridad/pasosinternacionales/listado").json()
        shown = []
        for row in rows:
            name = str(row.get("nombre_paso") or "")
            if name in PASSES_SHOWN and (row.get("provincia") == "SALTA" or name == "Jama") and name not in {p["name"] for p in shown}:
                shown.append({"name": name, "country": str(row.get("pais") or "").title(), "state": str(row.get("estado_prioridad") or ""), "hours": row.get("fecha_schema"), "at": row.get("fecha_hora_consulta")})
        shown.sort(key=lambda p: PASSES_SHOWN.index(p["name"]))
        if not shown:
            return None, _fail("pasos: listado sin los pasos de Salta")
        return shown, _ok(", ".join(f"{p['name']}={p['state']}" for p in shown))
    except Exception as exc:
        return None, _fail(f"pasos: {exc}")


def collect_all(today: date) -> Tuple[Dict[str, Any], Dict[str, Status]]:
    data: Dict[str, Any] = {}
    health: Dict[str, Status] = {}
    for name, fn in (
        ("weather", weather),
        ("dollar", lambda: dollar(today)),
        ("holidays", lambda: holidays(today)),
        ("water", lambda: water_cuts(today)),
        ("power", power_cuts),
        ("passes", border_passes),
    ):
        value, status = fn()
        data[name] = value
        health[name] = {**status, "checked_at": datetime.now().replace(microsecond=0).isoformat()}
        if not status["ok"]:
            LOGGER.warning("fuente de servicio %s: %s", name, status["detail"])
    return data, health
