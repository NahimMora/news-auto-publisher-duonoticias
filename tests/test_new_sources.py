"""Fuentes locales de 2026-10-22 (De Frente Salta, SaltaNews) y tope de 6 min del video original."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extractors.news.gendarmeria import is_salta
from extractors.news.medioscms import MediosCmsExtractor
from extractors.news.saltanews import SaltaNewsExtractor, youtube_ids
from storage.models import Asset
from utils.media_resolver import MediaResolver, VideoUnavailable

DEFRENTE = """<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":"Video: choque en zona oeste",
"description":"Los pasajeros auxiliaron a la victima.","image":"https://defrentesalta.com.ar/download/foto.webp",
"datePublished":"2026-10-21T20:06:00-03:00"}</script></head><body>
<div class="fullpost__main"><h1 class="fullpost__titulo">Video: choque en zona oeste</h1>
<div class="fullpost__cuerpo"><p>Una mujer que viajaba en moto resulto herida durante la tarde de hoy en la zona oeste.</p>
<p><video controls src="/download/multimedia.video.abc.mp4"></video></p>
<p>Segun describio una vecina en un mensaje enviado al WhatsApp de Defrentesalta, los pasajeros ayudaron.</p></div></div>
<div class="relacionadas"><video src="/download/otra-nota.mp4"></video></div></body></html>"""

# Plantilla nueva del sitio desde 2026-10-23 (articulo-*), con tarjeta de otra nota dentro del cuerpo.
DEFRENTE_2 = """<html><head><script type="application/ld+json">{"@type":"NewsArticle","headline":"Video: hinchas demorados",
"description":"Operativo en el estadio.","image":"https://defrentesalta.com.ar/download/foto2.webp",
"datePublished":"2026-10-24T11:45:00-03:00"}</script></head><body>
<header><h1>Video: hinchas demorados</h1><div class="articulo-copete"><div>Operativo en el estadio.</div></div></header>
<div class="articulo-con-columna"><div class="articulo-principal"><div class="articulo-lectura"><div class="articulo-cuerpo">
<figure class="image"><img src="/download/foto2.webp"><figcaption>El estadio.</figcaption></figure>
<p>Varios hinchas de Juventud Antoniana fueron demorados anoche en el marco del operativo policial.</p>
<div class="medios-widget post"><p>Otra nota del medio que no tiene nada que ver con este hecho puntual.</p></div>
<h2>Requisa</h2><p>Durante la requisa preventiva realizada en el estadio se secuestraron elementos prohibidos.</p>
<h3>Video</h3><p><video src="/download/multimedia.video.def.mp4"></video></p></div></div></div></div>
<div class="relacionados"><video src="/download/otra-nota.mp4"></video></div></body></html>"""

SALTANEWS = r"""<html><head><script type="application/ld+json">[{"@type":"NewsArticle","headline":"El IPV sortea hoy",
"description":"Sorteo de ubicacion","image":["https://cdn.test/ipv.webp"],"datePublished":"2026-10-21T10:00:00Z"}]</script></head>
<body><article><h1>El IPV sortea hoy la ubicacion de las 93 viviendas</h1><div class="cuerpo-nota">
<p>El Instituto Provincial de Vivienda sortea este miercoles la ubicacion de las viviendas de Rosario de Lerma.</p>
<p>Lee tambien: otra nota</p></div></article>
<script>self.__next_f.push([1,"66:I[634140,[\"$8\",\"$9\",\"$30\"],\"VideoDeYouTube\"]\n5a:[\"$\",\"$L66\",null,{\"id\":\"ckPQbycBqHY\",\"titulo\":\"IPV\"}]"])</script>
<script>self.__next_f.push([1,"70:I[1,[\"$8\"],\"Otro\"]\n7a:[\"$\",\"$L70\",null,{\"id\":\"zzzzzzzzzzz\"}]"])</script>
</body></html>"""


class NewSourceParserTests(unittest.TestCase):
    def test_defrente_takes_own_video_and_body(self) -> None:
        extractor = MediosCmsExtractor("defrentesalta", "https://defrentesalta.com.ar", listing_pages=["/historial"])
        detail = extractor.parse_article_html(DEFRENTE, "https://defrentesalta.com.ar/contenido/1/x")
        self.assertEqual(detail["titulo"], "Video: choque en zona oeste")
        self.assertEqual([v["url"] for v in detail["video_candidates"]], ["https://defrentesalta.com.ar/download/multimedia.video.abc.mp4"])
        self.assertEqual(len(detail["parrafos"]), 1)  # el pedido de WhatsApp del medio no es parte del hecho
        self.assertEqual(detail["imagenes_url"], ["https://defrentesalta.com.ar/download/foto.webp"])

    def test_defrente_new_template_2026_10_23(self) -> None:
        extractor = MediosCmsExtractor("defrentesalta", "https://defrentesalta.com.ar", listing_pages=["/historial"])
        detail = extractor.parse_article_html(DEFRENTE_2, "https://defrentesalta.com.ar/contenido/2/x")
        self.assertEqual(detail["titulo"], "Video: hinchas demorados")
        self.assertEqual(len(detail["parrafos"]), 2)  # la tarjeta medios-widget queda afuera
        self.assertEqual([v["url"] for v in detail["video_candidates"]], ["https://defrentesalta.com.ar/download/multimedia.video.def.mp4"])

    def test_saltanews_reads_youtube_id_from_the_component_payload(self) -> None:
        self.assertEqual(youtube_ids(SALTANEWS), ["ckPQbycBqHY"])  # el otro componente no es un video
        detail = SaltaNewsExtractor().parse_article_html(SALTANEWS, "https://www.saltanews.com.ar/ipv")
        self.assertEqual(detail["video_candidates"][0]["url"], "https://www.youtube.com/watch?v=ckPQbycBqHY")
        self.assertEqual(detail["video_candidates"][0]["kind"], "youtube")
        self.assertEqual(len(detail["parrafos"]), 1)
        self.assertEqual(detail["imagenes_url"], ["https://cdn.test/ipv.webp"])

    def test_saltanews_article_urls(self) -> None:
        extractor = SaltaNewsExtractor()
        self.assertTrue(extractor._is_article_url("https://www.saltanews.com.ar/ipv-sorteo-ubicacion-93-viviendas"))
        self.assertFalse(extractor._is_article_url("https://www.saltanews.com.ar/videos"))
        self.assertFalse(extractor._is_article_url("https://www.saltanews.com.ar/horoscopo"))


class GendarmeriaTests(unittest.TestCase):
    def test_only_salta_procedures(self) -> None:
        self.assertTrue(is_salta("Salta: Gendarmes detuvieron a dos personas", ""))
        self.assertTrue(is_salta("Tres procedimientos en Orán: secuestraron hojas de coca", ""))
        self.assertTrue(is_salta("Incautaron una tonelada de hojas de coca", "El camion fue detenido en Aguas Blancas."))
        self.assertFalse(is_salta("Chaco: Hallaron 1.000 atados de cigarrillos", "Venian desde Salta."))
        self.assertFalse(is_salta("En La Rioja incautaron mercaderia", ""))
        self.assertFalse(is_salta("Santiago del Estero Detuvieron a dos mujeres", ""))
        self.assertFalse(is_salta("Buenos Aires: descubrieron un bunker", "Saltaron el muro."))  # "saltaron" no es Salta


class SourceLengthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_len_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.resolver = MediaResolver(self.tmp, max_seconds=90, trim_long=True, max_source_seconds=360)

    def test_declared_program_is_rejected_without_download(self) -> None:
        asset = Asset(kind="video", remote_url="https://vid.test/programa.mp4", duration_seconds=3000, meta={"video_kind": "mp4"})
        with patch.object(self.resolver, "resolve") as resolve:
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve_asset(asset)
        self.assertEqual(ctx.exception.reason, "source_too_long")
        resolve.assert_not_called()

    def test_long_youtube_is_rejected_from_metadata(self) -> None:
        with patch.object(self.resolver, "_ytdlp_info", return_value={"duration": 5118}), patch("subprocess.run") as run:
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://www.youtube.com/watch?v=-Xi-oqgdh5M", "youtube")
        self.assertEqual(ctx.exception.reason, "source_too_long")
        run.assert_not_called()  # no se baja nada

    def test_live_stream_is_rejected(self) -> None:
        with patch.object(self.resolver, "_ytdlp_info", return_value={"is_live": True}):
            with self.assertRaises(VideoUnavailable) as ctx:
                self.resolver.resolve("https://www.youtube.com/watch?v=livelivexxx", "youtube")
        self.assertEqual(ctx.exception.reason, "source_too_long")


if __name__ == "__main__":
    unittest.main()
