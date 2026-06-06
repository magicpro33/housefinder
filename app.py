"""House Finder — Streamlit web app."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from house_finder.api_usage import (
    format_usage_status,
    get_month_usage,
    mark_limit_notice_shown,
    monthly_limit,
    should_show_limit_notice,
)
from house_finder.export import format_houses_report
from house_finder.filters import filter_houses
from house_finder.models import House
from house_finder.search import search_houses

AGE_MIN = 20
AGE_MAX = 100
VALUE_MAX_CAP = 2_000_000
ROOT = Path(__file__).resolve().parent
CREATOR_NAME = "AIupscale"
CREATOR_URL = "https://aiupscalellc.netlify.app/"
LOGO_PATH = ROOT / "assets" / "aiupscale_logo.png"

load_dotenv(ROOT / ".env")


def _apply_streamlit_secrets() -> None:
    """Load RentCast settings from Streamlit Cloud secrets (or local secrets.toml)."""
    try:
        secrets = st.secrets
        if secrets.get("RENTCAST_API_KEY"):
            os.environ["RENTCAST_API_KEY"] = str(secrets["RENTCAST_API_KEY"])
        if secrets.get("RENTCAST_MONTHLY_LIMIT"):
            os.environ["RENTCAST_MONTHLY_LIMIT"] = str(secrets["RENTCAST_MONTHLY_LIMIT"])
    except (FileNotFoundError, KeyError, RuntimeError):
        pass


st.set_page_config(
    page_title="House Finder",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _source_label(source: str) -> str:
    if source == "rentcast-cache":
        return "RentCast (cached)"
    return "RentCast"


def _houses_to_dataframe(houses: list[House]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Address": h.full_address,
                "Age (yr)": h.age_years,
                "Year built": h.year_built,
                "Est. value": f"${h.estimated_value:,}",
                "Latitude": h.latitude,
                "Longitude": h.longitude,
            }
            for h in houses
        ]
    )


def _build_map(houses: list[House]) -> folium.Map | None:
    if not houses:
        return None
    center_lat = sum(h.latitude for h in houses) / len(houses)
    center_lon = sum(h.longitude for h in houses) / len(houses)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=13, tiles="OpenStreetMap")
    for house in houses:
        popup_html = (
            f"<b>{house.full_address}</b><br>"
            f"Built: {house.year_built} ({house.age_years} yr)<br>"
            f"Est. value: ${house.estimated_value:,}"
        )
        folium.Marker(
            location=[house.latitude, house.longitude],
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=house.address,
        ).add_to(fmap)
    return fmap


def _init_session_state() -> None:
    defaults = {
        "raw_houses": [],
        "houses": [],
        "source": "",
        "zip_code": "29209",
        "search_logs": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _header() -> None:
    col_logo, col_title = st.columns([1, 3])
    with col_logo:
        if LOGO_PATH.is_file():
            st.image(str(LOGO_PATH), width=200)
        st.markdown(f"[{CREATOR_NAME}]({CREATOR_URL})")
    with col_title:
        st.title("House Finder — Age & Value Search")
        st.caption(
            f"Search US zip codes by house age and estimated value. "
            f"Created by [{CREATOR_NAME}]({CREATOR_URL})."
        )


def _sidebar() -> bool:
    st.sidebar.header("Settings")
    force_refresh = st.sidebar.checkbox(
        "Force refresh from API (ignore cache)",
        value=False,
        help="Next search re-downloads data for that zip and uses API credits.",
    )
    st.sidebar.divider()
    st.sidebar.subheader("API usage")
    st.sidebar.caption(format_usage_status())
    st.sidebar.markdown(
        "Get a free key at [RentCast](https://app.rentcast.io/app/api) "
        "and add `RENTCAST_API_KEY` to `.env` in this folder."
    )
    st.sidebar.divider()
    st.sidebar.subheader("About")
    st.sidebar.markdown(f"- [User guide]({CREATOR_URL})")
    st.sidebar.markdown(f"- Website: [{CREATOR_URL}]({CREATOR_URL})")
    with st.sidebar.expander("API key setup"):
        st.markdown(
            "1. Sign up at https://app.rentcast.io/app/api\n"
            "2. Create `.env` in the project folder\n"
            "3. Add: `RENTCAST_API_KEY=your_key_here`\n"
            "4. Restart this app"
        )
    return force_refresh


def main() -> None:
    _apply_streamlit_secrets()
    _init_session_state()
    _header()
    force_refresh = _sidebar()

    st.subheader("Search")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    with c1:
        zip_code = st.text_input("Zip code", value=st.session_state.zip_code, max_chars=5)
    with c2:
        min_age = st.number_input("Min age (years)", min_value=AGE_MIN, max_value=AGE_MAX, value=20)
    with c3:
        max_age = st.number_input("Max age (years)", min_value=AGE_MIN, max_value=AGE_MAX, value=40)
    with c4:
        st.write("")
        st.write("")
        run_search = st.button("Search", type="primary", use_container_width=True)

    st.caption(f"Shows homes aged {AGE_MIN}–{AGE_MAX} years. Requires RentCast API key in `.env`.")
    st.caption(format_usage_status())

    v1, v2 = st.columns(2)
    with v1:
        min_value = st.slider("Min estimated value ($)", 0, VALUE_MAX_CAP, 0, step=10_000)
    with v2:
        max_value = st.slider(
            "Max estimated value ($)", 0, VALUE_MAX_CAP, 1_500_000, step=10_000
        )
    min_v = min_value if min_value > 0 else None
    max_v = max_value if max_value < VALUE_MAX_CAP else None

    if run_search:
        zip_code = zip_code.strip()
        if len(zip_code) != 5 or not zip_code.isdigit():
            st.error("Enter a valid 5-digit US zip code.")
        else:
            logs: list[str] = [f"--- Search zip {zip_code} ---"]
            with st.spinner("Searching…"):
                try:
                    filtered, source, raw, limit_notify = search_houses(
                        zip_code,
                        int(min_age),
                        int(max_age),
                        min_v,
                        max_v,
                        log=logs.append,
                        force_refresh=force_refresh,
                    )
                    st.session_state.raw_houses = raw
                    st.session_state.houses = filtered
                    st.session_state.source = source
                    st.session_state.zip_code = zip_code
                    st.session_state.search_logs = logs
                except Exception as e:
                    st.error(str(e))
                    st.session_state.search_logs = logs + [f"Error: {e}"]

    elif st.session_state.raw_houses:
        filtered = filter_houses(
            st.session_state.raw_houses,
            int(min_age),
            int(max_age),
            min_v,
            max_v,
        )
        st.session_state.houses = filtered

    if should_show_limit_notice():
        st.warning(
            f"You have used {get_month_usage()[1]} of {monthly_limit()} RentCast API requests "
            "this month. Additional requests may be billed until the counter resets next month. "
            "Re-searching a cached zip does not use API credits."
        )
        mark_limit_notice_shown()

    houses: list[House] = st.session_state.houses
    if not houses and not st.session_state.search_logs:
        st.info("Enter a zip code and click **Search** to load properties.")
        return

    if st.session_state.search_logs:
        with st.expander("Activity log", expanded=False):
            st.code("\n".join(st.session_state.search_logs))

    if not houses:
        st.warning("No homes match the current filters. Widen age or value range and try again.")
        return

    source_label = _source_label(st.session_state.source)
    st.success(f"Showing **{len(houses)}** homes — source: **{source_label}**")

    tab_list, tab_map = st.tabs(["Address list", "Map"])

    with tab_list:
        st.dataframe(_houses_to_dataframe(houses), use_container_width=True, hide_index=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"houses_{st.session_state.zip_code}_{stamp}.txt"
        report = format_houses_report(
            houses,
            zip_code=st.session_state.zip_code,
            source=source_label,
        )
        st.download_button(
            label="Download results as text file",
            data=report,
            file_name=filename,
            mime="text/plain",
            type="secondary",
        )

    with tab_map:
        fmap = _build_map(houses)
        if fmap is not None:
            st_folium(fmap, width=None, height=500, returned_objects=[])


if __name__ == "__main__":
    main()
