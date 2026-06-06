from __future__ import annotations

from house_finder.models import House


def matches_age_range(house: House, min_age: int, max_age: int) -> bool:
    age = house.age_years
    return min_age <= age <= max_age


def matches_value_range(
    house: House,
    min_value: int | None,
    max_value: int | None,
) -> bool:
    if min_value is not None and house.estimated_value < min_value:
        return False
    if max_value is not None and house.estimated_value > max_value:
        return False
    return True


def filter_houses(
    houses: list[House],
    min_age: int,
    max_age: int,
    min_value: int | None,
    max_value: int | None,
) -> list[House]:
    if min_age > max_age:
        min_age, max_age = max_age, min_age
    out: list[House] = []
    for house in houses:
        if not matches_age_range(house, min_age, max_age):
            continue
        if not matches_value_range(house, min_value, max_value):
            continue
        out.append(house)
    return sorted(out, key=lambda h: h.address)
