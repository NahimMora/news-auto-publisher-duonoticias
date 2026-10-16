from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_yaml_config(path: Path) -> Dict[str, Any]:
    """Load YAML with PyYAML when available, with a tiny fallback for simple repo configs."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(text) or {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return _parse_minimal_yaml(text)


def _parse_minimal_yaml(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    current_key = ""
    current_item: Dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and line.endswith(":"):
            current_key = line[:-1].strip()
            data[current_key] = []
            current_item = None
            continue
        if current_key and line.startswith("- "):
            value = line[2:].strip()
            if ":" in value:
                key, raw_value = value.split(":", 1)
                current_item = {key.strip(): _coerce_scalar(raw_value.strip())}
            else:
                current_item = {"value": _coerce_scalar(value)}
            data.setdefault(current_key, []).append(current_item)
            continue
        if current_key and current_item is not None and ":" in line:
            key, raw_value = line.split(":", 1)
            current_item[key.strip()] = _coerce_scalar(raw_value.strip())
            continue
        if indent == 0 and ":" in line:
            key, raw_value = line.split(":", 1)
            data[key.strip()] = _coerce_scalar(raw_value.strip())
    return data


def _coerce_scalar(value: str) -> Any:
    cleaned = value.strip().strip('"').strip("'")
    lowered = cleaned.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return cleaned

