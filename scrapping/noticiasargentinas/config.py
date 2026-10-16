"""Configuracion para scraper de Noticias Argentinas."""
from pathlib import Path
import os
import random

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_PATH = PROJECT_ROOT / "data"
FOTOS_PATH = DATA_PATH / "fotos"
HISTORICO_PATH = DATA_PATH / "noticias_ejecutadas_noticiasargentinas.json"
LOGS_PATH = PROJECT_ROOT / "logs"

BASE_URL = "https://noticiasargentinas.com"
HOMEPAGE_URL = "https://noticiasargentinas.com"

REQUEST_TIMEOUT = int(os.getenv("NA_TIMEOUT", "25"))
HTTP_RETRIES = int(os.getenv("NA_HTTP_RETRIES", "3"))
HTTP_BACKOFF_BASE = float(os.getenv("NA_HTTP_BACKOFF", "1.6"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


def get_random_user_agent():
    return random.choice(USER_AGENTS)


URL_EXCLUDE_PATTERNS = [
    "/contenidos/",
    "/css-",
    "/services/",
    "/static/",
    "/assets/",
    "/wp-content/",
    "/authors/",
    "/tags/",
    "/categoria",
    "/buscar",
    "/search",
    "#",
    "javascript:",
    ".jpg",
    ".png",
    ".gif",
    ".css",
    ".js",
    "/amp/",
]

IMAGE_EXCLUDE_PATTERNS = [
    "lazy.svg",
    "/authors/",
    "/avatar/",
    "profile_images",
    "logo",
    "icon",
    "placeholder",
]

TEXT_EXCLUDE_PATTERNS = [
    "Suscribite",
    "Te puede interesar",
    "Informate mas",
    "Deja tu comentario",
    "Enlaces Patrocinados",
    "Enlaces Promovidos",
    "Contenido Premium",
    "#AgenciaNA",
]

# Overlay branding for OG images (simple black banner)
NA_OVERLAY_BOX_COLOR = (0, 0, 0)
NA_OVERLAY_BOX_REL_W = 0.42
NA_OVERLAY_BOX_REL_H = 0.18
NA_OVERLAY_BOX_POSITION = "bottom_left"
NA_OVERLAY_LOGO_MARGIN = 0

MAX_CONSECUTIVE_ERRORS = int(os.getenv("NA_MAX_ERRORS", "3"))
CONTINUE_ON_ERROR = os.getenv("NA_CONTINUE_ON_ERROR", "1") != "0"

