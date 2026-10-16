from __future__ import annotations

import json
import shutil
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
STORAGE_STATE = DATA_DIR / "x_storage_state.json"
PROFILE_DIR = DATA_DIR / "x_playwright_profile"
X_HOME_URL = "https://x.com/home"
X_LOGIN_URL = "https://x.com/i/flow/login"

REQUIRED_COOKIE_NAMES = {"auth_token", "ct0"}


def _read_storage_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cookie_names(payload: dict) -> set[str]:
    cookies = payload.get("cookies")
    if not isinstance(cookies, list):
        return set()
    names: set[str] = set()
    for item in cookies:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                names.add(name)
    return names


def _storage_is_authenticated(path: Path) -> bool:
    payload = _read_storage_state(path)
    names = _cookie_names(payload)
    return REQUIRED_COOKIE_NAMES.issubset(names)


def _clear_stale_session() -> None:
    removed = False
    if STORAGE_STATE.exists() and not _storage_is_authenticated(STORAGE_STATE):
        STORAGE_STATE.unlink(missing_ok=True)
        removed = True
    if PROFILE_DIR.exists() and not any(PROFILE_DIR.iterdir()):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        removed = True
    if removed:
        print("Sesion anterior invalida eliminada.")


def _launch_context(playwright):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    common_kwargs = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": False,
        "viewport": {"width": 1365, "height": 900},
        "locale": "es-AR",
        "timezone_id": "America/Buenos_Aires",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ],
    }
    try:
        return playwright.chromium.launch_persistent_context(channel="chrome", **common_kwargs)
    except PlaywrightError:
        return playwright.chromium.launch_persistent_context(**common_kwargs)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _clear_stale_session()

    print(f"Perfil persistente: {PROFILE_DIR}")
    print(f"Storage state: {STORAGE_STATE}")
    print("Se va a abrir un navegador con perfil persistente.")
    print("Inicia sesion en X. Cuando veas tu home o el feed de inicio, vuelve a la consola y presiona ENTER.")

    with sync_playwright() as playwright:
        context = _launch_context(playwright)
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined,
            });
            window.chrome = window.chrome || { runtime: {} };
            """
        )
        page = context.new_page()
        page.goto(X_HOME_URL, wait_until="domcontentloaded", timeout=60000)
        if "/i/flow/login" in page.url or "/login" in page.url:
            page.goto(X_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        input("Presiona ENTER cuando el login este completo... ")
        context.storage_state(path=str(STORAGE_STATE))
        context.close()

    if not _storage_is_authenticated(STORAGE_STATE):
        print("La sesion se guardo pero no quedaron cookies de autenticacion. Repeti el login.")
        return 1

    payload = _read_storage_state(STORAGE_STATE)
    print(f"Sesion guardada. Cookies: {len(payload.get('cookies') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
