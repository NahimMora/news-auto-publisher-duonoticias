"""Bundle de CA para sitios que no envian su certificado intermedio.

prensa.policiadesalta.gob.ar entrega solo su certificado (Sectigo DV R36) sin el
intermedio; los navegadores lo completan por AIA, ``requests`` no. En vez de
desactivar la verificacion TLS, se agrega ese intermedio publico (firmado por
una raiz de certifi) en ``config/certs/`` y se arma un bundle certifi + extras.
La cadena se sigue verificando completa contra las raices de certifi.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Union
from urllib.parse import urlparse

import certifi

BASE_DIR = Path(__file__).resolve().parents[1]
CERTS_DIR = BASE_DIR / "config" / "certs"
# Hosts que necesitan el bundle extendido.
EXTENDED_CHAIN_HOSTS = {"prensa.policiadesalta.gob.ar"}


@functools.lru_cache(maxsize=1)
def extended_ca_bundle() -> str:
    extras = sorted(CERTS_DIR.glob("*.pem")) if CERTS_DIR.exists() else []
    if not extras:
        return certifi.where()
    target = BASE_DIR / "data" / "runtime" / "ca_bundle_extended.pem"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = Path(certifi.where()).read_bytes()
    for extra in extras:
        content += b"\n" + extra.read_bytes()
    if not target.exists() or target.read_bytes() != content:
        target.write_bytes(content)
    return str(target)


def ca_bundle_for(url: str) -> Union[str, bool]:
    host = (urlparse(url).hostname or "").lower()
    if host in EXTENDED_CHAIN_HOSTS:
        return extended_ca_bundle()
    return True
