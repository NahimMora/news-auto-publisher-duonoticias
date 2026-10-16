from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from extractors.news.common import content_from_raw
from extractors.registry import SourceRegistry
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings


SOURCE_CONFIG = {
    "paparazzi": {
        "deprecated_command_reference": ["scrapping/paparazzi/main_paparazzi.py"],
        "pattern": "nuevas_noticias_paparazzi*.json",
        "source_type": "news",
    },
    "noticiasargentinas": {
        "deprecated_command_reference": ["scrapping/noticiasargentinas/main_noticiasargentinas.py"],
        "pattern": "nuevas_noticias_noticiasargentinas*.json",
        "source_type": "news",
    },
    "tn": {
        "pattern": "",
        "source_type": "news",
    },
    "infobae": {
        "pattern": "",
        "source_type": "news",
    },
}


class LegacyNewsExtractor:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.registry = SourceRegistry(self.settings)

    def run(self, source: str, max_items: int | None = None) -> List[ExtractedContent]:
        return self.registry.scan_source(source, max_items=max_items)

    def load_existing(self, source: str, file_path: str | Path) -> List[ExtractedContent]:
        config = SOURCE_CONFIG[source]
        return self._load_file(Path(file_path), source=source, source_type=config["source_type"])

    def _latest_file_since(self, pattern: str, started_at: float) -> Optional[Path]:
        candidates = [
            path
            for path in self.settings.data_dir.glob(pattern)
            if path.stat().st_mtime >= started_at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _load_file(self, file_path: Path, *, source: str, source_type: str) -> List[ExtractedContent]:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("noticias") or []
        if not isinstance(payload, list):
            return []
        items: List[ExtractedContent] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            content = self._to_content(raw, source=source, source_type=source_type)
            items.append(content)
        return items

    def _to_content(self, raw: Dict[str, object], *, source: str, source_type: str) -> ExtractedContent:
        content = content_from_raw(source=source, source_type=source_type, raw=raw)
        content.ranking_signals["origin_file"] = file_path_name(raw)
        return content


def file_path_name(raw: Dict[str, object]) -> str:
    value = str(raw.get("origen_archivo") or "").strip()
    return Path(value).name if value else ""
