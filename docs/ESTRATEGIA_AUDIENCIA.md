# Estrategia para frenar la baja de seguidores en Instagram (desde el 21/10/2026)

## Medición de partida

Fuente: API de Instagram (`follows_and_unfollows`, `reach`, `total_interactions`) y la base del
pipeline. Para volver a medir se usa `python scripts/audience_report.py --days 21`, que guarda
`data/reports/audience_<fecha>.json`.

| Período | Altas/día | Bajas/día | Neto/día | Alcance/día | Publicaciones IG/día |
|---|---|---|---|---|---|
| 1 al 15/10 (cuenta casi inactiva) | 0 a 4 | 9 a 23 | −5 a −22 | 500 a 3.000 | 0 |
| 16 y 17/10 | 6 a 7 | 73 a 83 | −67 a −76 | 1.200 a 5.800 | 0 a 9 |
| 18 y 19/10 (ritmo de 1/4 del cupo) | 11 a 27 | 86 a 97 | −70 a −75 | 17.000 a 57.000 | 71 a 88 |
| 20/10 (ritmo fijo por hora desde las 18:45) | 25 | 50 | −25 | 37.000 | 86 |

Vistas promedio por publicación del feed a las ~25 h:
- Imágenes: 801 el 18/10, 597 el 19/10 y 592 el 20/10, con 1 a 2 likes cada una.
- Reels: 5.922, 5.226 y 1.983 en esos mismos días.

### Lectura

- La cuenta ya perdía unos 10 seguidores netos por día antes de la automatización.
- El salto de bajas empezó el **16/10, antes de que el pipeline publicara**. Es coherente con la
  reactivación de una cuenta dormida: los seguidores inactivos o que la seguían por otro motivo
  vuelven a ver contenido y se van. La parte de las bajas que se explica por esto debería agotarse
  sola.
- El volumen alto multiplicó el alcance por 20 a 50, pero con imágenes que casi nadie toca. Eso le
  dice a Instagram que el contenido no interesa, y la distribución por publicación cae día a día.
- Los reels rinden entre 5 y 10 veces más que las imágenes.
- Facebook sube de seguidores (263 → 280), aunque su alcance es mínimo: 3 vistas en la última nota
  medida. Hasta el 21/10 las vistas de Facebook no se medían (siempre daban 0).

## Qué cambió el 21/10

1. **Feed de Instagram separado de Facebook** (`quotas.ig_feed` y `quotas.ig_news_per_hour` en
   `config/editorial_scoring.yaml`):
   - En el feed de IG entran solo las mejores notas de cada ciclo, con un máximo de 20 por día.
   - Por ciclo entran 0 de 1 a 6 h, 2 en las horas pico (12, 13, 20, 21 y 22 h) y 1 en el resto.
   - El resto de las notas sale solo en Facebook. La historia de la nota del ciclo sigue saliendo
     en las dos redes.
   - Instagram pasa de unas 85 publicaciones por día (noticias más historias) a unas 45.
2. **Prioridad para el video.** Una nota con video suma 10 puntos al competir por el feed de IG
   (`ig_feed.video_bonus`).
3. **Cierres que invitan a comentar.** Cada caption termina con una pregunta concreta y local en
   lugar de un cierre genérico (prompt `duo-2026-10-v4`). Las respuestas automáticas a comentarios
   salen de modo prueba esta semana.
4. **Prueba del límite de 100 terminada.** Ver `docs/PRUEBA_CUPO_INSTAGRAM.md`.
5. **Medición:**
   - Las vistas y el alcance de Facebook ahora se leen: `post_media_view` y
     `post_total_media_view_unique`.
   - `scripts/audience_report.py` reúne todo lo anterior en un solo reporte.

## Cómo se evalúa (revisar el 28/10)

| Indicador | Hoy | Objetivo a 7 días |
|---|---|---|
| Bajas/día | 50 a 97 | menos de 30 |
| Neto/día | −25 a −75 | 0 o positivo |
| Vistas por imagen a 25 h | ~590 | más de 900 |
| Likes por imagen | 1 a 2 | más de 5 |

Si al 28/10 las bajas siguen arriba de 50 por día, el siguiente paso es bajar `ig_feed.per_day` a
12 y concentrar las noticias de un mismo hecho en carruseles.

Para volver atrás: poner `ig_feed.per_day: 0`, que deja IG y FB con las mismas notas, y reiniciar
el servicio.
