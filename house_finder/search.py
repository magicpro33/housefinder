from __future__ import annotations

import os
from typing import Callable

from house_finder.demo import generate_demo_houses
from house_finder.filters import filter_houses
from house_finder.models import House
from house_finder.rentcast import fetch_properties_by_zip


def fetch_houses_in_zip(
    zip_code: str,
    *,
    use_demo: bool = False,
    api_key: str | None = None,
    min_age: int = 20,
    max_age: int = 40,
    log: Callable[[str], None] | None = None,
    force_refresh: bool = False,
) -> tuple[list[House], str, bool]:
    """Load properties for a zip (demo or RentCast).

    Returns (houses, source_label, api_limit_notify).
    """
    zip_code = zip_code.strip()
    if len(zip_code) != 5 or not zip_code.isdigit():
        raise ValueError("Enter a valid 5-digit US zip code.")

    if use_demo:
        if log:
            log("Using demo data (demo mode enabled).")
        raw = generate_demo_houses(zip_code, min_age=min_age, max_age=max_age)
        return raw, "demo", False

    key = (api_key or os.environ.get("RENTCAST_API_KEY", "")).strip()
    if not key:
        raise ValueError(
            "RentCast API key required. Enter a key in the sidebar, add Streamlit Secrets, "
            "or enable demo mode. Free key: https://app.rentcast.io/app/api"
        )

    if log:
        log(f"Loading property data for zip {zip_code}…")
    raw, from_cache, api_limit_notify = fetch_properties_by_zip(
        zip_code, key, log=log, force_refresh=force_refresh
    )
    source = "rentcast-cache" if from_cache else "rentcast"
    return raw, source, api_limit_notify


def search_houses(
    zip_code: str,
    min_age: int,
    max_age: int,
    min_value: int | None,
    max_value: int | None,
    *,
    use_demo: bool = False,
    api_key: str | None = None,
    log: Callable[[str], None] | None = None,
    force_refresh: bool = False,
) -> tuple[list[House], str, list[House], bool]:
    """Fetch properties in zip and apply age/value filters."""
    if min_age < 0 or max_age < 0:
        raise ValueError("House age must be zero or greater.")
    if min_age > max_age:
        min_age, max_age = max_age, min_age

    raw, source, api_limit_notify = fetch_houses_in_zip(
        zip_code,
        use_demo=use_demo,
        api_key=api_key,
        min_age=min_age,
        max_age=max_age,
        log=log,
        force_refresh=force_refresh,
    )
    filtered = filter_houses(raw, min_age, max_age, min_value, max_value)
    if log:
        log(
            f"Found {len(filtered)} homes aged {min_age}–{max_age} years "
            f"(from {len(raw)} in zip)."
        )
    return filtered, source, raw, api_limit_notify
