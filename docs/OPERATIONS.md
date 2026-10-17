# Operations

## Safe Defaults

Live publishing is blocked by default.

Required for live publishing:
- `DUO_LIVE_PUBLISH_ENABLED=true`
- command uses `--live`
- valid Meta credentials
- valid media storage credentials when local assets must be converted to public URLs (`docs/R2_MEDIA.md`)

Tests and dry-runs never publish live.

## Commands

```powershell
python -m cli.main doctor
python -m cli.main dry-run
python -m cli.main run-once --dry-run
python -m cli.main queue --format table
python -m cli.main import-x-url --url "https://x.com/user/status/123"
python -m cli.main publish-pending
```

## 24/7

```powershell
python -m cli.main run-24-7 --interval-minutes 60
```

or:

```powershell
.\24_7_duo.bat
```

The loop catches per-cycle failures, logs the exception, sleeps and continues. Use `CTRL+C` for clean shutdown.
The hardened autorun writes:
- `logs\autorun_24_7.log`: rotating runtime log from the CLI.
- `logs\start_24x7.log`: start attempts and preflight failures of the scheduled task.
- `data\runtime\heartbeat.json`: last cycle state, duration, result and next sleep.
- `data\runtime\autorun.lock`: process lock to avoid duplicate publishers.

The 24/7 loop aligns cycles to the configured publication blocks when the next block is sooner than the interval. Defaults:
- `DUO_SCHEDULE_SLOTS=09:00,12:00,15:00,18:00,21:00`
- `DUO_SCHEDULE_VIDEOS_PER_SLOT=5`
- `DUO_SCHEDULE_POSTS_PER_SLOT=10`
- `DUO_PUBLISH_DEFAULT_MAX_POSTS=15`
- `DUO_PUBLISH_SLOT_WINDOW_MINUTES=45`
- `DUO_SAFE_RECOVERY_MAX_RETRIES=3`
- `DUO_HEARTBEAT_STALE_MINUTES=90`

## Windows Autorun (produccion, solo FERNANDO)

Same scheme as `LaVozRiojana-24x7`:

```powershell
# 1. Gate: exit 1 and list what is missing if live publishing cannot work
.\.venv\Scripts\python.exe -m cli.main preflight
powershell -ExecutionPolicy Bypass -File .\scripts\start_24x7_production.ps1 -ValidateOnly

# 2. Register DuoNoticias-24x7 (every 5 minutes; add -Disable to register it off)
powershell -ExecutionPolicy Bypass -File .\scripts\register_scheduled_task.ps1
```

Each run of the task executes `scripts\start_24x7_production.ps1`: it refuses other machines, sets the live profile (`DUO_LIVE_PUBLISH_ENABLED=true`, `DUO_SAFE_MODE_DEFAULT=false`, web delivery off: `ENABLE_DUO_WEB=false`), runs `preflight` and only then `run-24-7 --live`. If the supervisor is already running it holds `data\runtime\autorun.lock` and the new instance exits, so the 5-minute trigger doubles as restart-on-crash. Preflight failures go to `logs\start_24x7.log`.

`preflight` is critical on: other machine, live flag off, no enabled source, missing LLM key (`GEMINI_API_KEY` with the default `LLM_PROVIDER=gemini`; editorial would fall back to template captions), no enabled platform, or an enabled platform (`ENABLE_INSTAGRAM`, `ENABLE_FACEBOOK`, `ENABLE_DUO_WEB`) without credentials or, for Instagram, without ready media storage.

Stop: `Disable-ScheduledTask -TaskName DuoNoticias-24x7`, then end the `python -m cli.main run-24-7` process.

Check health:

```powershell
.\.venv\Scripts\python.exe -m cli.main autorun-health
```

Operational status:
- `ok`: runtime prerequisites are present and heartbeat is fresh.
- `degraded`: the loop can run, but there are stale/retry-exhausted items or heartbeat/log issues.
- `critical`: live publishing, credentials or SQLite are not ready.

## Motor audiovisual (motion/)

- Instalación: `cd motion; npm install`. El primer render descarga el Chrome headless de Remotion y arma el bundle (`motion/.cache/`).
- Verificación: `python -m cli.main preflight` informa `motion_engine` como `ready`, `disabled` o `unavailable_legacy_fallback`. Cuando no está disponible, el pipeline sigue con el formateador legado y solo emite una advertencia.
- Demos y prueba visual: `cd motion; npm run render:demos`. Los archivos quedan en `motion/out/demos/`.
- Panel editorial (local, 127.0.0.1:3100): `cd motion; npm run panel`. Muestra las piezas generadas por el pipeline en "Bandeja del pipeline".

## Publicación interrumpida y límites de Meta

- **Si el proceso se corta mientras publica**, la plataforma queda `in_flight`. El próximo ciclo busca el caption exacto en la cuenta:
  - si lo encuentra, la marca como publicada;
  - si confirma que no está, la reencola;
  - si no puede verificar, la marca `ambiguous`.
- **Una plataforma `ambiguous` no se republica sola.** Revisá en Instagram/Facebook si el post salió:
  - si salió, dejala como está u omití la pieza con `skip`;
  - si no salió, corré `python -m cli.main retry --content-key "..."`.
- **Límites de Meta:** el cupo de 24 h de Instagram, los códigos 4/9/17/32/613 o un HTTP 429 bloquean esa plataforma 30 minutos (180 si es el cupo diario). La pieza vuelve a `scheduled` sin perder reintentos. El estado está en `data\runtime\meta_rate_limits.json` y el preflight lo informa.

## Recovery

Inspect:

```powershell
python -m cli.main inspect --content-key "..."
```

Retry:

```powershell
python -m cli.main retry --content-key "..."
```

Skip:

```powershell
python -m cli.main skip --content-key "..." --reason "duplicado o riesgo"
```

## Live Publish

Preview due items:

```powershell
python -m cli.main publish-pending
```

Live publish:

```powershell
$env:DUO_LIVE_PUBLISH_ENABLED="true"
python -m cli.main publish-pending --live --max-posts 15
```

Live 24/7:

```powershell
$env:DUO_LIVE_PUBLISH_ENABLED="true"
python -m cli.main run-24-7 --live
```
