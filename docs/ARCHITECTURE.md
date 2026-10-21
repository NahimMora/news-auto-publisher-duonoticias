# AutoPublicador Duo - Arquitectura (reestructuracion 2026-10)

Entrada unica: `python -m cli.main`. Orquestador: `jobs/pipeline.py` (`DuoPipeline.run_cycle`).
Informe completo de la reestructuracion: `docs/REESTRUCTURACION_2026_10.md`.

## Configuracion

| Archivo | Que define |
|---|---|
| `config/sources.yaml` | Fuentes activas, grupo de cupo (`local`, `national`, `paparazzi`, `x_feed`), `requires_video`, `watermark_policy`, `official`, feeds |
| `config/editorial_scoring.yaml` | Ciclo horario, cupos 6/2/2 (max 10; cupos libres en 0), cola de 12 h, vigencia por grupo, pesos/umbrales de relevancia, recorte de video, version de prompts, tarifas de IA |
| `config/editorial_policy.yaml` | Linea editorial (documental; el prompt vive en `editorial/prompting.py`) |
| `config/watermarks/` | Mascaras de las marcas de agua de El Tribuno y Que Pasa Salta |
| `config/certs/` | Intermedio Sectigo que no envia prensa.policiadesalta.gob.ar |

`storage/editorial_config.py` es el unico lector tipado de esos YAML.

## Fuentes

| Fuente | Grupo | Extractor | Video |
|---|---|---|---|
| El Tribuno | local | `extractors/news/eltribuno.py` (feed `/feed`, iframe onvideo.news -> HLS) | opcional; marca de agua -> descarte |
| Informate Salta | local | `extractors/news/informatesalta.py` (RSS + `<video>` de portada Tadevel, `data-tadevel-lazy-attrs`) | opcional; franja azul -> recorte |
| Que Pasa Salta | local | `extractors/news/quepasasalta.py` (portada/secciones, tuit incrustado, JSON-LD) | opcional; marca de agua -> descarte |
| Gobierno de Salta | local, oficial | `extractors/news/saltagob.py` | opcional |
| Policia de Salta | local, oficial | `extractors/news/wordpress.py` (REST `?rest_route=`) | opcional |
| Municipalidad de Salta | local, oficial | `extractors/news/wordpress.py` (REST `/wp-json/`) | opcional |
| Paparazzi | paparazzi | `extractors/news/paparazzi.py` (WP REST + JW Player de la pagina) | obligatorio |
| TN / Infobae | national | `extractors/news/arc.py` (`Fusion.globalContent`: genoa / JW Player) | obligatorio |
| Videos de X | x_feed | `extractors/x_video_feed.py` + `extractors/x/service.py` (solo links del intercambio de HolaSalta) | obligatorio |

Deteccion de video comun: `extractors/news/media.py` (portada, cuerpo, JSON-LD, Arc, `video`/`source`
con `src`/`data-*`, iframes, JW Player, tuits incrustados). Los extractores reciben `known(url)` y no
vuelven a bajar notas ya procesadas.

## Ciclo (`run_cycle`)

1. Recuperacion: piezas a medio producir vuelven a la cola; publicaciones "en vuelo" se reconcilian.
2. Vencimiento: `queued/retry/selected` con mas de 12 h desde su primer ingreso elegible -> `expired`.
3. Recopilacion de fuentes activas + intercambio de HolaSalta.
4. `jobs/content_policy.py`: fuente activa, validez (no portadas/suscripciones/vivos), texto minimo,
   vigencia por grupo, video obligatorio. Sin listas de temas.
5. `jobs/events.py`: el mismo hecho de varios medios es un acontecimiento (`news_events`); se queda la
   mejor version; si el hecho ya se publico, solo vuelve como actualizacion material.
6. Marca de agua en la imagen principal (`utils/watermark.py`) cuando la nota no tiene video.
7. `jobs/relevance.py`: lotes de 12 notas por llamada a Gemini; puntaje 0-100 calculado localmente.
8. Cola: puntaje >= umbral del grupo -> `queued` con vencimiento a 12 h.
9. `jobs/allocation.py`: 6 locales, 2 nacionales, 2 Paparazzi (max 10; los cupos libres estan en 0 desde 2026-10-18),
   un hecho por ciclo, tope por fuente, limite de publicacion de Instagram.
10. Produccion de lo elegido: `utils/media_resolver.py` (descarga verificada con cache, primeros 123 s),
    franja de Informate / marca de agua en video, `editorial/service.py` (caption canonico con cache),
    `formatter/service.py` (reel con el video completo, tope 90 s, plantilla `video` del motor `motion/` + portada 9:16
    apta para el recorte 4:5 del feed; posts estaticos sin fotos repetidas ni con marca de agua).
11. Validacion (`_formatted_publish_block_reason`): archivos reales, duraciones, caption < 2000.
12. Publicacion IG + FB con el mismo paquete; resultado por plataforma; idempotencia por plataforma.
13. Registro: `queue_events`, `llm_usage`, `cycles`, `web_articles` (preparado, sin publicar).

## Estados de una nota

`extracted` (candidata) -> `queued` (pendiente) -> `selected` -> `editorialized`/`formatted`/`scheduled`
(procesando) -> `published`. Salidas: `discarded`, `duplicate`, `expired`, `review` (marca ambigua),
`retry` (error recuperable). Cada transicion queda en `queue_events` con su motivo.

## Persistencia (SQLite, migraciones aditivas)

Tablas nuevas: `news_events`, `queue_events`, `llm_usage`, `cycles`, `web_articles`. Columnas nuevas en
`content_items`: `event_key`, `event_role`, `source_group`, `relevance_*`, `queue_entered_at`,
`queue_expires_at`, `cycle_id`, `media_json`, `eligibility_json`, `editorial_cache_key`. No se borra historial.

## Publicacion

- `publishers/meta_api.py`: IG reel (con `cover_url` y `user_tags`) / imagen / carrusel; FB recibe el mismo
  caption. FB no publica carruseles de video por API: va el primer tramo como video.
- Idempotencia: `in_flight` antes de cada llamada; reconciliacion por caption exacto; `ambiguous` si no
  se puede verificar.
- Limites de tasa compartidos: `publishers/rate_limits.py`.
- Etiquetas: `publishers/ig_tags.py` + `config/instagram_tags.yaml` (cuentas curadas o verificadas con
  `business_discovery`; nunca particulares; en policiales/justicia solo instituciones). FB no lleva etiquetas.
- Musica: la API no permite canciones de la biblioteca de Instagram; opcional `DUO_REEL_MUSIC_PATH`
  (archivo con licencia) como fondo a bajo volumen.
- Web futura: `publishers/web_prep.py` arma `web_articles`; la entrega (`publishers/duo_web.py`) sigue apagada.

## Produccion

Solo en FERNANDO con `DUO_LIVE_PUBLISH_ENABLED=true` y `--live` (`utils/machine_guard.py`).
Servicio: `docs/OPERATIONS.md`.
