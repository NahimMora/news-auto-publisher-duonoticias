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
