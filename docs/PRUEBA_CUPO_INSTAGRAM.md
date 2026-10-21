# Prueba del límite de publicación de Instagram (desde el 20/10/2026)

## Qué se quiere saber

Meta documenta un límite de **100 publicaciones por API cada 24 h móviles** por cuenta de
Instagram, y lo informa en `GET /{ig-user-id}/content_publishing_limit` (`quota_usage` y
`quota_total`). Otros medios publican unas 10 piezas por hora. La prueba busca responder
estas preguntas:

1. ¿Instagram rechaza de verdad al pasar las 100, o el número es solo informativo?
2. Si rechaza, ¿con qué error lo hace (código y subcódigo) y cuánto tarda en volver a aceptar?
3. ¿Las historias cuentan para ese cupo?

## Cómo está configurado

Se configura en `config/editorial_scoring.yaml`, dentro de `quotas`:

- `ig_news_per_hour`: `night: 10`, `day: 10`. Son 10 noticias por ciclo a toda hora. El techo
  por ciclo sigue siendo `max_per_cycle: 10`, repartido en 6 locales, 2 nacionales y 2 Paparazzi.
- `ig_quota_probe: true`. El ciclo **no** se frena por el cupo restante que informa la API ni
  por la reserva para formatos.

Si Instagram rechaza una publicación por límite, el sistema hace esto:

- La nota igual sale en Facebook.
- Instagram queda en pausa: 3 h si el error es el de cupo diario (`2207042` o `publishing limit
  reached`) y 30 min para otros límites de tasa. Se guarda en `data/runtime/meta_rate_limits.json`.
- La nota queda `scheduled` para completar Instagram cuando termine la pausa.

## Qué se registra

Cada ciclo agrega una línea a `data/reports/ig_limit_probe.jsonl` con estos datos:

- `before` y `after`: el `quota_usage` y el `quota_total` informados al empezar y al terminar el ciclo.
- `news_instagram` y `formats_instagram`: las publicaciones del ciclo en Instagram, por estado.
- `instagram_errors`: el texto completo de cada rechazo.
- `instagram_blocked`: la pausa vigente y su motivo.

El resumen de cada ciclo, en `logs/autorun_24_7.log`, también trae `"ig_probe": {before, after, errors}`.
Si fallan publicaciones, el vigilante manda un aviso por correo (`publicacion_falla:instagram`).

## Cómo volver al ritmo parejo

En `quotas` hay que dejar `ig_news_per_hour` con `night: 1` y `day: 3`, poner
`ig_quota_probe: false` y reiniciar el servicio.

## Resultados

| Fecha y hora | Uso informado | Qué pasó |
|---|---|---|
| 20/10 18:30 (antes de la prueba) | 83 / 100 | 56 noticias y 27 historias o formatos en 24 h. Las historias suman al `quota_usage`. |
| 20/10 21:00 (primer ciclo de la prueba) | 75 → 80 / 100 | Salieron 10 noticias y 1 historia en Instagram, sin rechazos. El uso sube 5 y no 11 porque en ese rato vencieron las publicaciones de la noche anterior (ventana móvil). |
| 21/10 13:00 a 16:00 | 82 → 90 / 100 | Durante el día el ritmo lo limitaron las notas disponibles (2 a 4 por ciclo), no el cupo. A las 16 h, dos fallas de subida a R2 (`InternalError`), sin relación con el cupo. |

## Conclusión (21/10/2026)

La prueba se cerró sin llegar al límite. En 18 ciclos hubo 0 rechazos de Instagram y el uso máximo
fue de 90/100, así que no se sabe si el corte en 100 es real. Las historias sí suman al
`quota_usage`.

Se terminó antes por la audiencia y no por el cupo: con ese volumen las bajas de seguidores
llegaron a 50 a 97 por día (ver `docs/ESTRATEGIA_AUDIENCIA.md`). Ahora `ig_quota_probe` está en
`false` y el feed de IG tiene un máximo de 20 noticias por día.
