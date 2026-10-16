# Auditoría y Refactor Productivo

## Hallazgos críticos

1. El pipeline actual depende de archivos `latest_*`, globbing y side effects del filesystem.
2. `duo_runner.py` encadena subprocess sin estado transaccional ni trazabilidad por item.
3. La deduplicación está fragmentada: semántica para noticias, `ig_key` para reels, pero no existe una capa única por contenido.
4. El extractor de X está dividido en varias ramas, con estrategias mezcladas y sin persistencia estructurada.
5. La publicación Meta funciona, pero vive como script monolítico y no como servicio reusable con analytics/comentarios.
6. No existe feedback loop persistido entre contenido, publicación y performance.
7. La UI actual no es el punto de control correcto para operación 24/7; faltaba una CLI operativa.
8. Había riesgo de seguridad: `.env.example` contenía valores sensibles con apariencia real.

## Arquitectura nueva

Se agregó una capa productiva paralela, sin romper el stack legacy:

- `extractors/`
  - `news_sources.py`: envuelve los scrapers actuales y los transforma en objetos persistibles.
  - `x/`: extractor multiestrategia con Playwright autenticado + fallback `yt-dlp`.
- `scoring/`
  - `virality.py`: score 0-100 con novelty, engagement, debate y repostability.
- `editorial/`
  - prompt estructurado y salida JSON persistida con hook/context/tensión/remate/CTA/overlay.
- `formatter/`
  - formatter idempotente para reels, imágenes y carruseles usando las funciones visuales existentes.
- `publishers/`
  - `meta_api.py`: create container -> publish, límite de publicación, fallback Facebook y automatización de respuestas.
- `analytics/`
  - snapshots persistidos por publicación.
- `growth/`
  - feedback loop simple para retroalimentar temas, slots y fuentes ganadoras.
- `storage/`
  - `sqlite_store.py`: source of truth de items, jobs, publicaciones, analytics y comentarios.
- `jobs/`
  - scheduler de slots y orquestador end-to-end.
- `cli/`
  - reemplazo operativo de la UI para correr pipeline, scraper, publisher, reintentos y métricas.

## Flujo nuevo

1. `extractors/` ingesta contenido crudo.
2. `storage/` persiste el item y lo deduplica por `content_key` + perceptual hash.
3. `scoring/` decide prioridad editorial.
4. `editorial/` genera hook, overlay, caption y razón.
5. `formatter/` produce assets publicables.
6. `jobs/scheduler.py` asigna slots 09 / 12 / 15 / 18 / 21 / 00.
7. `publishers/meta_api.py` publica en IG y cae a FB si IG falla.
8. `analytics/` recupera insights.
9. `growth/` sintetiza qué rindió mejor para el siguiente ciclo.

## Meta API: decisiones de producto

- Se implementó `POST /<IG_ID>/media` + `POST /<IG_ID>/media_publish`.
- Se consulta `/<IG_ID>/content_publishing_limit` antes de publicar.
- Se deja fallback a Facebook si Instagram falla o agotó cupo.
- Comentarios:
  - Se soporta lectura y respuesta con emoji en Instagram.
  - El “like” automático no se implementa como éxito garantizado porque la documentación oficial actual no expone un flujo soportado equivalente para Instagram comments.

## CLI operativa

```powershell
python -m cli run-pipeline
python -m cli run-scraper --max-news 5
python -m cli run-publisher
python -m cli retry-failed
python -m cli show-stats
python -m cli show-queue
```

## Próxima fase recomendada

1. Migrar comentarios/analytics a Webhooks para bajar polling.
2. Añadir batching y workers por etapa.
3. Conectar scheduler a un servicio 24/7 con watchdog y healthchecks.
4. Reemplazar gradualmente los scripts legacy por implementaciones puramente modulares.
5. Incorporar ranking por performance histórica real de slot + tema + formato.
