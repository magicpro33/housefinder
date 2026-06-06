from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def _cache_path(zip_code: str) -> Path:
    return CACHE_DIR / f"{zip_code.strip()}.json"


def has_cached_zip(zip_code: str) -> bool:
    return _cache_path(zip_code).is_file()


def load_cached_records(zip_code: str) -> list[dict[str, Any]] | None:
    """Return stored API records for a zip, or None if not cached."""
    path = _cache_path(zip_code)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        return None
    return [r for r in records if isinstance(r, dict)]


def save_cached_records(zip_code: str, records: list[dict[str, Any]]) -> None:
    """Persist all property records returned by RentCast for this zip."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "zip_code": zip_code.strip(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "records": records,
    }
    path = _cache_path(zip_code)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
