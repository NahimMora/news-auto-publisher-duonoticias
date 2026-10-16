# CLI

Primary commands:

```powershell
python -m cli.main status
python -m cli.main run-once
python -m cli.main run-once --dry-run
python -m cli.main run-24-7
python -m cli.main run-24-7 --cycles 1 --max-news 0
python -m cli.main scan-sources
python -m cli.main scan-source --source paparazzi
python -m cli.main scan-x-feed
python -m cli.main import-x-url --url "..."
python -m cli.main score-pending
python -m cli.main editorial-pending
python -m cli.main format-pending
python -m cli.main schedule-pending
python -m cli.main publish-pending
python -m cli.main publish-pending --live --max-posts 15
python -m cli.main analytics-collect
python -m cli.main growth-report
python -m cli.main source-ranking
python -m cli.main queue
python -m cli.main queue --format table
python -m cli.main inspect --content-key "..."
python -m cli.main retry --content-key "..."
python -m cli.main skip --content-key "..." --reason "..."
python -m cli.main dry-run
python -m cli.main safe-mode
python -m cli.main test-meta
python -m cli.main test-source --source tn
python -m cli.main autorun-health
python -m cli.main doctor
```

Legacy aliases still accepted:

```powershell
python -m cli.main run-pipeline
python -m cli.main run-scraper
python -m cli.main run-publisher
python -m cli.main run-analytics
python -m cli.main show-queue
python -m cli.main show-stats
```

Live publishing is blocked unless both are true:
- `.env`: `DUO_LIVE_PUBLISH_ENABLED=true`
- CLI: `--live`

Default automated blocks are `09:00,12:00,15:00,18:00,21:00`.
Each block schedules up to `DUO_SCHEDULE_VIDEOS_PER_SLOT=5` reels/videos and `DUO_SCHEDULE_POSTS_PER_SLOT=10` image/carousel news posts.
In `run-24-7`, live publishing is deferred unless the current time is inside `DUO_PUBLISH_SLOT_WINDOW_MINUTES` after a configured block.
