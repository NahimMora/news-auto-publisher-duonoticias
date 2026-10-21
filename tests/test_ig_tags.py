"""Etiquetas de Instagram: solo cuentas curadas o verificadas, nunca adivinadas."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from publishers.ig_tags import InstagramTagResolver

CONFIG = """
enabled: true
max_tags: 3
min_followers: {persona_publica: 20000, institucion: 5000}
institution_only_categories: [policiales, justicia]
accounts:
  - {handle: policiadesalta, kind: institucion, aliases: ["Policia de Salta"]}
  - {handle: gustavosaenzok, kind: persona_publica, aliases: ["Gustavo Saenz"]}
"""

ACCOUNTS = {
    "emimartinez": {"username": "emimartinez", "name": "Emiliano Dibu Martínez", "followers_count": 9_000_000},
    "casarosada": {"username": "casarosada", "name": "Casa Rosada", "followers_count": 506},
    "leomessi": {"username": "leomessi", "name": "Leo Messi", "followers_count": 500_000_000},
    "otromessi": {"username": "otromessi", "name": "Leo Messi", "followers_count": 30_000},
    "otrojuan": {"username": "otrojuan", "name": "Juan Pérez Gómez", "followers_count": 90_000},
}


class TagResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_tags_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "tags.yaml").write_text(CONFIG, encoding="utf-8")
        self.lookups = []

        def lookup(handle):
            self.lookups.append(handle)
            return ACCOUNTS.get(handle)

        self.resolver = InstagramTagResolver(self.tmp / "tags.yaml", self.tmp / "cache.json", lookup)

    def test_curated_alias_in_text_is_tagged(self) -> None:
        tags = self.resolver.resolve(text="Gustavo Sáenz y la Policía de Salta presentaron el operativo", personas=[], category="politica")
        self.assertEqual(tags, ["policiadesalta", "gustavosaenzok"])

    def test_only_institutions_in_crime_news(self) -> None:
        tags = self.resolver.resolve(text="Gustavo Sáenz habló; la Policía de Salta detuvo a dos", personas=[], category="policiales")
        self.assertEqual(tags, ["policiadesalta"])

    def test_ai_handle_needs_verified_matching_account(self) -> None:
        personas = [{"nombre": "Emiliano Martínez", "tipo": "persona_publica", "usuario_instagram": "@emimartinez"}]
        tags = self.resolver.resolve(text="Emiliano Martínez sufrió un golpe", personas=personas, category="deportes")
        self.assertEqual(tags, ["emimartinez"])

    def test_nickname_only_for_massive_accounts(self) -> None:
        text = "Lionel Messi hizo dos goles"
        ok = [{"nombre": "Lionel Messi", "tipo": "persona_publica", "usuario_instagram": "leomessi"}]
        small = [{"nombre": "Lionel Messi", "tipo": "persona_publica", "usuario_instagram": "otromessi"}]
        self.assertEqual(self.resolver.resolve(text=text, personas=ok, category="deportes"), ["leomessi"])
        self.assertEqual(self.resolver.resolve(text=text, personas=small, category="deportes"), [])

    def test_small_or_mismatched_accounts_are_rejected(self) -> None:
        personas = [
            {"nombre": "Casa Rosada", "tipo": "institucion", "usuario_instagram": "casarosada"},
            {"nombre": "Pedro Gómez", "tipo": "persona_publica", "usuario_instagram": "otrojuan"},
        ]
        tags = self.resolver.resolve(text="Desde la Casa Rosada confirmaron; Pedro Gómez opinó", personas=personas, category="politica")
        self.assertEqual(tags, [])

    def test_person_not_in_article_is_never_looked_up(self) -> None:
        personas = [{"nombre": "Emiliano Martínez", "tipo": "persona_publica", "usuario_instagram": "emimartinez"}]
        self.assertEqual(self.resolver.resolve(text="Otra nota sin esa persona", personas=personas, category="deportes"), [])
        self.assertEqual(self.lookups, [])

    def test_private_people_are_ignored(self) -> None:
        personas = [{"nombre": "Juan Pérez Gómez", "tipo": "particular", "usuario_instagram": "otrojuan"}]
        self.assertEqual(self.resolver.resolve(text="Juan Pérez Gómez fue detenido", personas=personas, category="sociedad"), [])

    def test_verifications_are_cached(self) -> None:
        personas = [{"nombre": "Emiliano Martínez", "tipo": "persona_publica", "usuario_instagram": "emimartinez"}]
        for _ in range(3):
            self.resolver.resolve(text="Emiliano Martínez atajó", personas=personas, category="deportes")
        self.assertEqual(self.lookups, ["emimartinez"])


if __name__ == "__main__":
    unittest.main()
