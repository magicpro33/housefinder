from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class House:
    """A residential property matching search criteria."""

    id: str
    address: str
    city: str
    state: str
    zip_code: str
    year_built: int
    estimated_value: int
    latitude: float
    longitude: float
    property_type: str = ""
    bedrooms: int | None = None
    bathrooms: float | None = None
    square_footage: int | None = None

    @property
    def age_years(self) -> int:
        return date.today().year - self.year_built

    @property
    def full_address(self) -> str:
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"

    def tooltip_text(self) -> str:
        beds = f"{self.bedrooms} bed" if self.bedrooms is not None else ""
        baths = f"{self.bathrooms} bath" if self.bathrooms is not None else ""
        extras = ", ".join(x for x in (beds, baths) if x)
        extra_line = f"\n{extras}" if extras else ""
        return (
            f"{self.full_address}\n"
            f"Built: {self.year_built} ({self.age_years} years old)\n"
            f"Est. value: ${self.estimated_value:,}"
            f"{extra_line}"
        )
