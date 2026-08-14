from __future__ import annotations

import os
from typing import Any

import httpx

from house_finder.api_usage import record_rentcast_request
from house_finder.models import House
from house_finder.zip_cache import load_cached_records, save_cached_records

RENTCAST_BASE = "https://api.rentcast.io/v1"

# When tax/assessment ratio exceeds this, the county value is likely missing trailing zeros.
# SC effective property-tax rates are often ~0.5–2% of market; 5% stopped scaling too early.
_MAX_TAX_TO_ASSESSMENT = 0.02
# Minimum plausible $/sqft after scaling (rural manufactured homes can be ~$10–15/sqft).
_MIN_SQFT_VALUE = 10
# If last-sale is far below a scaled tax assessment, prefer the assessment.
_SALE_VS_ASSESSMENT_FLOOR = 0.45


def _latest_sale_price(record: dict[str, Any]) -> int | None:
    if record.get("lastSalePrice"):
        return int(record["lastSalePrice"])
    history = record.get("history") or {}
    dated: list[tuple[str, int]] = []
    for key, entry in history.items():
        if not isinstance(entry, dict):
            continue
        price = entry.get("price")
        if price:
            dated.append((str(key), int(price)))
    if not dated:
        return None
    dated.sort(key=lambda item: item[0], reverse=True)
    return dated[0][1]


def _latest_tax_assessment(record: dict[str, Any]) -> tuple[int, str | None]:
    assessments = record.get("taxAssessments") or {}
    if not assessments:
        return 0, None
    latest_year = max(assessments.keys(), key=lambda y: int(y))
    entry = assessments[latest_year]
    if not isinstance(entry, dict):
        return 0, None
    value = entry.get("value")
    if not value:
        return 0, None
    return int(value), str(latest_year)


def _property_tax_for_year(record: dict[str, Any], year: str | None) -> float | None:
    if not year:
        return None
    taxes = record.get("propertyTaxes") or {}
    entry = taxes.get(year)
    if entry is None:
        entry = taxes.get(int(year))
    if not isinstance(entry, dict):
        return None
    total = entry.get("total")
    return float(total) if total else None


def _scale_assessment(raw: int, record: dict[str, Any], year: str | None) -> int:
    """
    Normalize tax assessments that counties report at the wrong scale.

    Some assessors (especially for manufactured homes in SC) store values like 132 or
    12050 when the real assessed amount should be 13200 or 120500. When property tax
    data exists for the same year, we infer the correction from the tax/assessment ratio.
    """
    if raw <= 0:
        return 0

    tax_total = _property_tax_for_year(record, year)
    if tax_total and tax_total > 0:
        rate = tax_total / raw
        if rate <= _MAX_TAX_TO_ASSESSMENT:
            return raw
        multiplier = 1
        while rate > _MAX_TAX_TO_ASSESSMENT and multiplier < 10_000:
            multiplier *= 10
            rate = tax_total / (raw * multiplier)
        if multiplier > 1:
            return int(raw * multiplier)

    sqft = record.get("squareFootage")
    if not sqft or int(sqft) <= 0:
        return raw

    sqft = int(sqft)
    if raw / sqft >= _MIN_SQFT_VALUE:
        return raw

    max_multiplier = 100 if raw < 1000 else 1000
    multiplier = 1
    while multiplier < max_multiplier and (raw * multiplier) / sqft < _MIN_SQFT_VALUE:
        multiplier *= 10
    scaled = int(raw * multiplier)
    if scaled / sqft >= _MIN_SQFT_VALUE:
        return scaled
    return raw


def _estimated_value(record: dict[str, Any]) -> int:
    sale = _latest_sale_price(record) or 0
    raw, year = _latest_tax_assessment(record)
    assessed = _scale_assessment(raw, record, year) if raw > 0 else 0

    if sale > 0 and assessed > 0:
        # Prefer assessment when recorded sale is unrealistically low vs tax-implied value.
        if sale < assessed * _SALE_VS_ASSESSMENT_FLOOR:
            return assessed
        return max(sale, assessed)
    if sale > 0:
        return sale
    return assessed


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
    """
    Fetch property records for a US zip code via RentCast.

    Returns (houses, from_cache, api_limit_notify). Cached zips do not call the API.
    """
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
