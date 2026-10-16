# Testing

## Unit/Integration

```powershell
python -m pytest
```

Current suite covers:
- SQLite migrations and traceability.
- Scoring.
- Editorial prompt normalization.
- Formatter service.
- Scheduler anti-repetition.
- X network/parser/import behavior.
- Meta publisher helpers.
- Analytics fallback.

## Smoke

```powershell
python -m cli.main doctor
python -m cli.main dry-run --max-news 0
python -m cli.main run-once --dry-run --max-news 1
python -m cli.main queue --format table
python -m cli.main test-source --source paparazzi
python -m cli.main test-source --source tn
python -m cli.main import-x-url --url MOCK_URL --dry-run
python -m cli.main test-meta
python -m cli.main run-24-7 --cycles 1 --max-news 0
```

Dry-run and tests do not publish live.
