"""Streamlit deployment entry point for House Finder."""

from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

import folium
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium

from house_finder.models import House
from house_finder.search import search_houses
from house_finder.zip_cache import get_cached_zip_info, list_cached_zips


ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "aiupscale_logo.png"
CREATOR_URL = "https://aiupscalellc.netlify.app/"
load_dotenv(ROOT / ".env")

st.set_page_config(page_title="House Finder", page_icon="🏠", layout="wide")


def _zillow_url(address: str, city: str = "", state: str = "", zip_code: str = "") -> str:
    """Build a Zillow homes search URL for a street address."""
    full = ", ".join(
        part for part in (
            str(address or "").strip(),
            str(city or "").strip(),
            f"{str(state or '').strip()} {str(zip_code or '').strip()}".strip(),
        ) if part
    )
    return f"https://www.zillow.com/homes/{quote(full)}_rb/"


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


def _street_label(address: str) -> str:
    """Short street text for map markers."""
    text = str(address or "").strip()
    # Prefer the street line before the city when formattedAddress is used.
    if "," in text:
        text = text.split(",", 1)[0].strip()
    if len(text) > 36:
        text = text[:33] + "…"
    return text or "Home"


def _houses_frame(houses: list[House]) -> pd.DataFrame:
    rows = []
    for house in houses:
        rows.append(
            {
                "Address": house.address,
                "Zillow": _zillow_url(
                    house.address, house.city, house.state, house.zip_code
                ),
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
    st.session_state.search_fingerprint = (
        zip_code,
        min_age,
        max_age,
        min_value,
        max_value,
    )


def _build_folium_map(houses: list[House]) -> folium.Map:
    """Map with large permanent street-name labels on each pin."""
    lats = [h.latitude for h in houses]
    lons = [h.longitude for h in houses]
    center = [sum(lats) / len(lats), sum(lons) / len(lons)]
    fmap = folium.Map(location=center, zoom_start=13, tiles="OpenStreetMap")

    # Slightly higher default zoom so basemap street names render larger.
    if len(houses) == 1:
        fmap = folium.Map(location=center, zoom_start=16, tiles="OpenStreetMap")

    for house in houses:
        label = _street_label(house.address)
        tip_html = (
            f'<div style="font-size:14px;font-weight:700;line-height:1.2;">'
            f"{html.escape(label)}</div>"
            f'<div style="font-size:12px;">${house.estimated_value:,} · {house.age_years} yr</div>'
        )
        popup_html = (
            f"<b>{html.escape(house.address)}</b><br>"
            f"{html.escape(house.city)}, {html.escape(house.state)} {html.escape(house.zip_code)}<br>"
            f"Est. value: ${house.estimated_value:,}<br>"
            f"Built: {house.year_built} ({house.age_years} years)<br>"
            f'<a href="{html.escape(_zillow_url(house.address, house.city, house.state, house.zip_code), quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Open on Zillow</a>'
        )
        folium.Marker(
            location=[house.latitude, house.longitude],
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=folium.Tooltip(tip_html, permanent=True, sticky=False),
            icon=folium.Icon(color="orange", icon="home", prefix="fa"),
        ).add_to(fmap)

    # Fit bounds with padding so labels stay readable
    if len(houses) > 1:
        fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(30, 30))

    # CSS bump for Folium permanent tooltips (street names on map)
    fmap.get_root().html.add_child(
        folium.Element(
            """
            <style>
            .leaflet-tooltip {
              font-size: 14px !important;
              font-weight: 700 !important;
              padding: 6px 8px !important;
              border-radius: 6px !important;
              box-shadow: 0 2px 8px rgba(0,0,0,.25) !important;
              opacity: 0.95 !important;
            }
            </style>
            """
        )
    )
    return fmap


def _render_html(markup: str) -> None:
    """Render raw HTML.

    Markdown treats indented lines as code blocks, and pandas to_html emits
    indented markup, so collapse everything to a single line first.
    """
    collapsed = "".join(line.strip() for line in markup.splitlines())
    render = getattr(st, "html", None)
    if callable(render):
        render(collapsed)
    else:
        st.markdown(collapsed, unsafe_allow_html=True)


def _fetch_zip_from_api(zip_code: str) -> tuple[bool, str]:
    """Pull a ZIP from RentCast and write it to the local cache."""
    from house_finder.rentcast import fetch_properties_by_zip

    key = _rentcast_key()
    if not key:
        return False, "Enter a RentCast API key first."
    if len(zip_code) != 5 or not zip_code.isdigit():
        return False, "Enter a valid 5-digit ZIP code."
    houses, _from_cache, api_limit_notify = fetch_properties_by_zip(
        zip_code, key, log=None, force_refresh=True
    )
    st.session_state.api_limit_notice = api_limit_notify
    if not houses:
        return False, f"RentCast returned no usable properties for {zip_code}."
    return True, f"Fetched {len(houses)} homes for {zip_code}."


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
        if st.session_state.get("zip_select") not in labels:
            st.session_state.zip_select = labels[0]
        selected_label = st.selectbox(
            "ZIP code to search",
            options=labels,
            key="zip_select",
            help="Loads automatically when you change ZIP or filters.",
        )
        zip_code = zip_by_label[selected_label]
        info = get_cached_zip_info(zip_code)
        if info and info.location_label:
            st.caption(f"Location: **{info.location_label}**")
    else:
        zip_code = ""
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

    st.divider()
    st.subheader("Search a ZIP with your API key")
    api_zip = st.text_input(
        "ZIP code to fetch",
        max_chars=5,
        key="api_zip_input",
        placeholder="e.g. 29212",
        help="Downloads this ZIP from RentCast and adds it to the ZIP list above.",
    ).strip()
    fetch_clicked = st.button(
        "Fetch from RentCast",
        use_container_width=True,
        disabled=not bool(api_zip),
    )
    st.caption("Uses one API request per ZIP. Cached ZIPs above are free.")

if fetch_clicked:
    try:
        with st.spinner(f"Fetching ZIP {api_zip} from RentCast…"):
            ok, message = _fetch_zip_from_api(api_zip)
    except ValueError as exc:
        ok, message = False, str(exc)
    except Exception as exc:  # network/API failures
        ok, message = False, f"RentCast request failed: {exc}"

    if ok:
        _cached_zip_options.clear()
        st.session_state.pop("search_fingerprint", None)
        info = get_cached_zip_info(api_zip)
        if info:
            st.session_state.zip_select = (
                f"{info.zip_code} — {info.location_label}"
                if info.location_label
                else info.zip_code
            )
        st.session_state.fetch_notice = message
        st.rerun()
    else:
        st.error(message)

fetch_notice = st.session_state.pop("fetch_notice", "")
if fetch_notice:
    st.success(fetch_notice)

# Auto-load whenever ZIP or filters change (no Search button).
fingerprint = (
    zip_code,
    age_range[0],
    age_range[1],
    value_range[0],
    value_range[1],
)
needs_load = bool(zip_code) and st.session_state.get("search_fingerprint") != fingerprint

if needs_load:
    try:
        with st.spinner(f"Loading ZIP {zip_code}…"):
            _run_search(
                zip_code,
                age_range[0],
                age_range[1],
                value_range[0],
                value_range[1],
                force_refresh=False,
            )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.exception(exc)
        st.stop()

if "search_results" not in st.session_state:
    st.info("Choose a ZIP code in the sidebar — results load automatically.")
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
    st.info("No homes match those filters. Widen the age or value range.")
    st.stop()

frame = _houses_frame(results).sort_values(["Estimated value", "Address"])
summary_cols = st.columns(4)
summary_cols[0].metric("Matching homes", f"{len(frame):,}")
summary_cols[1].metric("Median value", f"${frame['Estimated value'].median():,.0f}")
summary_cols[2].metric("Median age", f"{frame['Age'].median():,.0f} years")
summary_cols[3].metric("Location", location or search_zip)

st.subheader("Map")
st.caption("Street names are shown as large labels on each pin. Zoom in for larger basemap names.")
st_folium(_build_folium_map(results), width=None, height=480, returned_objects=[])

display_frame = frame.drop(columns=["Latitude", "Longitude"])
link_frame = display_frame.drop(columns=["Zillow"]).copy()
link_frame["Address"] = [
    f'<a href="{html.escape(str(url), quote=True)}" target="_blank" '
    f'rel="noopener noreferrer" style="color:#4da3ff;text-decoration:underline;">'
    f"{html.escape(str(addr))}</a>"
    for addr, url in zip(display_frame["Address"], display_frame["Zillow"])
]
link_frame["Estimated value"] = link_frame["Estimated value"].map(
    lambda v: f"${int(v):,}" if pd.notna(v) else "—"
)

st.subheader("Matching properties")
st.caption("Click an address to open that home on Zillow.")
table_html = link_frame.to_html(
    escape=False, index=False, border=0, classes="house-table"
)
_render_html(
    "<style>"
    ".house-table{width:100%;border-collapse:collapse;font-size:0.9rem;}"
    ".house-table th{position:sticky;top:0;background:#0c1829;color:#F6F4E9;"
    "text-align:left;padding:8px;border-bottom:1px solid #334;white-space:nowrap;}"
    ".house-table td{padding:8px;border-bottom:1px solid #1c2a3f;color:#F6F4E9;}"
    ".house-table tr:hover td{background:#122038;}"
    ".house-scroll{max-height:520px;overflow:auto;border:1px solid #233;border-radius:8px;}"
    "</style>"
    f'<div class="house-scroll">{table_html}</div>'
)

csv_frame = display_frame.drop(columns=["Zillow"])
st.download_button(
    "Download results as CSV",
    data=csv_frame.to_csv(index=False).encode("utf-8"),
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
