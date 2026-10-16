from __future__ import annotations

"""Deprecated legacy entrypoint.

Runtime source of truth is now ``python -m cli.main``.
This wrapper is kept so existing shortcuts keep working.
"""

import sys

from cli.main import main as cli_main


def main() -> None:
    print("[DEPRECATED] duo_runner.py ahora delega en python -m cli.main run-once --safe-mode")
    cli_main(["run-once", "--safe-mode", *sys.argv[1:]])


if __name__ == "__main__":
    main()
