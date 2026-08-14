from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


@dataclass(frozen=True)
class CachedZipInfo:
    zip_code: str
    fetched_at: str
    record_count: int
    city: str = ""
    state: str = ""

    @property
    def fetched_display(self) -> str:
        raw = self.fetched_at
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local = dt.astimezone()
            return local.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return raw[:16] if len(raw) > 16 else raw

    @property
    def location_label(self) -> str:
        if self.city and self.state:
            return f"{self.city}, {self.state}"
        return self.city or self.state or ""

    @property
    def summary(self) -> str:
        loc = f"{self.location_label} · " if self.location_label else ""
        return f"{loc}{self.record_count} records · cached {self.fetched_display}"


def _majority_location(records: list[dict[str, Any]]) -> tuple[str, str]:
    """Return the most common city/state pair from cached property records."""
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        city = str(record.get("city") or "").strip()
        state = str(record.get("state") or "").strip()
        if not city and not state:
            continue
        key = (city, state)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "", ""
    city, state = max(counts.items(), key=lambda item: item[1])[0]
    return city, state


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


def cache_summary(zip_code: str) -> str | None:
    info = get_cached_zip_info(zip_code)
    if info is None:
        return None
    return f"cached {info.record_count} records from {info.fetched_at}"


def get_cached_zip_info(zip_code: str) -> CachedZipInfo | None:
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
    count = payload.get("record_count")
    if not isinstance(count, int):
        count = len(records) if isinstance(records, list) else 0
    city, state = "", ""
    if isinstance(records, list):
        city, state = _majority_location(records)
    return CachedZipInfo(
        zip_code=zip_code.strip(),
        fetched_at=str(payload.get("fetched_at", "unknown")),
        record_count=count,
        city=city,
        state=state,
    )


def list_cached_zips() -> list[CachedZipInfo]:
    """Return metadata for every zip code saved under data/cache/."""
    if not CACHE_DIR.is_dir():
        return []
    results: list[CachedZipInfo] = []
    for path in CACHE_DIR.glob("*.json"):
        zip_code = path.stem
        if len(zip_code) != 5 or not zip_code.isdigit():
            continue
        info = get_cached_zip_info(zip_code)
        if info is not None:
            results.append(info)
    return sorted(results, key=lambda item: item.zip_code)
