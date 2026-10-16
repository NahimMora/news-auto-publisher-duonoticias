"""Simple console logger for scrapers."""
from datetime import datetime
from pathlib import Path
import sys

class ScraperLogger:
    COLORS = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "DEBUG": "\033[95m",
        "RESET": "\033[0m",
    }

    def __init__(self, name="Scraper", log_file=None, debug=False):
        self.name = name
        self.log_file = log_file
        self.debug_mode = debug
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)

    def _log(self, level, message, color=True):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if color and sys.platform != "win32":
            color_code = self.COLORS.get(level, "")
            reset = self.COLORS["RESET"]
            formatted = f"{color_code}[{timestamp}] [{level}]{reset} {message}"
        else:
            formatted = f"[{timestamp}] [{level}] {message}"
        print(formatted)
        if self.log_file:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] [{level}] {message}\n")

    def info(self, message):
        self._log("INFO", message)

    def success(self, message):
        self._log("SUCCESS", message)

    def warning(self, message):
        self._log("WARNING", message)

    def error(self, message):
        self._log("ERROR", message)

    def debug(self, message):
        if self.debug_mode:
            self._log("DEBUG", message)

    def separator(self, char="=", length=60):
        print(char * length)

    def header(self, title):
        self.separator()
        print(f" {title.center(58)} ")
        self.separator()
