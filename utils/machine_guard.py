"""Single place for the "real production only on FERNANDO" rule.

Every component that can publish or send outside this machine (Meta/TikTok
publishers, Duo web delivery, the HolaSalta bridge) must go through here.
"""
from __future__ import annotations

import os
import socket

PRODUCTION_COMPUTERNAME = "FERNANDO"


def current_computer_name() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname()


def is_production_machine() -> bool:
    return current_computer_name().upper() == PRODUCTION_COMPUTERNAME


def assert_production_machine(action: str = "Modo real") -> None:
    if not is_production_machine():
        raise RuntimeError(
            f"{action} bloqueado en {current_computer_name()!r}; solo se permite en la PC "
            f"{PRODUCTION_COMPUTERNAME}. Use --dry-run o --verify."
        )
