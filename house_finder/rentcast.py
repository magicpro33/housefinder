from __future__ import annotations

import os
from typing import Any

import httpx

from house_finder.api_usage import record_rentcast_request
from house_finder.models import House
from house_finder.zip_cache import load_cached_records, save_cached_records

RENTCAST_BASE = "https://api.rentcast.io/v1"


def _estimated_value(record: dict[str, Any]) -> int:
    if record.get("lastSalePrice"):
        return int(record["lastSalePrice"])
    assessments = record.get("taxAssessments") or {}
    if assessments:
        latest = max(assessments.keys(), key=lambda y: int(y))
        value = assessments[latest].get("value")
        if value:
            return int(value)
    return 0


def _parse_record(record: dict[str, Any]) -> House | None:
    year_built = record.get("yearBuilt")
    lat = record.get("latitude")
    lon = record.get("longitude")
    if year_built is None or lat is None or lon is None:
        return None
    value = _estimated_value(record)
    if value <= 0:
        return None
    address = record.get("formattedAddress") or record.get("addressLine1") or ""
    if not address:
        return None
    return House(
        id=str(record.get("id") or address),
        address=address,
        city=str(record.get("city") or ""),
        state=str(record.get("state") or ""),
        zip_code=str(record.get("zipCode") or ""),
        year_built=int(year_built),
        estimated_value=value,
        latitude=float(lat),
        longitude=float(lon),
        property_type=str(record.get("propertyType") or ""),
        bedrooms=record.get("bedrooms"),
        bathrooms=record.get("bathrooms"),
        square_footage=record.get("squareFootage"),
    )


def _records_to_houses(records: list[dict[str, Any]]) -> list[House]:
    houses: list[House] = []
    for record in records:
        house = _parse_record(record)
        if house:
            houses.append(house)
    return houses


def fetch_properties_by_zip(
    zip_code: str,
    api_key: str | None = None,
    *,
    limit: int = 500,
    log: Any = print,
    force_refresh: bool = False,
) -> tuple[list[House], bool, bool]:
    zip_code = zip_code.strip()

    if not force_refresh:
        cached = load_cached_records(zip_code)
        if cached is not None:
            houses = _records_to_houses(cached)[:limit]
            if log:
                log(
                    f"Using cached RentCast data for zip {zip_code} "
                    f"({len(cached)} records, {len(houses)} usable homes) — no API call."
                )
            return houses, True, False

    key = api_key or os.environ.get("RENTCAST_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "RentCast API key required. Set RENTCAST_API_KEY in .env or get a free key at "
            "https://app.rentcast.io/app/api"
        )

    headers = {"X-Api-Key": key, "Accept": "application/json"}
    all_records: list[dict[str, Any]] = []
    offset = 0
    page_size = min(500, limit)
    api_limit_notify = False

    with httpx.Client(timeout=60.0) as client:
        while len(all_records) < limit:
            params: dict[str, Any] = {
                "zipCode": zip_code,
                "limit": page_size,
                "offset": offset,
            }
            resp = client.get(f"{RENTCAST_BASE}/properties", headers=headers, params=params)
            _, notify = record_rentcast_request()
            api_limit_notify = api_limit_notify or notify
            if resp.status_code == 401:
                raise ValueError("Invalid RentCast API key.")
            if resp.status_code == 429:
                raise ValueError("RentCast API rate limit reached. Try again later.")
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list) or not data:
                break
            for record in data:
                if isinstance(record, dict):
                    all_records.append(record)
            if len(data) < page_size:
                break
            offset += page_size
            if offset >= limit:
                break

    save_cached_records(zip_code, all_records)
    houses = _records_to_houses(all_records)[:limit]
    if log:
        log(
            f"RentCast: fetched {len(all_records)} records for zip {zip_code} "
            f"({len(houses)} usable homes); saved to local cache."
        )
    return houses, False, api_limit_notify
