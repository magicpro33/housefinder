from __future__ import annotations

from datetime import datetime
from pathlib import Path

from house_finder.models import House


def format_houses_report(
    houses: list[House],
    *,
    zip_code: str = "",
    source: str = "",
) -> str:
    lines = [
        "House Finder — Search Results",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    if zip_code:
        lines.append(f"Zip code: {zip_code}")
    if source:
        lines.append(f"Data source: {source}")
    lines.append(f"Properties: {len(houses)}")
    lines.append("")
    lines.append(
        "Address\tAge (yr)\tYear built\tEst. value\tLatitude\tLongitude"
    )
    for house in houses:
        lines.append(
            f"{house.full_address}\t{house.age_years}\t{house.year_built}\t"
            f"${house.estimated_value:,}\t{house.latitude}\t{house.longitude}"
        )
    return "\n".join(lines) + "\n"


def save_houses_to_file(
    path: Path,
    houses: list[House],
    *,
    zip_code: str = "",
    source: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        format_houses_report(houses, zip_code=zip_code, source=source),
        encoding="utf-8",
    )
