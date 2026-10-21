# Formatos fuera del flujo de noticias

Código en `formats/`, configuración en `config/formats.yaml`. Plantillas del motor en `motion/src/templates/`:
- `ServiceBoard.tsx` (`board`): tableros 4:5 y 9:16;
- `StoryCard.tsx` (`story`): historias;
- `WeeklyTop.tsx` (`weekly`): reel semanal.

Los datos de cada pieza viajan en `content.extra`. Las fotos locales viajan en `content.photos` y se referencian como `"photo:N"`.

Se ejecuta al final de cada ciclo en vivo (`DuoPipeline.run_formats`). Está aislado: una falla de un formato no frena las noticias. Solo publica en FERNANDO.

## Agenda (hora local, una vez por día, ventana de 3 h)

| Hora | Formato | Redes |
|---|---|---|
| Cada ciclo | Historia del post nuevo (la mejor nota local del ciclo) y «Último momento» para notas urgentes | IG + FB historias |
| 7 h | Clima del SMN. Post solo si hay alerta amarilla o mayor | historia (+ post) |
| 8 h | «Lo que tenés que saber hoy»: portada con el clima, 5 notas con «Qué se sabe» y cierre con dólar y feriado | IG carrusel; FB post con fotos; historia |
| 9 h | Servicios: agua (Aguas del Norte), luz (EDESA) y pasos fronterizos. Post solo cuando aparece un corte o se cierra un paso | historia (+ post) |
| 10 h | Próximo feriado: el lunes de esa semana y 3 días antes | IG + FB post |
| 11 h | Dólar, solo los días hábiles | IG + FB post |
| 20 h | «Lo más importante del día»: las 5 notas más vistas | historia |
| Domingo 20 h | Top 5 de la semana | IG + FB reel |

Al publicarse una **actualización** de un hecho ya publicado:
- se publica una historia «En desarrollo», con el antes → ahora cuando cambia una cifra (muertos, heridos, evacuados, detenidos o desaparecidos);
- en Facebook se edita el texto del post original;
- en Instagram se agrega un comentario de la cuenta, porque la API no permite editar el texto.

## Límites
- **Historias:** como máximo 20 por día.
- **Cupo de Instagram:** son 100 publicaciones por API cada 24 h. Los formatos dejan libres 25 (`ig_reserve`) para las noticias.
- **Costo de IA:** ningún formato llama a Gemini. Los textos salen de plantillas y de la redacción ya generada. Las únicas excepciones son las respuestas a comentarios y el reporte.

## Respuestas a comentarios (`formats/comments.py`)
- Solo en posts informativos: Paparazzi queda afuera. Solo se responden preguntas concretas, con lo que dice la nota.
- Primero se aplica un filtro local de preguntas. Después hay una llamada a Gemini por ciclo, con un lote de hasta 20 comentarios.
- Modo `auto`: durante 3 días es modo prueba (se guarda en `comment_replies` y va al reporte sin publicarse). Después se publica, con un tope de 15 por día.
- Los posts borrados o ilegibles quedan marcados y no se vuelven a consultar.

## Ganchos A/B
- El prompt pide `gancho` y `gancho_b`, con otro ángulo.
- La mitad de las notas, según su clave, sale con el B, y la variante queda en `raw_response.variante_gancho`.
- El reporte compara las vistas promedio de A y B.

## Reporte de operaciones (`formats/report.py`)
- **Frecuencia:** sale cada 3 días a las 9 h.
- **Contenido:**
  - ciclos esperados y corridos, fallas y fuentes caídas;
  - publicaciones, vistas por tipo, hora y gancho;
  - seguidores (`account_snapshots`, una vez por día);
  - costo de IA y respuestas a comentarios.
- **Resumen:** Gemini lo escribe en una sola llamada.
- **Envío:** por SMTP, con las variables `DUO_REPORT_SMTP_*` de `.env`. Para Gmail hace falta una contraseña de aplicación.
- **Sin credenciales:** el HTML queda en `data/reports/` con estado `pending_credentials`.
- **Vigilante** (`DuoNoticias-Vigilante`, cada hora, registrado con `scripts/register_watchdog_task.ps1`):
  - manda un aviso si el latido del servicio tiene más de 2 h;
  - envía el reporte aunque el servicio esté caído.

## Comandos
```
python -m cli.main formats --step digest --step weekly      # vista previa en data/formats/preview (no publica)
python -m cli.main formats --step dollar --live             # publicar ahora (solo FERNANDO)
python -m cli.main ops-report                               # ¿toca reporte? destinatario
python -m cli.main ops-report --send                        # generar y enviar ahora
python -m cli.main ops-report --watchdog                    # lo que corre el vigilante
```

## Fuentes de servicio (`formats/sources.py`)
- **SMN:** `ws1.smn.gob.ar/v1`, con el token público de la web. El servidor viejo `ws2` ya no existe. Se consulta con curl porque Cloudflare bloquea httpx.
- **Dólar:** DolarApi, con el BCRA de respaldo; el histórico sale de ArgentinaDatos.
- **Feriados:** ArgentinaDatos.
- **Agua:** Aguas del Norte (`cortes.php` y `afectaciones.php`).
- **Luz:** EDESA (`widgets/cortes.php`).
- **Pasos fronterizos:** Ministerio de Seguridad.

Cada consulta guarda su estado en `service_health`, y ese estado va al reporte.
