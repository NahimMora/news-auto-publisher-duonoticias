"""
Reset completo del pipeline — borra todos los datos y deja el schema listo.

ADVERTENCIA: Esto elimina TODOS los items scrapeados, editorizados,
publicados y analytics. Es irreversible.

Uso:
    python reset_pipeline.py
    python reset_pipeline.py --confirm   # salta la confirmacion interactiva
"""
from __future__ import annotations
import argparse, shutil, sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB = Path("data/duo_pipeline.sqlite3")
BACKUP_DIR = Path("data/backups")

TABLES_TO_CLEAR = [
    "content_items",
    "publications",
    "analytics_snapshots",
    "comment_actions",
    "daily_reports",
    "score_validation_runs",
    "jobs",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Salta confirmacion interactiva")
    args = parser.parse_args()

    if not DB.exists():
        print(f"No existe {DB}. Nada que resetear.")
        return

    import sqlite3
    c = sqlite3.connect(DB)
    total = c.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
    pubs = c.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    c.close()

    print("=" * 55)
    print("  RESET PIPELINE — AutoPublicador Duo")
    print("=" * 55)
    print(f"  items en content_items : {total}")
    print(f"  publications           : {pubs}")
    print()

    if not args.confirm:
        resp = input("  ¿Confirmar reset completo? (escribi 'si' para continuar): ").strip().lower()
        if resp not in ("si", "sí", "yes", "y"):
            print("  Cancelado.")
            return

    # Backup antes de borrar
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"duo_pipeline_backup_{stamp}.sqlite3"
    shutil.copy2(DB, backup_path)
    print(f"\n  Backup guardado en: {backup_path}")

    # Truncar tablas
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in TABLES_TO_CLEAR:
        try:
            conn.execute(f'DELETE FROM "{table}"')
            print(f"  Limpiada: {table}")
        except Exception as e:
            print(f"  Skip {table}: {e}")
    conn.execute("DELETE FROM sqlite_sequence")
    conn.commit()
    conn.close()
    # VACUUM fuera de transaccion
    conn2 = sqlite3.connect(DB)
    conn2.isolation_level = None
    conn2.execute("VACUUM")
    conn2.close()

    print()
    print("  ✅ Reset completo. Base de datos lista para empezar de cero.")
    print(f"  Backup disponible en: {backup_path}")
    print()


if __name__ == "__main__":
    main()
