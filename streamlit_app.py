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
def _cached_zip_codes(_signature: str = "") -> list[str]:
    return [info.zip_code for info in list_cached_zips()]


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


def _run_search(
    zip_code: str,
    min_age: int,
    max_age: int,
    min_value: int,
    max_value: int,
) -> None:
    logs: list[str] = []
    houses, source, raw_houses, api_limit_notice = search_houses(
        zip_code,
        min_age,
        max_age,
        min_value or None,
        max_value or None,
        api_key=_rentcast_key(),
        log=logs.append,
        force_refresh=False,
    )
    st.session_state.search_results = houses
    st.session_state.raw_house_count = len(raw_houses)
    st.session_state.search_source = source
    st.session_state.search_zip = zip_code
    st.session_state.search_logs = logs
    st.session_state.api_limit_notice = api_limit_notice


st.title("🏠 House Finder")
st.caption("Search houses by ZIP code, age, and estimated value using cached ZIP data.")

available_zips = _cached_zip_codes(_cache_dir_signature())

with st.sidebar:
    st.header("Search")
    if available_zips:
        zip_code = st.selectbox(
            "ZIP code to search",
            options=available_zips,
            help="Loaded from data/cache/*.json",
        )
    else:
        zip_code = ""
        st.warning("No cached ZIP files found in data/cache.")

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
        disabled=not bool(zip_code),
    )

if submitted:
    if not zip_code:
        st.error("Select a ZIP code to search.")
    else:
        try:
            with st.spinner(f"Searching ZIP {zip_code}…"):
                _run_search(
                    zip_code,
                    age_range[0],
                    age_range[1],
                    value_range[0],
                    value_range[1],
                )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            st.exception(exc)

if "search_results" not in st.session_state:
    st.info("Choose a ZIP code in the sidebar, then click **Search homes**.")
    st.stop()

results: list[House] = st.session_state.search_results
source = st.session_state.search_source
search_zip = st.session_state.search_zip
source_label = "Stored ZIP data" if source == "rentcast-cache" else "RentCast API"

st.success(
    f"{len(results):,} matching homes out of {st.session_state.raw_house_count:,} usable properties "
    f"in {search_zip} · source: {source_label}"
)
if st.session_state.get("api_limit_notice"):
    st.warning("Your configured monthly RentCast request limit has been reached.")

if st.session_state.get("search_logs"):
    with st.expander("Search activity"):
        st.code("\n".join(st.session_state.search_logs), language=None)

if not results:
    st.info("No homes match those filters. Widen the age or value range and search again.")
    st.stop()

frame = _houses_frame(results).sort_values(["Estimated value", "Address"])
summary_cols = st.columns(4)
summary_cols[0].metric("Matching homes", f"{len(frame):,}")
summary_cols[1].metric("Median value", f"${frame['Estimated value'].median():,.0f}")
summary_cols[2].metric("Median age", f"{frame['Age'].median():,.0f} years")
summary_cols[3].metric("ZIP code", search_zip)

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

st.download_button(
    "Download results as CSV",
    data=display_frame.to_csv(index=False).encode("utf-8"),
    file_name=f"house-finder-{search_zip}.csv",
    mime="text/csv",
)

info = get_cached_zip_info(search_zip)
if info:
    st.caption(f"Stored data: {info.summary}")
