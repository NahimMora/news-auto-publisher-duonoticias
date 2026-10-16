from __future__ import annotations

"""Deprecated direct-publish X Studio.

Kept as a compatibility launcher, but it now opens the safe X importer so X
items enter the unified SQLite pipeline before scoring, scheduling and publish.
"""

from x_ui import main


if __name__ == "__main__":
    main()
