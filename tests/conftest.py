"""Tests never reach a real LLM: blank the keys before storage.settings loads .env.

load_dotenv does not override variables that already exist, so setting them
empty here wins over the production keys in .env. Tests that need a key patch
it explicitly.
"""
import os

for _name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
    os.environ[_name] = ""
