from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

DEFAULT_USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "api_usage.json"


def _current_month_key() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def _ensure_current_month(state: dict) -> dict:
    month = _current_month_key()
    if state.get("month") != month:
        return {"month": month, "count": 0, "limit_notice_shown": False}
    return {
        "month": month,
        "count": int(state.get("count", 0)),
        "limit_notice_shown": bool(state.get("limit_notice_shown", False)),
    }


def load_usage(path: Path | None = None) -> dict:
    usage_path = path or DEFAULT_USAGE_PATH
    if not usage_path.exists():
        return {"month": _current_month_key(), "count": 0, "limit_notice_shown": False}
    try:
        raw = json.loads(usage_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    return _ensure_current_month(raw)


def save_usage(state: dict, path: Path | None = None) -> None:
    usage_path = path or DEFAULT_USAGE_PATH
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def monthly_limit() -> int:
    raw = os.environ.get("RENTCAST_MONTHLY_LIMIT", "50").strip()
    if not raw:
        return 50
    try:
        return max(1, int(raw))
    except ValueError:
        return 50


def monthly_limit_hint() -> int | None:
    raw = os.environ.get("RENTCAST_MONTHLY_LIMIT", "50").strip()
    if not raw or raw == "0":
        return None
    return monthly_limit()


def record_rentcast_request(path: Path | None = None) -> tuple[int, bool]:
    state = load_usage(path)
    state["count"] = int(state.get("count", 0)) + 1
    limit = monthly_limit()
    notify = state["count"] >= limit and not state.get("limit_notice_shown", False)
    save_usage(state, path)
    return int(state["count"]), notify


def mark_limit_notice_shown(path: Path | None = None) -> None:
    state = load_usage(path)
    state["limit_notice_shown"] = True
    save_usage(state, path)


def should_show_limit_notice(path: Path | None = None) -> bool:
    state = load_usage(path)
    return state["count"] >= monthly_limit() and not state.get("limit_notice_shown", False)


def get_month_usage(path: Path | None = None) -> tuple[str, int]:
    state = load_usage(path)
    return str(state["month"]), int(state["count"])


def format_usage_status(path: Path | None = None) -> str:
    month_key, count = get_month_usage(path)
    try:
        month_label = datetime.strptime(month_key, "%Y-%m").strftime("%B %Y")
    except ValueError:
        month_label = month_key
    limit = monthly_limit_hint()
    if limit is not None:
        over = " — limit reached" if count >= limit else ""
        return f"RentCast API ({month_label}): {count} / {limit} requests — resets each month{over}"
    return f"RentCast API ({month_label}): {count} requests — resets each month"
