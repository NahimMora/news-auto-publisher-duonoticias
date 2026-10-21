# Reglas del proyecto

- Produccion real solo en la PC cuyo `COMPUTERNAME` sea `FERNANDO`. En otras maquinas, usar exclusivamente tests, mocks y `--dry-run`/`--verify`. Aplica a los dos componentes: el envio del puente HolaSalta y la publicacion live del pipeline (`--live` + `DUO_LIVE_PUBLISH_ENABLED=true`).
- HolaSalta es solo lectura: no modificar `C:\HolaSalta\WebApp_HolaSalta` ni `C:\HolaSalta\Ops`. El pipeline solo lee `C:\sources\x_video_sources.json` (compartido con LVR): nunca escribirlo, moverlo ni borrarlo, y no tocar el estado de LVR. El puente deprecado usa la API (solo `POST /api/auth/login` y GET).
- No exponer puertos en produccion. No guardar ni imprimir secretos; configurarlos en `.env`, que esta ignorado por Git.
- La web Node (CMS DuoNoticias) esta fuera de este repositorio; su API esta documentada en `DUO_API.md` y el contrato de ingesta del puente en `docs/INGEST_CONTRACT.md`.

## Componentes

El repo une dos proyectos (merge de `pipeline-completo` en `main`):

- **Pipeline completo** (raiz: `cli/`, `jobs/`, `extractors/`, `editorial/`, `formatter/`, `publishers/`, `storage/`, ...): entrypoint unico `python -m cli.main`. Comandos, arquitectura y estilo en `AGENTS.md` y `docs/ARCHITECTURE.md`.
- **HolaSalta → Duo** dentro del pipeline: solo los links de videos de X que recolecta HolaSalta (`extractors/x_video_feed.py`). Las noticias de HolaSalta no son fuente. No hay scraping autonomo de cuentas de X. La entrega a la web de Dúo (`publishers/duo_web.py`) está deshabilitada; `publishers/web_prep.py` solo prepara articulos.
- **Reestructuracion 2026-10**: fuentes, cupos horarios (6 locales, 2 nacionales, 2 Paparazzi; max 10, sin cupos libres desde 2026-10-18), cola de 12 h, acontecimientos, relevancia por lotes y videos reales. Configuracion en `config/sources.yaml` y `config/editorial_scoring.yaml`; informe en `docs/REESTRUCTURACION_2026_10.md`. Nunca se generan reels con fotos. TN e Infobae sin video usable salen como imagen solo con relevancia >= 70 (`image_min_score` en `config/sources.yaml`); umbral local 45 (recalibrado 2026-10-18).
- **La Voz Riojana** (referencia de arquitectura) está en `C:\LVR`: solo lectura.
- **Puente standalone** (`duonoticias_autopublicador/`, deprecado): `python -m duonoticias_autopublicador.main`; ver `README.md`. No agregar funcionalidad nueva ahi.
- Servicio 24/7 en FERNANDO: tarea `DuoNoticias-24x7` (`scripts/register_scheduled_task.ps1` -> `scripts/start_24x7_production.ps1`, que corre `preflight` y despues `run-24-7 --live`, un ciclo por hora). Para probar sin publicar: `python -m cli.main simulate` (base separada). Ver `docs/OPERATIONS.md`.
- **Formatos** (`formats/`, `config/formats.yaml`, ver `docs/FORMATOS.md`): historias IG/FB, resumen de las 8, tarjetas de servicio (SMN, dolar, feriados, cortes, pasos), actualizaciones de noticias en desarrollo, top 5 semanal (unica excepcion a "nunca reels con fotos", pedida por el usuario), respuestas a comentarios (modo prueba 3 dias) y reporte de operaciones cada 3 dias por correo. Vigilante: tarea `DuoNoticias-Vigilante`.
- El guard de produccion vive en `utils/machine_guard.py`; todo lo que publique o envie hacia afuera tiene que pasar por ahi.
- Motor visual: `motion/` (Remotion + panel Next.js, ver `motion/README.md`). El pipeline lo usa via `formatter/motion_engine.py` (reels solo con video real), con fallback automatico al formateador legado. El panel solo escucha en 127.0.0.1. Las cifras y los puntos clave en pantalla solo pueden salir del texto de la nota.
- Dependencias: `requirements.txt` es la unica fuente (`pyproject.toml` la lee). Tests: `python -m pytest` corre todo `tests/`.

## Segundo Cerebro (gestión de conocimiento personal)

Este repo está trackeado por el "Segundo Cerebro" personal
(`AutoPublicadores/2doCerebro`, https://ops.moraapps.com) bajo el proyecto
**DUO** (Duo Noticias), módulo **Web**.

Si el usuario pregunta algo como "¿qué bugs/ideas/incidentes anoté acá?" (o
equivalente), consultá antes de responder; no asumas que no hay nada
pendiente sin chequear:

```bash
curl -s https://ops.moraapps.com/api/shortcuts \
  -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action":"list_items","projectCode":"DUO","moduleSlug":"web"}'
```

- Si resolviste algo que ya estaba anotado ahí (id visible en la respuesta
  anterior, formato `DUO-BUG-0007`, o porque el usuario te lo dijo), marcalo
  resuelto en vez de dejarlo como pendiente fantasma, y referencialo en el
  commit (`fix: ... [DUO-BUG-0007]`):

  ```bash
  curl -s https://ops.moraapps.com/api/shortcuts \
    -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action":"resolve_item","publicId":"DUO-BUG-0007"}'
  ```

- Si encontraste un bug real que no vas a arreglar ahora, o una idea/mejora
  para más adelante, anotala en vez de perderla en la conversación:

  ```bash
  curl -s https://ops.moraapps.com/api/shortcuts \
    -H "Authorization: Bearer $SEGUNDO_CEREBRO_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"action":"capture","content":"texto libre describiendo el bug/idea","mode":"interpret","projectCode":"DUO","moduleSlug":"web"}'
  ```

`SEGUNDO_CEREBRO_TOKEN` vive en `.env` (gitignored; nunca commitear su
valor ni imprimirlo). Si no está seteado, avisá que esta integración no
está disponible en vez de fallar en silencio.
