from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date

import httpx

from house_finder.models import House

_DEMO_SEED = 42

_US_STATE_ABBR: dict[str, str] = {
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
    "District of Columbia": "DC",
}


@dataclass(frozen=True)
class ZipLocation:
    latitude: float
    longitude: float
    city: str
    state: str


def _state_abbrev(address: dict) -> str:
    iso = address.get("ISO3166-2-lvl4", "")
    if isinstance(iso, str) and iso.startswith("US-") and len(iso) >= 4:
        return iso[3:5].upper()
    state = str(address.get("state", "")).strip()
    if len(state) == 2:
        return state.upper()
    return _US_STATE_ABBR.get(state, state[:2].upper() if state else "US")


def _city_from_address(address: dict) -> str:
    for key in ("city", "town", "village", "hamlet", "municipality"):
        name = address.get(key)
        if name:
            return str(name)
    county = address.get("county")
    if county:
        return str(county).replace(" County", "")
    return "Unknown"


def geocode_zip(zip_code: str) -> ZipLocation:
    """Resolve zip center, city, and state via Nominatim."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "postalcode": zip_code.strip(),
        "country": "USA",
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = {"User-Agent": "house-finder/1.0"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        results = resp.json()
    if not results:
        raise ValueError(f"Could not locate zip code {zip_code!r} on the map.")
    row = results[0]
    address = row.get("address") or {}
    return ZipLocation(
        latitude=float(row["lat"]),
        longitude=float(row["lon"]),
        city=_city_from_address(address),
        state=_state_abbrev(address),
    )


def generate_demo_houses(
    zip_code: str,
    *,
    min_age: int = 20,
    max_age: int = 40,
    count: int = 45,
) -> list[House]:
    """Synthetic properties near the zip center for offline UI testing."""
    loc = geocode_zip(zip_code)
    rng = random.Random(_DEMO_SEED + hash(zip_code) % 10_000)
    ref_year = date.today().year
    if min_age > max_age:
        min_age, max_age = max_age, min_age
    streets = [
        "Oak St",
        "Maple Ave",
        "Pine Rd",
        "Cedar Ln",
        "Elm Dr",
        "Birch Ct",
        "Willow Way",
        "Ash Blvd",
        "Cherry Pl",
        "Walnut Ter",
    ]
    houses: list[House] = []
    for i in range(count):
        age_years = rng.randint(min_age, max_age)
        year_built = ref_year - age_years
        angle = (i / count) * 2 * math.pi
        radius = 0.008 + rng.random() * 0.012
        lat = loc.latitude + radius * math.cos(angle)
        lon = loc.longitude + radius * math.sin(angle)
        street_num = 100 + i * 17
        street = streets[i % len(streets)]
        base_value = 180_000 + age_years * 8_000 + rng.randint(-40_000, 80_000)
        houses.append(
            House(
                id=f"demo-{zip_code}-{i}",
                address=f"{street_num} {street}",
                city=loc.city,
                state=loc.state,
                zip_code=zip_code.strip(),
                year_built=year_built,
                estimated_value=base_value,
                latitude=lat,
                longitude=lon,
                property_type="Single Family",
                bedrooms=rng.randint(2, 5),
                bathrooms=rng.choice([1.0, 1.5, 2.0, 2.5, 3.0]),
                square_footage=rng.randint(1100, 3200),
            )
        )
    return houses
