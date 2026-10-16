"""
Configuration for Paparazzi scraper.
"""
from pathlib import Path
import os
import random

# Paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_PATH = PROJECT_ROOT / "data"
FOTOS_PATH = DATA_PATH / "fotos"
VIDEOS_PATH = DATA_PATH / "videos"
HISTORICO_PATH = DATA_PATH / "noticias_ejecutadas_paparazzi.json"
LOGS_PATH = PROJECT_ROOT / "logs"

# Site
BASE_URL = os.getenv("PAPARAZZI_BASE_URL", "https://www.paparazzi.com.ar")
WP_API_BASE = os.getenv("PAPARAZZI_WP_API", f"{BASE_URL}/wp-json/wp/v2")
POSTS_ENDPOINT = f"{WP_API_BASE}/posts"

# Request tuning
REQUEST_TIMEOUT = int(os.getenv("PAPARAZZI_TIMEOUT", "30"))
PER_PAGE = int(os.getenv("PAPARAZZI_PER_PAGE", "20"))
MAX_PAGES = int(os.getenv("PAPARAZZI_MAX_PAGES", "5"))
VIDEO_DOWNLOAD_TIMEOUT = int(os.getenv("PAPARAZZI_VIDEO_TIMEOUT", "60"))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

# Filters
IMAGE_EXCLUDE_PATTERNS = [
    "logo",
    "icon",
    "avatar",
    "placeholder",
    "sprite",
    "lazy",
]

TEXT_EXCLUDE_PATTERNS = [
    "Mira tambien",
    "Segui leyendo",
    "Suscribite",
    "Newsletter",
    "Publicidad",
    "Contenido patrocinado",
]

# History limits
MAX_CONSECUTIVE_ERRORS = int(os.getenv("PAPARAZZI_MAX_ERRORS", "3"))
CONTINUE_ON_ERROR = os.getenv("PAPARAZZI_CONTINUE_ON_ERROR", "1") != "0"
