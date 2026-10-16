"""
Escribe data/pipeline_snapshot.json con el estado actual del pipeline.
El dashboard Next.js lee este archivo via /api/pipeline/route.ts.
Correr después de cada ciclo o con --watch para actualización continua.

    python pipeline_snapshot.py
"""
from __future__ import annotations
import json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path("data/duo_pipeline.sqlite3")
OUT = Path("data/pipeline_snapshot.json")


def snapshot() -> dict:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    # Status counts
    status_rows = c.execute(
        "SELECT pipeline_status, assigned_post_type, COUNT(*) n "
        "FROM content_items GROUP BY pipeline_status, assigned_post_type"
    ).fetchall()

    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for r in status_rows:
        s = str(r["pipeline_status"] or "unknown")
        t = str(r["assigned_post_type"] or "unknown")
        by_status[s] = by_status.get(s, 0) + r["n"]
        by_type[t] = by_type.get(t, 0) + r["n"]

    # Queue
    queue = c.execute(
        "SELECT source, title, assigned_post_type, score_total, pipeline_status, updated_at "
        "FROM content_items WHERE pipeline_status IN ('scheduled','formatted','editorialized') "
        "ORDER BY score_total DESC LIMIT 20"
    ).fetchall()

    # Recent published
    published = c.execute(
        "SELECT source, title, assigned_post_type, score_total, updated_at "
        "FROM content_items WHERE pipeline_status = 'published' "
        "ORDER BY updated_at DESC LIMIT 10"
    ).fetchall()

    # Failed
    failed = c.execute(
        "SELECT source, title, assigned_post_type, last_error, updated_at "
        "FROM content_items WHERE pipeline_status = 'publish_failed' "
        "ORDER BY updated_at DESC LIMIT 10"
    ).fetchall()

    # Source breakdown
    source_pub = c.execute(
        "SELECT source, COUNT(*) n FROM content_items "
        "WHERE pipeline_status='published' GROUP BY source ORDER BY n DESC LIMIT 12"
    ).fetchall()

    # Score distribution
    score_dist = c.execute(
        "SELECT CAST(score_total/10 AS INT)*10 bucket, COUNT(*) n "
        "FROM content_items WHERE score_total IS NOT NULL "
        "GROUP BY bucket ORDER BY bucket"
    ).fetchall()

    c.close()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(DB),
        "by_status": by_status,
        "by_type": by_type,
        "queue": [dict(r) for r in queue],
        "published": [dict(r) for r in published],
        "failed": [dict(r) for r in failed],
        "source_published": [dict(r) for r in source_pub],
        "score_distribution": [dict(r) for r in score_dist],
        "totals": {
            "total": sum(by_status.values()),
            "scheduled": by_status.get("scheduled", 0),
            "published": by_status.get("published", 0),
            "publish_failed": by_status.get("publish_failed", 0),
            "editorialized": by_status.get("editorialized", 0),
            "filtered": by_status.get("filtered", 0),
            "skipped": by_status.get("skipped", 0),
        },
    }


if __name__ == "__main__":
    if not DB.exists():
        print(f"ERROR: {DB} no existe.")
        sys.exit(1)
    data = snapshot()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Snapshot escrito: {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"  total={data['totals']['total']} published={data['totals']['published']} scheduled={data['totals']['scheduled']}")
