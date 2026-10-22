"""Respaldo del clima con los datos abiertos del SMN (la web del SMN pide desafio de Cloudflare)."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from formats import sources

TIEPRE = " Rosario;22-octubre-2026;08:00;Despejado;10 km;14.0;No se calcula; 80;Norte  5;1010.0 /\n Salta;22-octubre-2026;08:00;Parcialmente nublado con neblina;12 km;15.6;No se calcula; 92;Sur  1;876.3 /\n"
FORECAST = {"days": [{"date": "2026-10-22", "min": 13.2, "max": 30.4, "desc": "Nublado", "rain": 2}]}


class SmnOpenDataTests(unittest.TestCase):
    def run_with(self, alerts: str):
        files = {"tiepre": TIEPRE, "alertas": alerts}
        with patch.object(sources, "_smn_open_file", side_effect=lambda dato: files[dato]), patch.object(sources, "_open_meteo", return_value=FORECAST):
            return sources._smn_open_data()

    def test_salta_station_and_open_meteo_forecast(self) -> None:
        data, status = self.run_with("")
        self.assertTrue(status["ok"])
        self.assertEqual(data["now"], {"temp": 15.6, "desc": "Parcialmente nublado con neblina", "humidity": 92, "wind": "Sur 1 km/h", "at": "22-octubre-2026 08:00"})
        self.assertEqual(data["days"], FORECAST["days"])
        self.assertEqual(data["alert_levels"], {})

    def test_alert_for_salta(self) -> None:
        data, _ = self.run_with("Alerta naranja por tormentas para: Capital - Salta\nAlerta roja por viento para: Jujuy\n")
        self.assertEqual(data["alert_levels"], {date.today().isoformat(): 3})

    def test_without_salta_station_falls_through(self) -> None:
        with patch.object(sources, "_smn_open_file", return_value=" Rosario;x;y;z;a;1;b;2;c;d\n"):
            data, status = sources._smn_open_data()
        self.assertIsNone(data)
        self.assertFalse(status["ok"])


if __name__ == "__main__":
    unittest.main()
