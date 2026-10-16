"""TikTok uploader using Playwright with persistent session."""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")


@dataclass
class TikTokUploaderConfig:
    profile_dir: Path
    storage_state: Path
    headless: bool
    upload_url: str
    publish_timeout_sec: int
    max_retries: int

    @classmethod
    def from_env(cls) -> "TikTokUploaderConfig":
        return cls(
            profile_dir=Path(os.getenv("TIKTOK_PROFILE_DIR", str(BASE_DIR / "data" / "tiktok_profile"))),
            storage_state=Path(
                os.getenv("TIKTOK_STORAGE_STATE", str(BASE_DIR / "data" / "tiktok_storage_state.json"))
            ),
            headless=os.getenv("TIKTOK_HEADLESS", "0") == "1",
            upload_url=os.getenv("TIKTOK_UPLOAD_URL", "https://www.tiktok.com/upload"),
            publish_timeout_sec=max(30, int(os.getenv("TIKTOK_PUBLISH_TIMEOUT_SEC", "180"))),
            max_retries=max(1, int(os.getenv("TIKTOK_MAX_RETRIES", "3"))),
        )


class TikTokUploader:
    def __init__(self, cfg: TikTokUploaderConfig, logger: Optional[logging.Logger] = None) -> None:
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)
        self.cfg.profile_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.storage_state.parent.mkdir(parents=True, exist_ok=True)

    def _open_context(self, *, headless: bool):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(
                "Playwright no esta disponible. Instala dependencias y ejecuta: playwright install chromium"
            ) from exc

        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(self.cfg.profile_dir),
            headless=headless,
            viewport={"width": 1366, "height": 900},
            args=["--disable-dev-shm-usage"],
        )
        context.set_default_timeout(self.cfg.publish_timeout_sec * 1000)
        context.set_default_navigation_timeout(self.cfg.publish_timeout_sec * 1000)

        self._load_cookies_from_storage_state(context)
        return pw, context

    def _close_context(self, state: Tuple[Any, Any]) -> None:
        pw, context = state
        try:
            context.storage_state(path=str(self.cfg.storage_state))
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass

    def _load_cookies_from_storage_state(self, context: Any) -> None:
        if not self.cfg.storage_state.exists():
            return
        try:
            payload = json.loads(self.cfg.storage_state.read_text(encoding="utf-8"))
        except Exception:
            return
        cookies = payload.get("cookies") if isinstance(payload, dict) else None
        if not isinstance(cookies, list) or not cookies:
            return
        try:
            context.add_cookies(cookies)
            self.logger.debug("Cookies loaded from storage_state")
        except Exception:
            self.logger.debug("Could not inject cookies from storage_state")

    def login(self) -> Dict[str, Any]:
        state = self._open_context(headless=False)
        pw, context = state
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
            print("Inicia sesion manualmente en la ventana del navegador.")
            input("Presiona ENTER cuando el login este completo... ")
            context.storage_state(path=str(self.cfg.storage_state))
            self.logger.info("TikTok login state saved at %s", self.cfg.storage_state)
            return {"status": "ok", "storage_state": str(self.cfg.storage_state)}
        finally:
            self._close_context((pw, context))

    def upload(self, video_path: str, caption: str) -> Dict[str, Any]:
        path = Path(video_path)
        if not path.exists():
            return {"status": "error", "error": "video_not_found", "video": str(path)}

        error_text = "unknown"
        for attempt in range(1, self.cfg.max_retries + 1):
            self.logger.info("TikTok upload attempt %s/%s for %s", attempt, self.cfg.max_retries, path.name)
            try:
                result = self._upload_once(path, caption)
                if result.get("status") == "published":
                    return result
                error_text = str(result.get("error") or "upload_failed")
            except Exception as exc:
                error_text = str(exc)
                self.logger.exception("TikTok upload attempt failed")

            if attempt < self.cfg.max_retries:
                backoff = min(20, 2 ** attempt)
                time.sleep(backoff)

        return {"status": "error", "error": error_text, "video": str(path)}

    def _upload_once(self, video_path: Path, caption: str) -> Dict[str, Any]:
        state = self._open_context(headless=self.cfg.headless)
        pw, context = state
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(self.cfg.upload_url, wait_until="domcontentloaded")
            self._dismiss_cookie_banner(page)

            file_input = page.locator("input[type='file']").first
            file_input.wait_for(state="attached", timeout=60_000)
            file_input.set_input_files(str(video_path))
            self.logger.info("Video file attached: %s", video_path)

            self._fill_caption(page, caption)
            self._wait_post_button_enabled(page)
            self._click_post(page)

            post_url = self._wait_publish_confirmation(page)
            context.storage_state(path=str(self.cfg.storage_state))
            return {"status": "published", "post_url": post_url or "", "video": str(video_path)}
        finally:
            self._close_context((pw, context))

    def _dismiss_cookie_banner(self, page: Any) -> None:
        selectors = [
            "button:has-text('Accept all')",
            "button:has-text('Allow all')",
            "button:has-text('Aceptar todo')",
            "button:has-text('Aceptar')",
        ]
        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                if locator.first.is_visible(timeout=1200):
                    locator.first.click(timeout=1500)
                    self.logger.debug("Cookie banner dismissed")
                    return
            except Exception:
                continue

    def _fill_caption(self, page: Any, caption: str) -> None:
        value = (caption or "").strip()
        if not value:
            return

        selectors = [
            "div[data-e2e='video-caption'] div[contenteditable='true']",
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
            "textarea",
        ]

        for selector in selectors:
            locator = page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                target = locator.first
                target.click(timeout=3000)
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
                target.type(value, delay=6)
                self.logger.info("Caption set using selector: %s", selector)
                return
            except Exception:
                continue

        self.logger.warning("Caption textbox not found; continuing without replacing caption")

    def _wait_post_button_enabled(self, page: Any) -> None:
        deadline = time.time() + self.cfg.publish_timeout_sec
        while time.time() < deadline:
            button = self._find_post_button(page)
            if button is not None:
                try:
                    if button.is_enabled():
                        return
                except Exception:
                    pass
            time.sleep(2)
        raise RuntimeError("post_button_not_enabled")

    def _find_post_button(self, page: Any):
        candidates = [
            page.get_by_role("button", name=re.compile(r"^Post$", re.I)),
            page.get_by_role("button", name=re.compile(r"^Publicar$", re.I)),
            page.get_by_role("button", name=re.compile(r"Post|Publicar", re.I)),
            page.locator("button:has-text('Post')"),
            page.locator("button:has-text('Publicar')"),
        ]
        for locator in candidates:
            try:
                if locator.count() > 0 and locator.first.is_visible(timeout=500):
                    return locator.first
            except Exception:
                continue
        return None

    def _click_post(self, page: Any) -> None:
        button = self._find_post_button(page)
        if button is None:
            html_path = BASE_DIR / "data" / "tiktok_upload_debug.html"
            try:
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            raise RuntimeError("post_button_not_found")

        button.click(timeout=8000)
        self.logger.info("Post button clicked")

    def _wait_publish_confirmation(self, page: Any) -> str:
        deadline = time.time() + self.cfg.publish_timeout_sec
        while time.time() < deadline:
            current_url = page.url or ""
            if "/video/" in current_url:
                return current_url

            link_locator = page.locator("a[href*='/video/']")
            try:
                if link_locator.count() > 0:
                    href = link_locator.first.get_attribute("href") or ""
                    if href:
                        if href.startswith("http"):
                            return href
                        return f"https://www.tiktok.com{href}"
            except Exception:
                pass

            success_markers = [
                "Your video has been uploaded",
                "Your video is being uploaded",
                "Video uploaded",
                "Tu video se publico",
                "Tu video se esta subiendo",
            ]
            for marker in success_markers:
                if page.locator(f"text={marker}").count() > 0:
                    return current_url

            time.sleep(2)

        raise RuntimeError("publish_confirmation_timeout")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TikTok uploader via Playwright")
    parser.add_argument("--login", action="store_true", help="Open browser for manual login")
    parser.add_argument("--upload", action="store_true", help="Upload a video")
    parser.add_argument("--video", help="Path to MP4")
    parser.add_argument("--caption", default="", help="Video caption")
    parser.add_argument("--headless", type=int, choices=[0, 1], help="Override headless mode")
    parser.add_argument("--timeout", type=int, help="Override publish timeout in seconds")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args()
    cfg = TikTokUploaderConfig.from_env()
    if args.headless is not None:
        cfg.headless = args.headless == 1
    if args.timeout:
        cfg.publish_timeout_sec = max(30, int(args.timeout))

    uploader = TikTokUploader(cfg)

    if args.login:
        result = uploader.login()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.upload:
        if not args.video:
            raise RuntimeError("--video es requerido con --upload")
        result = uploader.upload(args.video, args.caption)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    raise RuntimeError("Usa --login o --upload")


if __name__ == "__main__":
    main()
