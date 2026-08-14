"""Streamlit deployment entry point for House Finder."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from house_finder.models import House
from house_finder.search import search_houses
from house_finder.zip_cache import get_cached_zip_info, list_cached_zips


ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "aiupscale_logo.png"
CREATOR_URL = "https://aiupscalellc.netlify.app/"
load_dotenv(ROOT / ".env")

st.set_page_config(page_title="House Finder", page_icon="🏠", layout="wide")


def _configured_api_key() -> str:
    """Secrets / environment key (not the sidebar session override)."""
    try:
        secret = str(st.secrets.get("RENTCAST_API_KEY", "")).strip()
        if secret:
            return secret
    except Exception:
        pass
    return os.environ.get("RENTCAST_API_KEY", "").strip()


def _rentcast_key() -> str:
    """Prefer sidebar-entered key, then Streamlit secrets, then environment."""
    typed = str(st.session_state.get("rentcast_api_key_input", "")).strip()
    if typed:
        return typed
    return _configured_api_key()


@st.cache_data(show_spinner=False)
def _cached_zip_options(_signature: str = "") -> list[tuple[str, str]]:
    """Return (zip_code, display_label) from data/cache."""
    options: list[tuple[str, str]] = []
    for info in list_cached_zips():
        if info.location_label:
            label = f"{info.zip_code} — {info.location_label}"
        else:
            label = info.zip_code
        options.append((info.zip_code, label))
    return options


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
    *,
    force_refresh: bool,
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
        force_refresh=force_refresh,
    )
    st.session_state.search_results = houses
    st.session_state.raw_house_count = len(raw_houses)
    st.session_state.search_source = source
    st.session_state.search_zip = zip_code
    st.session_state.search_logs = logs
    st.session_state.api_limit_notice = api_limit_notice


def _clickable_logo_html(path: Path, url: str, *, max_width: int = 220) -> str:
    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        f'<div style="text-align:right;margin-top:0.35rem">'
        f'<a href="{url}" target="_blank" rel="noopener noreferrer" title="AI Upscale">'
        f'<img src="data:image/png;base64,{encoded}" alt="AI Upscale" '
        f'style="max-width:{max_width}px;width:100%;height:auto;" />'
        f"</a></div>"
    )


# ── Header with clickable logo ──────────────────────────────────────────────
header_left, header_right = st.columns([3, 1])
with header_left:
    st.title("🏠 House Finder")
    st.caption("Search houses by ZIP code, age, and estimated value.")
with header_right:
    if LOGO_PATH.is_file():
        st.markdown(_clickable_logo_html(LOGO_PATH, CREATOR_URL), unsafe_allow_html=True)
    else:
        st.markdown(f"[AI Upscale]({CREATOR_URL})")

zip_options = _cached_zip_options(_cache_dir_signature())
zip_by_label = {label: zip_code for zip_code, label in zip_options}
labels = [label for _, label in zip_options]

with st.sidebar:
    st.header("Search")
    if labels:
        selected_label = st.selectbox(
            "ZIP code to search",
            options=labels,
            help="Loaded from data/cache/*.json",
        )
        zip_code = zip_by_label[selected_label]
        info = get_cached_zip_info(zip_code)
        if info and info.location_label:
            st.caption(f"Location: **{info.location_label}**")
    else:
        zip_code = ""
        selected_label = ""
        st.warning("No cached ZIP files found in data/cache.")
        zip_code = st.text_input("ZIP code", max_chars=5).strip()

    age_range = st.slider("House age (years)", min_value=0, max_value=150, value=(20, 40))
    value_range = st.slider(
        "Estimated value ($)",
        min_value=0,
        max_value=2_000_000,
        value=(0, 1_500_000),
        step=25_000,
    )

    st.divider()
    st.subheader("RentCast API key")
    has_configured = bool(_configured_api_key())
    st.text_input(
        "API key",
        type="password",
        key="rentcast_api_key_input",
        placeholder="Paste key here (optional if set in secrets)",
        help="Used for live/refresh searches. Prefer Streamlit secrets for production.",
    )
    if has_configured and not str(st.session_state.get("rentcast_api_key_input", "")).strip():
        st.caption("Using API key from Streamlit secrets / environment.")
    elif _rentcast_key():
        st.caption("API key ready for live searches.")
    else:
        st.caption("Cached ZIP searches work without a key.")

    force_refresh = st.checkbox(
        "Refresh this ZIP from RentCast API",
        value=False,
        help="Requires an API key. Replaces the cached dump for this ZIP on this host.",
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
    elif force_refresh and not _rentcast_key():
        st.error("Enter a RentCast API key (or set RENTCAST_API_KEY in secrets) to refresh.")
    else:
        try:
            with st.spinner(f"Searching ZIP {zip_code}…"):
                _run_search(
                    zip_code,
                    age_range[0],
                    age_range[1],
                    value_range[0],
                    value_range[1],
                    force_refresh=force_refresh,
                )
                # Bust zip-label cache after a refresh so location stays current
                if force_refresh:
                    _cached_zip_options.clear()
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
zip_info = get_cached_zip_info(search_zip)
location = zip_info.location_label if zip_info else ""
source_label = "Stored ZIP data" if source == "rentcast-cache" else "RentCast API"
place = f"{search_zip} ({location})" if location else search_zip

st.success(
    f"{len(results):,} matching homes out of {st.session_state.raw_house_count:,} usable properties "
    f"in {place} · source: {source_label}"
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
summary_cols[3].metric("Location", location or search_zip)

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

if zip_info:
    st.caption(f"Stored data: {zip_info.summary}")

st.markdown(
    f'<p style="text-align:center;font-size:0.8rem;margin-top:1.5rem;">'
    f'Created by <a href="{CREATOR_URL}" target="_blank" rel="noopener noreferrer">'
    f"AI Upscale</a></p>",
    unsafe_allow_html=True,
)
