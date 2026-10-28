"""Calendario oficial de pagos de ANSES desde el Boletin Oficial (una vez por año, con control manual).

ANSES fija el calendario anual por resolucion: para 2026 es la Resolucion 349/2025 (aviso 334596
del 17/11/2025), con un anexo por mes. anses.gob.ar bloquea los accesos automaticos, asi que esta es
la fuente oficial legible. Genera config/anses_calendar_<año>.json; revisar el resultado contra los
PDF antes de commitear.

Uso: python scripts/anses_calendar.py --year 2026 --aviso 334596 --fecha 20251117 --anexo-id 7512916
(el id de los anexos sale del HTML del aviso: descargarPDFAnexo("primera", N, "<id>", ...)).
Necesita ``pdftotext`` (poppler) en el PATH.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

import httpx

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
SECTIONS = [
    (re.compile(r"PENSIONES NO CONTRIBUTIVAS", re.I), "pnc", "Pensiones no contributivas"),
    (re.compile(r"no superen el monto", re.I), "minimo", "Jubilaciones y pensiones hasta el haber mínimo"),
    (re.compile(r"(?<!no )superen el monto", re.I), "superior", "Jubilaciones y pensiones que superan el haber mínimo"),
]
GROUP = re.compile(r"GRUPO DE PAGO (\d+):\s*Documentos terminados en ([\d ,y]+?),\s*a partir del d[ií]a (\d{1,2}) de (\w+) de (\d{4})", re.I)
VALID = re.compile(r"Determ[ií]nase el d[ií]a (\d{1,2}) de (\w+) de (\d{4})", re.I)


def parse_annex(text: str) -> dict:
    text = re.sub(r"\s+", " ", text)
    groups = []
    section = None
    pos = 0
    marks = []
    for rx, key, label in SECTIONS:
        for m in rx.finditer(text):
            marks.append((m.start(), key, label))
    marks.sort()
    for m in GROUP.finditer(text):
        while marks and marks[0][0] < m.start():
            section = marks.pop(0)
        if section is None:
            raise ValueError(f"grupo {m[1]} sin seccion")
        day, month, year = int(m[3]), MONTHS.index(m[4].lower()) + 1, int(m[5])
        groups.append({"group": int(m[1]), "kind": section[1], "label": section[2], "digits": re.findall(r"\d", m[2]), "date": date(year, month, day).isoformat()})
        pos = m.end()
    valid = VALID.search(text, pos)
    if len(groups) != 20:
        raise ValueError(f"se esperaban 20 grupos y hay {len(groups)}")
    return {"groups": groups, "valid_until": date(int(valid[3]), MONTHS.index(valid[2].lower()) + 1, int(valid[1])).isoformat() if valid else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--aviso", required=True)
    ap.add_argument("--fecha", required=True)
    ap.add_argument("--anexo-id", required=True)
    ap.add_argument("--resolucion", default="")
    args = ap.parse_args()
    out = {"year": args.year, "source": f"https://www.boletinoficial.gob.ar/detalleAviso/primera/{args.aviso}/{args.fecha}", "resolucion": args.resolucion, "months": {}}
    with httpx.Client(timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as http, tempfile.TemporaryDirectory() as tmp:
        for n in range(1, 13):
            resp = http.post("https://www.boletinoficial.gob.ar/pdf/download_anexo", data={"seccion": "primera", "nroAnexo": str(n), "idAnexo": args.anexo_id, "fechaPublicacion": args.fecha})
            pdf = Path(tmp) / f"anexo{n}.pdf"
            pdf.write_bytes(base64.b64decode(resp.json()["pdfBase64"]))
            text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=True).stdout.decode("utf-8", "ignore")
            out["months"][str(n)] = parse_annex(text)
            print(n, "ok", out["months"][str(n)]["groups"][0]["date"], "->", out["months"][str(n)]["groups"][-1]["date"])
    target = Path(__file__).resolve().parents[1] / "config" / f"anses_calendar_{args.year}.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("escrito", target)


if __name__ == "__main__":
    main()
