# Reestructuración integral de DUO Noticias (2026-10-17/18)

Informe técnico verificable. Todo lo que figura como "probado" tiene una prueba automática
(`python -m pytest`, 187 tests) o una corrida real documentada acá. Lo que no se pudo probar
está en la sección 14.

## 1. Resumen de implementación

- Ciclo **horario** nuevo (`jobs/pipeline.py::run_cycle`) que reemplaza las franjas fijas y el cupo
  diario 6+4. El orden va de lo barato a lo caro: recuperación → vencimiento → recopilación →
  filtros técnicos → acontecimientos → marca de agua → relevancia por lotes → cola (12 h) →
  cupos (máximo 10) → producción → validación → publicación → registro.
- Fuentes reorganizadas: 3 medios salteños, 3 fuentes oficiales, Paparazzi, TN e Infobae, y videos
  de X solo desde el intercambio de HolaSalta.
- Extracción de **videos reales** en portada, cuerpo, JSON-LD, Arc/Fusion, `video`/`source` con
  `data-*`, iframes, JW Player y tuits incrustados. La descarga está verificada con ffprobe y cacheada.
- **Recorte mecánico**: hasta 60 s el video va entero; si es más largo, se usan los tramos 0-60 y
  60-120 en un carrusel de dos videos.
- Se retiraron los reels con fotos animadas, el scraping autónomo de cuentas de X, las fuentes
  eliminadas, el scoring viral por palabras clave, las listas de temas y el scheduler por franjas.
- **Relevancia** 0-100 interpretable, con componentes que devuelve Gemini en lotes de 12 notas y un
  puntaje calculado localmente con pesos configurables.
- **Acontecimientos**: deduplicación entre medios y seguimiento de actualizaciones, todo local.
- **Caption canónico único** para Instagram y Facebook, con caché y validación local.
- **Marcas de agua**: descarte local para El Tribuno y Qué Pasa Salta; recorte de la franja de Informate.
- Registro de costos de IA (`llm_usage`), transiciones (`queue_events`), ciclos (`cycles`) y
  artículos preparados para la futura web (`web_articles`).

## 2. Fuentes

| Fuente | Estado | Grupo / cupo | Regla |
|---|---|---|---|
| El Tribuno | mantenida, extractor rehecho | local (6) | video opcional; marca de agua → descarte |
| Informate Salta | **nueva** | local | video de portada; franja azul → recorte |
| Qué Pasa Salta | **nueva** | local | tuit incrustado → video; marca de agua → descarte |
| Gobierno de Salta (salta.gob.ar/prensa) | **nueva** | local, oficial | umbral 65 (más exigente) |
| Policía de Salta (prensa.policiadesalta.gob.ar) | **nueva** | local, oficial | umbral 65 |
| Municipalidad de Salta (prensa.municipalidadsalta.gob.ar) | **nueva** | local, oficial | umbral 65 |
| Paparazzi | mantenida, prioridad mayor | paparazzi (2) + libres | solo con video real |
| TN, Infobae | mantenidas | national (2 entre ambas) | solo con video real; umbral 60 |
| Videos de X (HolaSalta) | mantenido | x_feed: libres, o locales si el hecho es salteño | sin contexto → no se publica |

**Eliminadas del flujo automático y del código:** Nuevo Diario de Salta, Fiscales Penales Salta,
Justicia Salta, Noticias Argentinas, Minuto Uno, Elonce, Ámbito, Aries Online y Elonce Salta, además
del scraping de cuentas de X (TTendenciaX, BoludoscnAmarok, ceciarmy, therealbuni, `x.com/home`).

Se borraron sus extractores (`extractors/news/{nuevodiario,fiscalespenalesalta,justiciasalta,
ariesonline,eloncesalta,rss_html}.py`), `scrapping/`, `extractor_x/`, las estrategias Playwright y
yt-dlp por perfil, `jobs/manual_x_video_flow.py`, la UI de X y los lanzadores paralelos
(`INICIAR_PIPELINE.bat`, `LOOP_24_7.bat`, `pipeline_runner.py`). La política descarta como
`fuente_inactiva` cualquier fila histórica de esas fuentes que llegue a una etapa activa. El
historial y las publicaciones previas se conservan.

Hallazgos de la investigación de fuentes:
- El RSS configurado de Infobae daba 404; el correcto es `/arc/outboundfeeds/rss/`. Ese feed mezcla
  ediciones de México, Perú, Colombia y otros países, que ahora se excluyen por ruta.
- TN sí expone MP4 directos (`vod.vodgc.net`), aunque LVR lo había descartado. El video de la nota se
  toma de `Fusion.globalContent`, no del HTML: el widget de recomendados repite el mismo video en
  notas distintas.
- Paparazzi tiene el video en la plantilla de la página (JW Player), no en `content.rendered`. Por
  eso antes nunca se detectaba video y todas sus notas se perdían.
- La Policía no envía su certificado intermedio. Se agrega el intermedio público de Sectigo en
  `config/certs/` (`utils/tls.py`), sin desactivar la verificación TLS.

## 3. Multimedia

`extractors/news/media.py` detecta, y `utils/media_resolver.py` resuelve:
- `mp4` directo (Informate, TN genoa, Infobae/Paparazzi JW Player);
- `hls` (`.m3u8`) con ffmpeg;
- `onvideo` (El Tribuno): iframe → manifiesto HLS;
- `jwplayer`: media id → API pública → MP4 y duración;
- `tweet`: tuit incrustado en una nota (Qué Pasa) o link del intercambio de HolaSalta → yt-dlp,
  una URL puntual;
- `youtube`: se intenta, pero YouTube exige verificación anti-bot (ver 14).

Verificación: ffprobe confirma que hay pista de video, que es legible y que dura al menos 5 s (los
previews animados de 2 s de Qué Pasa se descartan). Solo se baja lo que se usa (primeros 123 s).
Caché por URL en `data/media_cache/`: un video, o un "inutilizable", no se vuelve a bajar en el
ciclo siguiente.

Prioridad: si hay video válido, la pieza es audiovisual. Sin video, las fuentes locales usan imagen o
carrusel con el formato existente, y Paparazzi, TN e Infobae se descartan. No hay reel con fotos:
`MotionEngine.render_reel` se niega a renderizar sin un video real.

Recorte (`utils/video_clips.py`):
- 40 s → un reel de 40 s;
- 90 s → carrusel 0-60 y 60-90;
- 23 min → carrusel 00:00-01:00 y 01:00-02:00;
- un remanente menor a 5 s no forma un segundo tramo.

Sin transcripción ni selección por IA. Las plantillas no se tocaron: cada tramo se renderiza con
`motion/` (Editorial o Breaking) y, si el motor falla, con el formateador legado.

Prueba real: un video de Paparazzi (JW Player, 224 s) se descargó en sus primeros 123 s y salió como
dos tramos de 60,0 s, 1080x1920, con audio, con la plantilla existente (fuente en la barra inferior),
en 311 s. Pasó la validación previa a publicar.

## 4. Marcas de agua

`utils/watermark.py`: detección local, sin Gemini.

- **El Tribuno y Qué Pasa Salta** estampan su logo y su nombre en blanco semitransparente. El
  detector usa la máscara real del logo (`config/watermarks/`) como núcleo "trazo menos anillo" a
  varias escalas: una capa blanca translúcida aclara el trazo respecto de su borde, sea cual sea el
  fondo.
- **Calibración** con 25 fotos reales del 17/10:
  - El Tribuno: positivos entre 25,8 y 31,7; negativos ≤ 14,5. Umbral 20.
  - Qué Pasa: positivos con puntaje ≥ 25,9 y fracción ≥ 0,82, más uno ambiguo (23,3 / 0,76).
  - Ningún falso positivo.
- **Decisión**: marca clara → `discarded` antes de gastar evaluación; caso ambiguo → `review` (nunca
  se publica solo); video → mediana temporal de 9 cuadros más cuadros sueltos. La imagen de
  "sin foto" de El Tribuno (su logo) también se descarta.
- **Excepción de Informate**: se detecta la franja azul inferior fila por fila desde abajo y se
  recorta exactamente esa altura más 2 px (probado: 39 px de 514, el resto intacto). Si la franja
  supera el 12 % del alto, se descarta ese video y la nota sigue con imagen.

## 5. LVR (La Voz Riojana)

`C:\LBR` no existe; el proyecto está en `C:\LVR` y lo estudié solo en modo lectura. `git status` en
LVR quedó sin cambios. Su único commit nuevo durante la sesión (20:05) no salió de este trabajo.
Archivos estudiados:
- deduplicación: `utils/news_dedup.py`, `utils/editorial_router.py` (topic_key, actualización material);
- historias: `editorial_context/` (story_engine, retrieval, entities) y `docs/STORY_ENGINE.md`;
- servicio y cola: `run_24x7.py`, `utils/durable_queue.py`;
- captions: `utils/social_caption.py`;
- videos: `utils/x_video_reels.py`, `utils/paparazzi_relevance.py`, `utils/jwplayer.py`,
  `scraping/base_infobae.py`, `scraping/base_paparazzi.py`;
- web y costos: `pipeline/node_webapp/*` y `docs/COST_MODEL.md`.

Ideas reutilizadas, adaptadas y no copiadas:
- Jaccard de raíces de 6 letras sobre títulos (umbral 0,5).
- Puntaje de relación explicable por entidades, localidades, términos y cercanía, con evidencia doble
  en policiales, espectáculos y deportes.
- Palabras clave de actualización material.
- Supervisor con lock y tarea programada cada 5 minutos como relanzador.
- Puntaje 0-10 por IA para Paparazzi e internacionales, que acá se generalizó a lotes y componentes.
- JW Player por API pública.
- Video de Infobae por `contentUrl`.
- Modelo de artículo web: título, bajada, cuerpo, SEO, slug, imagen, video y fuentes.

No se copiaron secretos ni configuraciones.

## 6. Deduplicación y seguimiento

`jobs/events.py` + tabla `news_events`. Una nota se compara con las notas de las últimas 72 h:
1. Título similar (Jaccard ≥ 0,5).
2. **Contenido similar**: coseno TF-IDF de título×2 + bajada + inicio del cuerpo ≥ 0,33. Esta
   comparación se agregó al ver que el método de LVR no unía, con texto real, el hecho de las dos
   niñas contado por El Tribuno, Qué Pasa y Policía. Calibración con 77 notas reales: mismo hecho
   entre 0,33 y 0,81; hechos distintos por debajo de 0,30.
3. Relación por entidades. Se ignoran las entidades genéricas (que aparecen en 4 o más notas
   recientes) y las instituciones ("Policía de Salta", "Fiscalía"); un lugar compartido no cuenta
   como entidad del hecho; contención "barrio Miguel Ortiz" ~ "Miguel Ortiz".

Repetición sobre las notas reales: 79 notas → 61 acontecimientos. Uniones correctas: las niñas (3
fuentes), Salvador Mazza, San Benito (3), Juventud Antoniana, Messi (El Tribuno + Infobae), avalancha
en Portillo, código rojo en la ruta 9, fiestas clandestinas, Dibu Martínez (TN + Qué Pasa).

Versión elegida: la más completa (video válido +3, texto, imagen, actualidad). Si llega una mejor
mientras la anterior espera, la reemplaza y **hereda su puntaje y su vencimiento**. Si la elegida
falla (sin video, marca de agua), se promueve la siguiente versión del mismo hecho.

Seguimiento: si el hecho ya se publicó, la nota nueva solo entra si trae datos sustanciales nuevos
(víctima fatal, detención, imputación, condena, hallazgo, cifras nuevas). Entra como
`event_role=update` y el caption cuenta primero el dato nuevo. Si no trae nada nuevo, es `duplicate`.

## 7. Gemini

Auditoría del flujo anterior: una llamada de redacción por cada nota que pasaba el scoring de
palabras clave (prompt de unos 7.760 caracteres, unos 1.940 tokens, con bloques de "señales de
performance" y JSON de scoring), más una llamada extra de diapositivas por cada nota de Noticias
Argentinas. En la corrida real del 17/10 hubo **29 llamadas para 10 piezas publicadas**, y el 60 %
de las redacciones (15 de 25) nunca se publicó.

Flujo nuevo:
- **Sin IA**: fuente, URL conocida, fecha, validez, video obligatorio, marca de agua, duplicados,
  hashtags, validación del caption y cálculo del puntaje. Una nota nacional sin video nunca llega a
  Gemini (probado en `test_national_without_video_never_reaches_gemini`).
- **Relevancia**: una llamada cada 12 notas, con claves cortas y salida estructurada
  (`responseSchema`), temperatura 0. Las versiones duplicadas heredan el puntaje del acontecimiento.
- **Caption**: solo para las piezas elegidas, una por pieza (no hay dos llamadas por red); prompt de
  unos 2.800 caracteres; caché por versión de prompt, modelo y contenido. Un reintento no regenera
  (probado en `test_caption_is_cached_on_retry`).
- **Modelo**: `gemini-3.1-flash-lite`, el actual. Modelos disponibles en el proyecto:
  2.5-flash-lite, 3.1-flash-lite y 3.5-flash-lite. No cambié de modelo sin comparar calidad.

Medición en la simulación real del 18/10 (143 notas ingresadas, 63 evaluadas, 10 producidas):

| Propósito | Llamadas | Notas | Tokens de entrada | Tokens de salida |
|---|---:|---:|---:|---:|
| Relevancia por lotes | 6 | 63 | 16.165 | 5.682 |
| Caption | 10 | 10 | 16.737 | 3.970 |

Resultado: unas **1,6 llamadas por pieza producida** (antes ~2,9) y unos 3.300 tokens de entrada por
pieza (antes ~5.600, estimado por largo de prompt), con evaluación por IA de todas las notas
elegibles en lugar de palabras clave.

El costo en dólares no se calcula porque las tarifas (`llm.rates_per_million` en
`config/editorial_scoring.yaml`) no están cargadas; no las invento. Con las tarifas cargadas,
`python -m cli.main llm-usage` lo estima con tokens reales.

## 8. Cola y cupos

- Un ciclo por hora alineado al minuto 0. Si se corrió el ciclo de esta hora, no se repite.
- Cupos por ciclo:
  - local 6 (máximo 3 por fuente);
  - nacional 2, para TN e Infobae juntos;
  - Paparazzi 2;
  - libres: **0** desde el 2026-10-18 (decisión del propietario); si se reactivan, nunca van a nacionales;
  - techo de 10.
- Un acontecimiento ocupa un lugar por ciclo. Nada bajo el umbral rellena cupos.
- Una pieza en Instagram y Facebook cuenta una vez; el resultado se registra por plataforma.
- Cola persistente en SQLite: `queue_entered_at` es el primer ingreso elegible y
  `queue_expires_at = +12 h`. No se reinicia con un nuevo scraping ni con un cambio de versión.
  Vencida → `expired`, nunca se publica.
- Reintentos limitados (`max_retries: 3`). Un error de Gemini, render o red devuelve la pieza a la
  cola (`retry`).
- Presupuesto de producción de 45 min por ciclo: lo que no llega vuelve a la cola sin perder lugar.
- Antes de asignar se consulta el límite de publicación de Instagram y se usa como techo (ver 14).

Pruebas (`tests/test_cycle.py`, todas pasan):
- 18 elegibles → 10 publicadas (6 local, 2 nacional, 2 Paparazzi); la tercera y cuarta
  nacional quedan pendientes; la débil se descarta.
- Una fuente con poco contenido → no se rellena.
- 5 de Paparazzi → 2 por ciclo; la quinta sobrevive a un reinicio y sale dos ciclos después.
- Vencimiento exacto de 12 h → `expired`, sin publicar.
- Mismo hecho en dos medios → 1 publicación.
- Actualización material → `update`.
- Nota ya publicada que reaparece → no se reprocesa.
- Instagram bien y Facebook mal, con reinicio en el medio → Instagram 1 vez, Facebook reintentado.
- Video de X sin contexto → no se publica.

## 9. Instagram/Facebook: caption compartido

Un solo `FormattedPackage` con un solo `caption` se envía a ambas plataformas
(`_publish_platform_records`). No hay un segundo texto ni una segunda llamada a Gemini. Verificado
en `test_quotas_with_more_than_twelve_eligible`: las 12 piezas tienen el caption de Instagram
idéntico al de Facebook y menor a 2.000 caracteres. Los resultados se guardan por plataforma en
`publications`.

Limitación: la API de páginas de Facebook no publica carruseles de video. En ese caso Facebook recibe
el primer tramo como video, con el mismo caption, y queda anotado en la publicación.

## 10. Futura web

- `publishers/web_prep.py` + tabla `web_articles`: un artículo por acontecimiento, armado al
  publicarse en redes sin IA extra.
- Campos: slug estable, título, título y descripción SEO, bajada, párrafos, categoría, tags, imagen
  principal, video, fuentes con URL, caption social y estado `prepared`.
- `news_events` sirve para una línea de tiempo de la historia.
- Interruptor de preparación: `DUO_WEB_PREPARE_ARTICLES` (por defecto 1).
- **La publicación web sigue apagada**: `ENABLE_DUO_WEB=false`, `DUO_WEB_MODE=disabled`. No se
  definió dominio ni CMS. La web de LVR no se tocó.

## 11. Servicios

- Tarea `DuoNoticias-24x7` (FERNANDO, cada 5 minutos como relanzador) →
  `scripts/start_24x7_production.ps1` → `preflight` → `run-24-7 --live`.
- El loop corre un ciclo por hora, con lock de proceso, heartbeat con `last_cycle_id` y recuperación
  de piezas a medio producir.
- **La tarea sigue DESHABILITADA**: no la activé.
- Para probar sin publicar: `python -m cli.main simulate` (base `data/simulation.sqlite3` y estado
  propio del intercambio de HolaSalta). Detalle en `docs/OPERATIONS.md`.

## 12. Código

Nuevos:
- configuración: `config/editorial_scoring.yaml`, `config/watermarks/*`, `config/certs/*`;
- almacenamiento: `storage/editorial_config.py`, `storage/editorial_store.py`;
- extractores: `extractors/news/{media,arc,informatesalta,quepasasalta,saltagob,wordpress}.py`;
- trabajos: `jobs/{events,relevance,allocation}.py`;
- redacción y publicación: `editorial/captions.py`, `publishers/web_prep.py`;
- utilidades: `utils/{media_resolver,watermark,video_clips,tls}.py`;
- tests: `tests/{test_cycle,test_editorial_units,test_video_pieces}.py`.

Reescritos:
- configuración: `config/sources.yaml`, `config/editorial_policy.yaml`, `config/thresholds.yaml` (vacío);
- pipeline y CLI: `jobs/pipeline.py`, `jobs/content_policy.py`, `cli/main.py`;
- redacción: `editorial/prompting.py`, `editorial/service.py`;
- extractores: `extractors/registry.py`, `extractors/x/service.py`,
  `extractors/news/{eltribuno,paparazzi}.py`;
- tests: `test_content_policy`, `test_cli_main`, `test_source_registry`.

Modificados:
- `formatter/service.py`, `formatter/motion_engine.py`;
- `publishers/meta_api.py`;
- `storage/sqlite_store.py`, `storage/settings.py`;
- `utils/llm_client.py`, `extractors/news/{common,html_scraper}.py`;
- documentación.

Eliminados: ver sección 2, más `jobs/{scheduler,salta_priority}.py`, `scoring/`,
`utils/{x_captioner_openai,instagram_reels_only,instagram_carousel_slices,instagram_formatter,political_agent}.py`
y los tests de esos módulos.

## 13. Pruebas

- `python -m pytest`: **187 tests pasan**. Incluyen el contrato Python → esquema de Motion (Node).
- Ciclo simulado real (red real, Gemini real, sin publicar): 143 notas, 56 descartes técnicos,
  15 duplicados, 3 marcas de agua, 63 evaluadas, 14 en cola, 10 seleccionadas y producidas.
  6,5 minutos.
- Render real de dos piezas: un carrusel de video de Paparazzi y un carrusel estático de El Tribuno.
- Fallas encontradas y corregidas durante las pruebas:
  - JSON de relevancia truncado: el lote de 12 excedía el tope de tokens; pasé a claves cortas.
  - Entidades contaminadas por la bajada (`rstrip` borraba el salto de línea).
  - Contención de entidades de igual largo ("Córdoba" ~ "Mendoza").
  - Partes policiales agrupados por jerga institucional.
  - `Path("")` tratado como existente.
  - Fallback pobre ante un 503 de Gemini: ahora es reintento.
  - Títulos en mayúsculas.

### Ejemplo de ciclo simulado (18/10, ~00 h, datos reales)

Entran (10, sin publicar por ser simulación):
- **Local (6):** "Qué dice la Policía sobre las dos niñas…" (Informate; El Tribuno, Qué Pasa y
  Policía quedaron como duplicados del mismo hecho), crimen en Miguel Ortiz (Qué Pasa, 78,5), "El
  pedido urgente por la salteñita…" (Qué Pasa, 76), San Benito (El Tribuno, 71; duplicados de
  Informate y Qué Pasa), suba de alimentos (Informate) y "Apareció Sofía en Salta" (Informate).
- **Paparazzi (2):** Dibu Martínez, golpe en la cabeza (84), con video de 224 s → carrusel de dos
  tramos; video de Fernando Confessore (44,5).
- **Libres (2):** detenido con código rojo en la ruta 9 (Informate; el parte policial es duplicado)
  y calendario de ANSES (Informate).
- **Nacional (0):** ninguna nota con video superó 72. El naufragio en el Paraná (TN) dio 66.

Quedan pendientes (4): obras sociales en hospitales (63), bloqueo de bagayeros en Salvador Mazza
(62), fiestas clandestinas desbaratadas (Informate, 61,5) y el video de la "amante de Emanuel Ortega"
(Paparazzi, 36).

Se descartan, por ejemplo:
- 49 bajo el umbral: actos peronistas (penalidad por política nacional de rutina), Caputo, Brasil,
  inscripciones de UPATecO (rutina institucional) y "síndrome gripal" del Gobierno (64 < 65).
- 56 técnicos: TN e Infobae sin video, resultados deportivos de más de 12 h, Municipalidad sin notas
  de las últimas 24 h, ediciones extranjeras de Infobae.
- 3 por marca de agua de El Tribuno y 1 en revisión por marca ambigua de Qué Pasa.

Videos de HolaSalta: 8 importados. Dos se unieron al mismo hecho de Francia que ya cubría El Tribuno
(bajo umbral). Tres clips partidarios sin contexto ("Gracias Cristina", Manzur…) no se publican. Dos
estaban fuera de vigencia. La persecución en la General Paz dio 51 < 55.

## 13 bis. Ajustes del 2026-10-18 (aprobados por el propietario)

- Se quitaron los 2 cupos libres: techo de **10** por ciclo (6 locales, 2 nacionales, 2 Paparazzi).
  Los videos de HolaSalta sin relación con Salta ya no tienen cupo; los salteños compiten por los locales.
- Recalibración con 13 notas con video, cada una evaluada 3 veces:
  - **Nacional 60**: el hecho grave del día (naufragio en el Paraná) promedió 73,9, con un rango de
    66 a 76,5; lo siguiente promedió 41,6 o menos.
  - **Paparazzi 32**: Dibu 83, Confessore 44, figuras conocidas (Pergolini, Ortega, Caniggia) 32-34,
    notas flojas 27-28.
- Simulación con la configuración nueva: 143 notas, 63 evaluadas, 8 producidas (6 locales + 2
  Paparazzi). Ninguna nacional ese ciclo: la más alta fue un gendarme desaparecido en Neuquén
  (58,5 < 60).
- Los tests ya no pueden escribir en la base real: `tests/conftest.py` fuerza una base temporal. Un
  test viejo, ya eliminado, había dejado dos filas `in_flight` falsas (`content_key=abc`) en la base
  de producción; el primer ciclo las reconcilia como fallidas, sin efecto.
- El flujo nuevo ignora las filas a medio procesar del flujo anterior. Quedan como historial y, si
  la nota reaparece en una fuente activa, se procesa desde cero.

## 13 ter. Primer ciclo vigilado y respaldo de Gemini (2026-10-18)

- Primer ciclo en vivo (`2026-10-18T00`, 10,8 min): 173 notas ingresadas, 60 evaluadas, 9 elegidas
  (6 locales, 1 nacional, 2 Paparazzi). Se publicó 1 pieza (ANSES, Informate Salta), con caption
  idéntico en IG y FB. Las otras 8 volvieron a la cola por HTTP 503 de Gemini ("high demand").
- Respaldo ante 503: si `gemini-3.1-flash-lite` está saturado (después de los reintentos con espera),
  la misma llamada se hace una vez con `gemini-3.5-flash-lite`, el lite disponible de costo más
  parecido (0,30/2,50 frente a 0,25/1,50 USD por millón). `gemini-2.5-flash-lite`, que es más barato,
  devolvió 404: ya no se habilita para cuentas nuevas. En `llm_usage` queda el modelo que respondió y
  `respaldo_por_saturacion_de`.
- Tarifas cargadas por modelo: `llm-usage` estima costos con tokens reales.

## 13 quater. Correcciones tras los primeros posts en vivo (2026-10-18)

Pedidas por el propietario después de revisar los 9 posts del primer ciclo.

1. **Reel = video completo, tope 90 s.** Se eliminaron los carruseles de tramos de 60 s
   (`utils/video_clips.py` borrado). `media.max_reel_seconds: 90`: un video más largo no se usa
   (`too_long`, queda en caché como inutilizable). Si la duración viene declarada (JW Player, Genoa,
   Arc), la nota de Paparazzi/TN/Infobae se descarta antes de evaluarla (`video_mayor_90s`); si no, se
   bajan 92 s y se mide. Las locales con video largo siguen con imagen. Datos de 48 h: entran en 90 s
   5 de 9 videos de Paparazzi, 6 de 8 de TN, 6 de 7 de Infobae y 11 de 14 de X.
2. **"Qué se sabe" sintetizado.** La redacción devuelve `que_se_sabe`: 2 o 3 puntos de hasta 70
   caracteres. Localmente se descartan los de más de 80 (nunca se truncan a mitad de frase) y los que no
   están anclados en la nota.
3. **Reel rediseñado** (plantilla `video`, `motion/src/templates/VideoNews.tsx`). El titular queda fijo
   arriba durante todo el video. El video completo va al centro, sobre el campo violeta de la marca, sin
   fondo desenfocado; los videos verticales van a pantalla completa con velos de lectura. Abajo, los
   puntos de "Qué se sabe" rotan cada 4,5 a 7 s hasta el cierre, con indicador de avance. No queda
   ningún tramo sin texto ni el "vaciado" con el titular abajo. Todo lo importante está entre y=300 y
   y=1620 (recorte 4:5 del feed).
4. **Captions** (prompt `duo-2026-10-v2`):
   - La primera línea es un gancho de hasta 110 caracteres con emoji: lo único visible antes de "más".
   - Siguen 2 a 4 párrafos muy cortos, cada uno con un emoji temático, y un cierre que invita a
     comentar o compartir.
   - En policiales, justicia o gravedad ≥ 6 se quitan los emojis frívolos (😂 🔥 🎉…).
   - Si falta el emoji inicial, se agrega el de la categoría. El texto sin IA también lo lleva.
5. **Marca de agua de El Tribuno que se escapó (San Benito).** El detector comparaba el trazo con el
   promedio del anillo de toda la ventana. Con figuras oscuras delante, la fracción bajaba a 0,56 y no
   llegaba al umbral. Ahora la compara con el anillo cercano: la foto de San Benito da 23,2 / 0,84.
   Recalibración con 26 fotos:
   - Positivos: entre 23 y 36, con fracción ≥ 0,82.
   - Negativos: ≤ 23, con fracción ≤ 0,71.
   - Sin falsos positivos.

   Además, la marca se revisa en **todas** las fotos que se usan, no solo en la primera. Si todas la
   tienen, la pieza se descarta y pasa la siguiente versión del hecho.
6. **Carruseles con la misma foto.** Para cada foto se probaba primero la `og:image` de la nota, así
   que todas terminaban siendo la principal. Ahora va primero la URL propia de cada foto, y se descartan
   duplicadas por dHash (≤ 6 bits). Con una sola foto distinta, el post es una imagen simple.
7. **Portada de video** (plantilla `cover`): una imagen de 1080×1920 hecha con un cuadro del video
   (al 20 %), el titular, la categoría y un botón de play, todo dentro del recorte 4:5. Va como
   `cover_url` del reel en Instagram y como miniatura preferida del video en Facebook.
8. **Música de Instagram:** no es posible por API. La Graph API solo permite renombrar el audio
   original (`audio_name`); no permite elegir canciones de la biblioteca, como "Movie Magic" de Global
   Genius. Queda la opción `DUO_REEL_MUSIC_PATH`: un archivo propio con licencia de uso que el motor
   mezcla debajo del audio original (volumen 0,12 por defecto). Está desactivada mientras no se cargue
   un archivo.
9. **Etiquetas de personas** (`publishers/ig_tags.py`, `config/instagram_tags.yaml`):
   - Se etiqueta con `user_tags` en reels, imágenes y la primera imagen de los carruseles, con un
     máximo de 3 cuentas.
   - Solo se usan cuentas curadas o cuentas que propone la redacción y que se verifican con
     `business_discovery`: la cuenta existe, el nombre coincide con el de la nota y supera el mínimo
     de seguidores (personas 20.000, instituciones 5.000).
   - La persona tiene que figurar en el texto. Nunca se etiquetan particulares, víctimas, menores,
     detenidos ni acusados. En policiales y justicia solo se etiquetan instituciones.
   - Si Instagram rechaza una etiqueta, el post sale sin ella.
   - Ejemplos verificados: @policiadesalta, @gobiernosalta, @municipalidadsalta, @gustavosaenzok,
     @ansesgob. Un caso que muestra por qué no se adivina: @gobiernodesalta existe, pero no es la
     cuenta oficial (1.260 seguidores).

## 14. Pendientes y limitaciones reales

1. **No se publicó nada en vivo** (por diseño). Falta la aprobación del propietario para habilitar
   la tarea, correr `preflight` en FERNANDO y hacer un primer ciclo vigilado. El carrusel de video en
   Instagram usa el camino existente (hijos `VIDEO`), pero no se ejercitó contra Meta real.
2. **Límite de Instagram**: Meta limita la publicación por API a un cupo de 24 h (el código lo
   consulta antes de asignar). 12 piezas por hora durante 24 h supera ese cupo: el sistema se frena
   cuando se agota. Conviene fijar `quotas.max_pieces_per_day` según el cupo real de la cuenta.
3. **Tiempo de render**: una pieza de video de dos tramos tarda unos 5 minutos. Con el presupuesto de
   45 minutos, un ciclo produce como mucho 8 o 9 videos; el resto sigue en la cola.
4. **Calibración con una noche de datos**: los umbrales de Paparazzi (32) y nacional (60) salen de
   pocas notas. El modelo varía entre corridas (Pergolini dio 36 y después 27,5). Revisar con una
   semana de `relevance_json`.
5. **Marcas de agua**: solo se detectan las de El Tribuno y Qué Pasa; los créditos de terceros
   ("© Periodismo Joven") no. La calibración usó 25 imágenes.
6. **Deduplicación**: dos notas del mismo hecho sin vocabulario en común pueden quedar separadas. En
   el ejemplo, "Apareció Sofía" y "la salteñita que deambulaba" probablemente sean el mismo caso.
7. **YouTube** bloquea la descarga sin cookies (verificación anti-bot). Esos videos no se usan; la
   nota local sigue con imagen.
8. **Facebook**: el carrusel de video sale como un video con el primer tramo; los carruseles de
   imágenes siguen saliendo con la primera imagen (comportamiento previo).
9. **Costos en dólares**: tarifas cargadas el 2026-10-18; revisar si Google cambia precios.
10. El `.env` de producción todavía define `X_MODE` con un modo de scraping. El código ya no lo lee;
    se puede borrar esa línea.
11. Los cambios no están commiteados: esperan aprobación.


## 13 quinquies · Volumen (2026-10-18, tarde)

- Diagnostico con 24 h reales: de ~180 notas locales por dia solo 26 superaban el umbral 55 y
  quedaban afuera notas publicables de 45-55; de ~690 de TN/Infobae, 546 se descartaban por no tener video.
- Umbral local 55 -> 45 y oficial 65 -> 58. Se reencolaron 15 notas locales del dia.
- TN e Infobae: sin video usable (o con video de mas de 90 s) la nota igual puede salir como
  IMAGEN si su relevancia llega a 70 (`image_min_score`). Paparazzi sigue con video obligatorio.
  Se reevaluaron 325 nacionales de las ultimas 6 h con la regla nueva.
- Imagenes genericas del medio (logo de Infobae sobre naranja, El Tribuno sobre azul): se descartan
  por URL (`fallback`, `/logos/`...) y por contenido (<= 8 colores cubren el 95 % y uno >= 70 %).
  Una nacional sin video y sin foto real no sale (`NoRealPhoto`). Los resumenes horarios de agencias
  de Infobae (`/america/agencias/`, titulos tipo "Domingo, 18 de octubre de 2026 (12:00 GMT)") no son notas.
- Cupo de Instagram (100 por API cada 24 h, historias incluidas): las noticias dejan 15 para
  formatos y ningun ciclo usa mas del 25 % de lo que queda (`ig_reserve_for_formats`,
  `max_share_of_ig_remaining`). Historias: tope 15 por dia.
