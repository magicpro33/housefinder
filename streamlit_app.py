"""Streamlit deployment entry point for House Finder."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from house_finder.models import House
from house_finder.search import search_houses
from house_finder.zip_cache import get_cached_zip_info, list_cached_zips


ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

st.set_page_config(page_title="House Finder", page_icon="🏠", layout="wide")


def _rentcast_key() -> str:
    """Get the key from Streamlit Cloud secrets first, then local environment."""
    try:
        return str(st.secrets.get("RENTCAST_API_KEY", "")).strip()
    except Exception:
        return os.environ.get("RENTCAST_API_KEY", "").strip()


@st.cache_data(show_spinner=False)
def _discover_cached_zips(_signature: str = "") -> list[dict]:
    """Scan data/cache for ZIP dumps and return a serializable inventory."""
    rows = []
    for info in list_cached_zips():
        rows.append(
            {
                "zip_code": info.zip_code,
                "record_count": info.record_count,
                "fetched_at": info.fetched_at,
                "fetched_display": info.fetched_display,
                "summary": info.summary,
            }
        )
    return rows


def _cache_dir_signature() -> str:
    from house_finder.zip_cache import CACHE_DIR

    if not CACHE_DIR.is_dir():
        return "missing"
    parts = []
    for path in sorted(CACHE_DIR.glob("*.json")):
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            continue
    return "|".join(parts) or "empty"


def _houses_frame(houses: list[House]) -> pd.DataFrame:
    rows = []
    for house in houses:
        rows.append(
            {
                "Address": house.address,
                "City": house.city,
                "State": house.state,
                "ZIP": house.zip_code,
                "Age": house.age_years,
                "Year built": house.year_built,
                "Estimated value": house.estimated_value,
                "Property type": house.property_type or "—",
                "Beds": house.bedrooms,
                "Baths": house.bathrooms,
                "Sq. ft.": house.square_footage,
                "Latitude": house.latitude,
                "Longitude": house.longitude,
            }
        )
    return pd.DataFrame(rows)


def _run_multi_search(
    zip_codes: list[str],
    min_age: int,
    max_age: int,
    min_value: int,
    max_value: int,
    refresh_from_api: bool,
) -> None:
    logs: list[str] = []
    all_houses: list[House] = []
    raw_total = 0
    sources: set[str] = set()
    api_limit_notice = False
    key = _rentcast_key()

    for zip_code in zip_codes:
        logs.append(f"── ZIP {zip_code} ──")
        houses, source, raw_houses, notify = search_houses(
            zip_code,
            min_age,
            max_age,
            min_value or None,
            max_value or None,
            api_key=key,
            log=logs.append,
            force_refresh=refresh_from_api,
        )
        all_houses.extend(houses)
        raw_total += len(raw_houses)
        sources.add(source)
        api_limit_notice = api_limit_notice or notify

    # De-dupe by property id when searching multiple ZIPs
    seen: set[str] = set()
    unique: list[House] = []
    for house in all_houses:
        if house.id in seen:
            continue
        seen.add(house.id)
        unique.append(house)

    if sources == {"rentcast-cache"}:
        source_label = "rentcast-cache"
    elif "rentcast" in sources and "rentcast-cache" in sources:
        source_label = "mixed"
    else:
        source_label = sources.pop() if sources else "unknown"

    st.session_state.search_results = unique
    st.session_state.raw_house_count = raw_total
    st.session_state.search_source = source_label
    st.session_state.search_zips = zip_codes
    st.session_state.search_logs = logs
    st.session_state.api_limit_notice = api_limit_notice


st.title("🏠 House Finder")
st.caption(
    "Cached ZIP dumps under data/cache are detected automatically and become "
    "the searchable ZIP list. Filters apply after load."
)

cache_inventory = _discover_cached_zips(_cache_dir_signature())
available_zips = [row["zip_code"] for row in cache_inventory]

if cache_inventory:
    with st.expander(
        f"Auto-detected cached ZIP codes ({len(available_zips)})",
        expanded=True,
    ):
        inv = pd.DataFrame(cache_inventory)[
            ["zip_code", "record_count", "fetched_display"]
        ].rename(
            columns={
                "zip_code": "ZIP",
                "record_count": "Records",
                "fetched_display": "Cached at",
            }
        )
        st.dataframe(inv, use_container_width=True, hide_index=True)
else:
    st.warning(
        "No cached ZIP files found in data/cache. "
        "Add `NNNNN.json` dumps or use RentCast API mode with a key."
    )

with st.sidebar:
    st.header("Search")

    if available_zips:
        st.success(f"{len(available_zips)} ZIP codes ready from cache")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Select all", use_container_width=True):
                st.session_state.zip_multiselect = list(available_zips)
        with col_b:
            if st.button("Clear", use_container_width=True):
                st.session_state.zip_multiselect = []
        if "zip_multiselect" not in st.session_state:
            st.session_state.zip_multiselect = [available_zips[0]]
        # Drop any stale selections if cache files changed
        st.session_state.zip_multiselect = [
            z for z in st.session_state.zip_multiselect if z in available_zips
        ]
        selected_zips = st.multiselect(
            "ZIP codes to search",
            options=available_zips,
            key="zip_multiselect",
            help="Built automatically from data/cache/*.json",
        )
        source_mode = st.radio(
            "Data source",
            ["Stored ZIP data", "RentCast API"],
            help="Stored data needs no API key. API mode can refresh selected ZIPs.",
        )
        refresh_from_api = (
            source_mode == "RentCast API"
            and st.checkbox(
                "Refresh selected ZIPs from RentCast",
                help="Uses the RentCast API and overwrites cache files on this host.",
            )
        )
        if source_mode == "RentCast API" and not _rentcast_key():
            st.warning(
                "Add RENTCAST_API_KEY to Streamlit secrets before using the live API."
            )
    else:
        selected_zips = []
        st.text_input("ZIP code (live API only)", key="manual_zip", max_chars=5)
        refresh_from_api = True
        if not _rentcast_key():
            st.warning("No cache and no RENTCAST_API_KEY — nothing to search yet.")

    # Optional: type a ZIP not in the cache list (API mode / new dumps)
    extra_zip = st.text_input(
        "Add another ZIP (optional)",
        max_chars=5,
        help="Include a ZIP that is not in the auto-detected list (API key required if uncached).",
    ).strip()
    if extra_zip and len(extra_zip) == 5 and extra_zip.isdigit():
        if extra_zip not in selected_zips:
            selected_zips = [*selected_zips, extra_zip]

    age_range = st.slider("House age (years)", min_value=0, max_value=150, value=(20, 40))
    value_range = st.slider(
        "Estimated value ($)",
        min_value=0,
        max_value=2_000_000,
        value=(0, 1_500_000),
        step=25_000,
    )
    submitted = st.button(
        "Search homes",
        type="primary",
        use_container_width=True,
        disabled=not selected_zips,
    )

    st.divider()
    st.caption(
        "ZIP list is generated by scanning data/cache on each app load. "
        "On Streamlit Cloud, new API cache files are temporary unless committed to GitHub."
    )

if submitted:
    if not selected_zips:
        st.error("Select at least one ZIP code from the auto-generated list.")
    else:
        try:
            label = ", ".join(selected_zips)
            with st.spinner(f"Searching {len(selected_zips)} ZIP code(s): {label}…"):
                _run_multi_search(
                    selected_zips,
                    age_range[0],
                    age_range[1],
                    value_range[0],
                    value_range[1],
                    refresh_from_api,
                )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

if "search_results" not in st.session_state:
    st.info(
        "Pick one or more ZIP codes from the auto-detected list in the sidebar, "
        "then click **Search homes**."
    )
    st.stop()

results: list[House] = st.session_state.search_results
source = st.session_state.search_source
search_zips: list[str] = st.session_state.get("search_zips") or []
zip_label = ", ".join(search_zips) if search_zips else "—"

source_names = {
    "rentcast-cache": "Stored ZIP data",
    "rentcast": "RentCast API",
    "mixed": "Stored ZIP data + RentCast API",
}
source_label = source_names.get(source, source)

st.success(
    f"{len(results):,} matching homes out of {st.session_state.raw_house_count:,} usable properties "
    f"across {len(search_zips)} ZIP(s) ({zip_label}) · source: {source_label}"
)
if st.session_state.get("api_limit_notice"):
    st.warning("Your configured monthly RentCast request limit has been reached.")

if st.session_state.get("search_logs"):
    with st.expander("Search activity"):
        st.code("\n".join(st.session_state.search_logs), language=None)

if not results:
    st.info("No homes match those filters. Widen the age or value range and search again.")
    st.stop()

frame = _houses_frame(results).sort_values(["ZIP", "Estimated value", "Address"])
summary_cols = st.columns(4)
summary_cols[0].metric("Matching homes", f"{len(frame):,}")
summary_cols[1].metric("Median value", f"${frame['Estimated value'].median():,.0f}")
summary_cols[2].metric("Median age", f"{frame['Age'].median():,.0f} years")
summary_cols[3].metric("ZIP codes", str(len(search_zips)))

map_frame = frame.rename(columns={"Latitude": "lat", "Longitude": "lon"})
st.map(map_frame[["lat", "lon"]], use_container_width=True, height=420)

display_frame = frame.drop(columns=["Latitude", "Longitude"])
st.subheader("Matching properties")
st.dataframe(
    display_frame,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Estimated value": st.column_config.NumberColumn(format="$%,d"),
        "Age": st.column_config.NumberColumn(format="%d years"),
    },
)

file_tag = "-".join(search_zips[:3]) + ("-more" if len(search_zips) > 3 else "")
st.download_button(
    "Download results as CSV",
    data=display_frame.to_csv(index=False).encode("utf-8"),
    file_name=f"house-finder-{file_tag or 'results'}.csv",
    mime="text/csv",
)

if search_zips:
    captions = []
    for zip_code in search_zips:
        info = get_cached_zip_info(zip_code)
        if info:
            captions.append(f"{zip_code}: {info.summary}")
    if captions:
        st.caption(" · ".join(captions))
