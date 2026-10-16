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
- `logs\autorun_24_7_console.log`: stdout/stderr when launched through the autorun BAT.
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

## Windows Autorun

Register the live autorun task:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autorun_task.ps1 -RunNow
```

The task runs `autorun_24_7.bat` at user logon, ignores duplicate starts and asks Task Scheduler to restart the process every 5 minutes if it exits unexpectedly.

Check health:

```powershell
python -m cli.main autorun-health
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
