"""Etiquetas de Instagram (``user_tags``) para las personas e instituciones de la nota.

Nunca se etiqueta una cuenta adivinada: cada usuario sale de la lista curada
(``config/instagram_tags.yaml``) o lo propone la redaccion IA y lo confirma la
API (``business_discovery``): la cuenta existe, su nombre coincide con el de la
nota y supera el minimo de seguidores. Las verificaciones se guardan en cache
(``data/runtime/ig_handles.json``) para no repetir consultas.

Reglas de seguridad:
- la persona o institucion tiene que figurar en el texto de la nota;
- nunca particulares, victimas, menores, detenidos o acusados (el prompt no los
  propone y aca solo se aceptan ``persona_publica`` e ``institucion``);
- en policiales y justicia solo se etiquetan instituciones.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import yaml

LOGGER = logging.getLogger("duo.ig_tags")
Lookup = Callable[[str], Optional[Dict[str, Any]]]
CACHE_TTL_DAYS = 14
_HANDLE_RE = re.compile(r"^[a-z0-9._]{2,30}$")
_STOPWORDS = {"de", "del", "la", "las", "los", "el", "y", "e", "provincia", "ciudad", "nacional"}


def _norm(text: object) -> str:
    value = unicodedata.normalize("NFKD", str(text or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(text: object) -> List[str]:
    return [t for t in _norm(text).split() if len(t) >= 3 and t not in _STOPWORDS]


def _mentions(text_norm: str, name: str) -> bool:
    name_norm = _norm(name)
    return bool(name_norm) and re.search(rf"(?<![a-z0-9]){re.escape(name_norm)}(?![a-z0-9])", text_norm) is not None


class InstagramTagResolver:
    def __init__(self, config_path: Path, cache_path: Path, lookup: Lookup) -> None:
        self.cache_path = Path(cache_path)
        self.lookup = lookup
        try:
            payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            payload = {}
        self.enabled = bool(payload.get("enabled", True))
        self.max_tags = int(payload.get("max_tags") or 3)
        minimum = payload.get("min_followers") or {}
        self.min_followers = {
            "persona_publica": int(minimum.get("persona_publica") or 20000),
            "institucion": int(minimum.get("institucion") or 5000),
        }
        self.institution_only = {_norm(c) for c in payload.get("institution_only_categories") or ["policiales", "justicia"]}
        self.accounts = [a for a in payload.get("accounts") or [] if isinstance(a, dict) and a.get("handle")]

    # -- API ------------------------------------------------------------------

    def resolve(self, *, text: str, personas: Iterable[Any], category: str) -> List[str]:
        if not self.enabled:
            return []
        text_norm = _norm(text)
        only_institutions = _norm(category) in self.institution_only
        tags: List[str] = []

        def add(handle: str) -> None:
            if handle not in tags and len(tags) < self.max_tags:
                tags.append(handle)

        for account in self.accounts:
            kind = str(account.get("kind") or "institucion")
            if only_institutions and kind != "institucion":
                continue
            if any(_mentions(text_norm, alias) for alias in account.get("aliases") or []):
                add(str(account["handle"]).lower())

        for persona in personas or []:
            if not isinstance(persona, dict):
                continue
            kind = str(persona.get("tipo") or "").strip().lower()
            name = str(persona.get("nombre") or "").strip()
            handle = str(persona.get("usuario_instagram") or "").strip().lstrip("@").lower()
            if kind not in self.min_followers or not name or not _HANDLE_RE.match(handle):
                continue
            if only_institutions and kind != "institucion":
                continue
            if not _mentions(text_norm, name):
                continue  # la IA nombro a alguien que no esta en la nota
            if self._verified(handle, name=name, kind=kind):
                add(handle)
        return tags

    # -- verificacion ----------------------------------------------------------------

    def _verified(self, handle: str, *, name: str, kind: str) -> bool:
        info = self._account(handle)
        if not info:
            return False
        if int(info.get("followers_count") or 0) < self.min_followers[kind]:
            return False
        account_tokens = set(_tokens(f"{info.get('name') or ''} {handle}"))
        wanted = _tokens(name)
        if not wanted:
            return False
        def found(token: str) -> bool:
            return token in account_tokens or any(token in a for a in account_tokens)

        if kind == "persona_publica":
            # Nombre y apellido: el apellido siempre; el nombre tambien, salvo en cuentas masivas
            # (>= 1 M seguidores), donde el apodo es comun ("Leo Messi" por "Lionel Messi").
            if len(wanted) < 2 or not found(wanted[-1]):
                return False
            followers = int(info.get("followers_count") or 0)
            return all(found(t) for t in wanted[:-1]) or followers >= 1_000_000
        present = sum(1 for t in wanted if found(t))
        return present / len(wanted) >= 0.6

    def _account(self, handle: str) -> Optional[Dict[str, Any]]:
        cache = self._read_cache()
        entry = cache.get(handle)
        now = datetime.now(timezone.utc)
        if entry:
            try:
                fresh = now - datetime.fromisoformat(str(entry.get("checked_at"))) < timedelta(days=CACHE_TTL_DAYS)
            except ValueError:
                fresh = False
            if fresh:
                return entry.get("account")
        try:
            account = self.lookup(handle)
        except Exception as exc:  # error de red/API: no se etiqueta y no se guarda
            LOGGER.warning("ig_tags: no se pudo verificar @%s: %s", handle, str(exc)[:160])
            return None
        cache[handle] = {"checked_at": now.replace(microsecond=0).isoformat(), "account": account}
        self._write_cache(cache)
        return account

    def _read_cache(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_cache(self, cache: Dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("ig_tags cache: %s", exc)
