# Calibration Phase

## Objetivo

Esta capa prepara 7 dias de calibracion real sin reescribir el pipeline nuevo. La calibracion agrega:

- trazabilidad total por contenido
- checkpoints T1/T2/T3 en SQLite
- buckets de performance
- validacion score vs performance
- feedback loop para prompt editorial
- slots editoriales con restricciones
- ranking dinamico de fuentes X
- flags de reciclado
- daily reports en CLI + JSON

## Comandos

```powershell
python -m cli run-pipeline --safe-mode --max-posts 1
python -m cli run-pipeline --dry-run
python -m cli run-publisher --dry-run --safe-mode
python -m cli run-analytics
python -m cli validate-scoring --lookback-days 30 --checkpoint T3
python -m cli show-source-ranking
python -m cli daily-report --date 2026-04-05
```

## Persistencia

SQLite ahora guarda:

- score total y subscores materializados
- prompt editorial usado
- input editorial
- output editorial completo
- caption y overlay final
- tipo de contenido y slot asignado
- post_id final
- checkpoints T1/T2/T3 con views, likes, comments, shares, engagement_rate y performance_score
- bucket actual y flags de reciclado

## Politica de slots

- alto: `18:00`, `21:00`, `00:00`
- medio: `12:00`, `15:00`
- experimental: `09:00`

El scheduler intenta evitar repeticion consecutiva de tema, cuenta origen y tipo de contenido.

## Safe Mode

- `--dry-run`: corre pipeline sin publicar
- `--safe-mode`: publica con limite por defecto (`DUO_PUBLISH_DEFAULT_MAX_POSTS`)
- `--max-posts`: override del limite de publicacion

## Reportes

`daily-report` genera un JSON en `DUO_DAILY_REPORT_DIR` y lo persiste tambien en SQLite.
