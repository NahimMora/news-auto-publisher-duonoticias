# Auditoría 24/7: Dúo Noticias (2026-10-17)

**Objetivo:** que Dúo Noticias publique noticias de Salta en forma automática y continua, con la confiabilidad del autopublicador de La Voz Riojana (LVR).

**Método:**
- Se estudió LVR solo a nivel de concepto, en lectura: no se copió código, no se unió nada y no se tocó nada de `C:\LVR`.
- Se recorrió el pipeline de Dúo con datos reales (scraping, scoring, editorial, formato y render) sobre una base temporal, sin publicar.

## Resumen

| # | Hallazgo | Severidad | Estado |
| --- | --- | --- | --- |
| 1 | El filtro de temas descartaba casi toda la noticia local de Salta | Crítica | Corregido |
| 2 | Sin idempotencia: una caída durante la publicación podía duplicar posts | Alta | Corregido |
| 3 | Un rechazo por límite de Meta dejaba la nota en `publish_failed` para siempre | Alta | Corregido |
| 4 | Los tests leían credenciales reales del `.env` y renderizaban de verdad | Alta | Corregido |
| 5 | El módulo legado de Meta ignoraba las claves `META_*` del `.env` | Media | Corregido |
| 6 | Los layouts legados buscaban archivos de HolaSalta y tenían estética de plantilla genérica | Media | Reemplazado por Dúo Motion (el legado queda como respaldo) |
| 7 | Falta `GEMINI_API_KEY`: el preflight frena el servicio | Bloqueante | **Pendiente (usuario)** |
| 8 | Volumen configurado: hasta 75 publicaciones por día | Media | **Decisión del usuario** |
| 9 | La tarea programada solo corre con la sesión de Windows iniciada | Media | Recomendación |
| 10 | No hay canal de alertas (heartbeat vencido, fallas repetidas) | Media | Recomendación |
| 11 | Pocas fuentes salteñas (4) frente a nacionales (7) | Media | Recomendación |
| 12 | El token de Meta vence el 15/12/2026 | Media | Recordatorio |
| 13 | Credenciales compartidas por chat | Media | Recomendación |

## Detalle

### 1. Noticia local descartada

`jobs/content_policy.py` aceptaba solo política, policiales, espectáculos y alertas, detectados por palabras del título. En la prueba real quedaron afuera:
- la atleta salteña Milagros D'Amico, medalla de plata en el Sudamericano;
- "Dani Alves llega a Salta";
- "Controles contra el contrabando".

**Corrección:** también entra lo local, es decir, notas de una fuente salteña (`is_salta_source`) o con un lugar de Salta en el título. Hay una lista de localidades y el filtro se puede desactivar con `DUO_POLICY_ACCEPT_SALTA_LOCAL=0`. Las notas nacionales genéricas siguen filtradas.

**Tests:** `tests/test_publish_reliability.py::LocalNewsPolicyTests`.

### 2. Idempotencia de publicación

El registro de la publicación se guardaba después de la llamada a Meta. Si el proceso caía entre la publicación real y ese guardado, el próximo ciclo republicaba la nota.

**Corrección:** la plataforma queda `in_flight` antes de llamar a Meta. Al iniciar el siguiente ciclo, `_reconcile_in_flight` busca en la cuenta el caption exacto: los últimos 30 posts de IG, y los posts y videos de la página de FB.
- Si lo encuentra, marca `published` con su id y no duplica.
- Si confirma que no está, la nota vuelve a la cola.
- Si no puede verificar, queda `ambiguous`: no se reintenta sola y requiere `retry` manual.

La coincidencia es por evidencia (el caption generado es único), nunca por parecido de título. Es la misma idea de "reconciliación por evidencia" de LVR, implementada desde cero.

**Tests:** `ReliabilityTests` (tres escenarios).

### 3. Límites de Meta

Un rechazo por cupo o tasa marcaba la nota `publish_failed`, y `list_due_for_publish` no reintenta ese estado: la nota se perdía. Es la lección #91 de LVR.

**Corrección:** `publishers/rate_limits.py` detecta:
- el cupo de 24 h de Instagram (subcódigo 2207042);
- los códigos 4/9/17/32/613;
- HTTP 429;
- "limit reached".

Ante cualquiera de ellos bloquea esa plataforma de forma compartida: 30 minutos, o 180 si es el cupo diario. El estado vive en `data/runtime/meta_rate_limits.json` y la nota vuelve a `scheduled` sin consumir reintentos. Mientras dura el bloqueo no se llama a la plataforma, y las demás plataformas siguen publicando. El preflight muestra los bloqueos vigentes.

**Tests:** `test_rate_limit_defers_without_burning_the_item`, `RateLimitDetectionTests`.

### 4. Aislamiento de tests

Con `META_*` en el `.env`, un test tomaba el `META_PAGE_ID` real. Además, el motor audiovisual se ejecutaba de verdad dentro de la suite.

**Corrección:** `tests/conftest.py` vacía las credenciales de LLM, Meta y R2, desactiva el motor (que tiene sus propios tests con un worker falso) y aísla el estado de límites de Meta.

### 5. Claves `META_*`

`utils/instagram_graph_publisher.py`, que usan el flujo manual de X y la resolución de URLs de medios, solo leía `IG_*`/`FB_*`. Ahora lee primero `META_*` (el nombre canónico en `.env`) y conserva los alias anteriores.

### 6. Diseño

El formateador legado dependía de `logo_cuadrado.png`, `www.HolaSalta.com.png` e `icono_deslizar.png`, que no existen en `data/`, y producía tarjetas de plantilla. Ahora todo sale de **Dúo Motion** (ver `motion/README.md`): identidad Dúo, cuatro plantillas, ganchos, animación y formatos adaptativos.
- Si el motor no está disponible o falla en una pieza, el legado la produce igual (como el respaldo Remotion → Pillow de LVR) y queda registrado `motion_fallback` en el log.
- Las cifras y los puntos clave que salen en pantalla se validan contra el texto de la nota.

### 7. Gemini

Sin `GEMINI_API_KEY`, el editorial usa captions de plantilla y el preflight marca un error crítico, así que el servicio no arranca. **Es lo único que falta para salir en vivo:** Instagram, Facebook y R2 ya figuran como listos.

### 8. Volumen

Los valores por defecto (5 videos y 10 posts por franja, 5 franjas, tope de 15 por franja) permiten hasta 75 publicaciones por día. El cupo de Instagram por API es de 100 en 24 h (verificado: `quota_total=100`), así que entra, pero es mucho para una cuenta de 23.000 seguidores y para Facebook. LVR trabaja con hasta 8 por ciclo y un tope diario de imágenes locales.

**Sugerencia:** arrancar con 2 videos y 4 posts por franja (unas 30 por día) y ajustar con las métricas. Variables: `DUO_SCHEDULE_VIDEOS_PER_SLOT`, `DUO_SCHEDULE_POSTS_PER_SLOT` y `DUO_PUBLISH_DEFAULT_MAX_POSTS`.

### 9. Arranque tras reinicio

`DuoNoticias-24x7` (igual que la tarea de LVR) corre "solo con el usuario conectado". Después de un corte de luz no publica hasta que alguien inicie sesión.

**Opciones:**
- inicio de sesión automático de Windows en FERNANDO;
- volver a registrar la tarea como "ejecutar tanto si el usuario inició sesión como si no" (pide la contraseña de Windows).

### 10. Alertas

Hoy un heartbeat vencido o una falla repetida solo queda en el log. LVR tiene detección, deduplicación y una bandeja de alertas (aunque sin webhook configurado). Se recomienda sumar un canal: webhook, Telegram, o registrar incidentes en el Segundo Cerebro (proyecto DUO).

### 11. Fuentes

Las fuentes salteñas activas son El Tribuno, Nuevo Diario, Fiscales y Poder Judicial. HolaSalta está desactivada. Para un medio salteño conviene sumar más fuentes locales, cada una con su extractor y su prueba.

### 12. Token de Meta

Es un token de página y es válido: `expires_at` cae el 15/12/2026. Hay que renovarlo antes de esa fecha o el servicio deja de publicar. El preflight lo detecta como credencial inválida recién cuando falla.

### 13. Credenciales compartidas

En la conversación se pegaron, además de las claves en uso, el `IG_APP_SECRET`, una clave de OpenAI, credenciales de Cloudinary y un token de Meta anterior. **Recomendación:** rotar las que no se usan (OpenAI y Cloudinary) y el app secret.

Las claves en uso solo están en `.env`, que Git ignora, y nunca se imprimieron en logs.

## Ideas de LVR adoptadas (a nivel de concepto)

| Concepto LVR | Dúo |
| --- | --- |
| Tarea cada 5 min + lock + gate de configuración | Ya estaba (`DuoNoticias-24x7`, `autorun.lock`, `preflight`) |
| Marcar "processing" antes de la API y reconciliar tras una caída | **Nuevo:** `in_flight` + reconciliación por caption |
| Límite de Meta: espera compartida, sin dead-letter | **Nuevo:** `rate_limits.py` |
| Motor principal con respaldo automático y registro del motor usado | **Nuevo:** Dúo Motion → formateador legado (`meta.style`) |
| Prioridad local por buckets | Bonus Salta en scoring/scheduler + **nuevo** filtro local |
| Heartbeat y salud | Ya estaba (`heartbeat.json`, `autorun-health`) |

## Ideas de LVR pendientes (sugeridas)

1. Canal de alertas con deduplicación (ver punto 10).
2. Subprocesos por etapa con su propio timeout. Hoy el render ya está aislado en su worker con timeouts; faltaría aislar el scraping.
3. Topes diarios por plataforma, horario de silencio para imágenes y espaciado con variación entre posts.
4. Canario de publicación: una pieza por canal con evidencia guardada, antes de habilitar el volumen completo.
