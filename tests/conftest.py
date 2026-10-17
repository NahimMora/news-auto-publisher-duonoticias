"""Tests never see production credentials: blank them before .env loads.

load_dotenv does not override variables that already exist, so setting them
empty here wins over the production values in .env (LLM keys, Meta token/IDs,
R2). Tests that need a value patch it explicitly.
"""
import os

for _name in (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "META_ACCESS_TOKEN",
    "META_IG_USER_ID",
    "META_PAGE_ID",
    "MEDIA_STORAGE_PROVIDER",
    "R2_ACCOUNT_ID",
    "R2_ENDPOINT_URL",
    "R2_BUCKET",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_PUBLIC_BASE_URL",
    "X_MODE",
):
    os.environ[_name] = ""

# The motion engine (Node render worker) is exercised by its own tests with a
# fake worker; the rest of the suite keeps the legacy formatter.
os.environ["DUO_MOTION_ENGINE"] = "0"

# Shared Meta rate-limit state must not leak between production and tests.
import tempfile as _tempfile

os.environ["DUO_RATE_LIMITS_PATH"] = os.path.join(_tempfile.mkdtemp(prefix="duo_rl_"), "meta_rate_limits.json")
