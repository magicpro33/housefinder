#!/usr/bin/env python3
"""GUI: find homes by zip, age, and estimated value with an interactive map."""

from __future__ import annotations

import math
import queue
import threading
import webbrowser
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from dotenv import load_dotenv

from house_finder.api_usage import (
    format_usage_status,
    get_month_usage,
    mark_limit_notice_shown,
    monthly_limit,
    should_show_limit_notice,
)
from house_finder.export import save_houses_to_file
from house_finder.models import House
from house_finder.search import search_houses
from house_finder.zip_cache import get_cached_zip_info, has_cached_zip, list_cached_zips

AGE_MIN = 20
AGE_MAX = 100

ROOT = Path(__file__).resolve().parent
README_PATH = ROOT / "README.txt"
API_USAGE_PATH = ROOT / "data" / "api_usage.json"
CREATOR_NAME = "AIupscale"
CREATOR_URL = "https://aiupscalellc.netlify.app/"
CREATOR_LOGO_PATH = ROOT / "assets" / "aiupscale_logo.png"
load_dotenv(ROOT / ".env")


def _bind_link_label(label: tk.Label, url: str) -> None:
    label.bind("<Button-1>", lambda _e: webbrowser.open(url))
    label.bind("<Enter>", lambda _e: label.configure(fg="#551A8B"))
    label.bind("<Leave>", lambda _e: label.configure(fg="#0000EE"))


def _bind_clickable_widget(widget: tk.Widget, url: str) -> None:
    widget.configure(cursor="hand2")
    widget.bind("<Button-1>", lambda _e: webbrowser.open(url))


def _load_creator_logo_photo(
    master: tk.Misc, *, max_height: int = 72, max_width: int = 240
) -> tk.PhotoImage | None:
    if not CREATOR_LOGO_PATH.is_file():
        return None
    try:
        from PIL import Image, ImageTk

        img = Image.open(CREATOR_LOGO_PATH)
        w, h = img.size
        scale = min(max_width / w, max_height / h, 1.0)
        if scale < 1.0:
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        return ImageTk.PhotoImage(img, master=master)
    except ImportError:
        pass
    except OSError:
        return None
    try:
        photo = tk.PhotoImage(file=str(CREATOR_LOGO_PATH), master=master)
    except tk.TclError:
        return None
    if photo.height() > max_height:
        factor = max(1, round(photo.height() / max_height))
        photo = photo.subsample(factor, factor)
    return photo


def _add_creator_logo_link(parent: tk.Widget, photo_holder: list[tk.PhotoImage]) -> None:
    """Top-right clickable logo linking to the AIupscale website."""
    tk_master = parent.winfo_toplevel()
    photo = _load_creator_logo_photo(tk_master)
    if photo is not None:
        photo_holder.append(photo)
        logo = tk.Label(parent, image=photo, borderwidth=0, highlightthickness=0)
        logo.pack(anchor=tk.NE)
        _bind_clickable_widget(logo, CREATOR_URL)
        return
    fallback = tk.Label(
        parent,
        text=f"Created by {CREATOR_NAME}",
        fg="#0000EE",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    fallback.pack(anchor=tk.NE)
    _bind_link_label(fallback, CREATOR_URL)


def _add_creator_attribution(parent: tk.Widget, *, anchor: str = "e") -> ttk.Frame:
    """Pack 'Created by AIupscale' with clickable name and URL."""
    frame = ttk.Frame(parent)
    side = tk.RIGHT if anchor in ("e", "east") else tk.LEFT
    frame.pack(side=side, anchor=anchor, fill=tk.X, padx=8, pady=(0, 2))

    ttk.Label(frame, text="Created by ", font=("Segoe UI", 9)).pack(side=tk.LEFT)
    name_link = tk.Label(
        frame,
        text=CREATOR_NAME,
        fg="#0000EE",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    name_link.pack(side=tk.LEFT)
    _bind_link_label(name_link, CREATOR_URL)

    ttk.Label(frame, text=" — ", font=("Segoe UI", 9)).pack(side=tk.LEFT)
    url_link = tk.Label(
        frame,
        text=CREATOR_URL,
        fg="#0000EE",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    url_link.pack(side=tk.LEFT)
    _bind_link_label(url_link, CREATOR_URL)
    return frame

try:
    import tkintermapview
except ImportError as e:
    raise SystemExit(
        "Missing dependency tkintermapview. Run:\n"
        "  .venv\\Scripts\\pip install -r requirements.txt\n"
        f"Original error: {e}"
    ) from e


def _pin_label(house: House) -> str:
    """Text beside map pin (no '$' — safer for Tk canvas)."""
    addr = house.address
    if len(addr) > 30:
        addr = addr[:27] + "..."
    return f"{addr}\n{house.age_years} yr, {house.estimated_value:,}"


def _detail_line(house: House) -> str:
    return house.tooltip_text().replace("\n", "  |  ")


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _nearest_house(
    lat: float, lon: float, houses: list[House], max_miles: float
) -> House | None:
    best: House | None = None
    best_dist = max_miles
    for house in houses:
        dist = _haversine_miles(lat, lon, house.latitude, house.longitude)
        if dist < best_dist:
            best_dist = dist
            best = house
    return best


class HouseFinderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("House Finder — Age & Value Search")
        self.minsize(1100, 720)
        self.geometry("1280x800")

        self._houses: list[House] = []
        self._raw_houses: list[House] = []
        self._markers: list[object] = []
        self._house_by_tree_iid: dict[str, House] = {}
        self._updating_selection = False
        self._map_click_pending = False
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._busy = False
        self._photo_refs: list[tk.PhotoImage] = []
        self._last_source = ""
        self._sort_column: str | None = None
        self._sort_reverse = False
        self._tree_column_titles = {
            "address": "Address",
            "age": "Age (yr)",
            "built": "Year built",
            "value": "Est. value",
        }

        self._build_menu()
        self._build_ui()
        self.after(100, self._drain_log_queue)
        self.after(400, self._check_api_limit_on_startup)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(
            label="Save results to text file…",
            command=self._save_results,
            accelerator="Ctrl+S",
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)

        search_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Search", menu=search_menu)
        search_menu.add_command(label="Run search", command=self._run_search, accelerator="Ctrl+Return")

        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        self._force_refresh_var = tk.BooleanVar(value=False)
        settings_menu.add_checkbutton(
            label="Force refresh from API (ignore cache)",
            variable=self._force_refresh_var,
        )

        about_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="About", menu=about_menu)
        about_menu.add_command(label="User guide (README)", command=self._show_about_readme)
        about_menu.add_command(label="API key setup", command=self._show_help)
        about_menu.add_separator()
        about_menu.add_command(
            label=f"Visit {CREATOR_NAME} website",
            command=lambda: webbrowser.open(CREATOR_URL),
        )

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="API usage this month", command=self._show_api_usage)

        self.bind("<Control-Return>", lambda _e: self._run_search())
        self.bind("<Control-s>", lambda _e: self._save_results())

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        search_frame = ttk.LabelFrame(self, text="Search", padding=8)
        search_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        search_body = ttk.Frame(search_frame)
        search_body.pack(fill=tk.X)

        search_left = ttk.Frame(search_body)
        search_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        logo_slot = ttk.Frame(search_body)
        logo_slot.pack(side=tk.RIGHT, padx=(16, 0), anchor=tk.NE)
        _add_creator_logo_link(logo_slot, self._photo_refs)

        row1 = ttk.Frame(search_left)
        row1.pack(fill=tk.X)

        ttk.Label(row1, text="Zip code:").pack(side=tk.LEFT, padx=(0, 4))
        self._zip_var = tk.StringVar(value="29209")
        ttk.Entry(row1, textvariable=self._zip_var, width=8).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(row1, text="House age (years):").pack(side=tk.LEFT, padx=(0, 4))
        self._age_min_var = tk.IntVar(value=20)
        self._age_max_var = tk.IntVar(value=40)
        ttk.Spinbox(
            row1,
            from_=AGE_MIN,
            to=AGE_MAX,
            textvariable=self._age_min_var,
            width=4,
        ).pack(side=tk.LEFT)
        ttk.Label(row1, text="to").pack(side=tk.LEFT, padx=4)
        ttk.Spinbox(
            row1,
            from_=AGE_MIN,
            to=AGE_MAX,
            textvariable=self._age_max_var,
            width=4,
        ).pack(side=tk.LEFT, padx=(0, 16))

        self._search_btn = ttk.Button(row1, text="Search", command=self._run_search)
        self._search_btn.pack(side=tk.LEFT)

        row_cache = ttk.Frame(search_left)
        row_cache.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(row_cache, text="Cached zip codes:").pack(side=tk.LEFT, padx=(0, 4))
        self._cached_zip_var = tk.StringVar()
        self._cached_zip_combo = ttk.Combobox(
            row_cache,
            textvariable=self._cached_zip_var,
            state="readonly",
            width=12,
        )
        self._cached_zip_combo.pack(side=tk.LEFT, padx=(0, 8))
        self._cached_zip_combo.bind("<<ComboboxSelected>>", self._on_cached_zip_selected)

        self._load_cached_btn = ttk.Button(
            row_cache, text="Load cached", command=self._load_cached_zip
        )
        self._load_cached_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._update_cache_btn = ttk.Button(
            row_cache, text="Update from API", command=self._update_cached_zip
        )
        self._update_cache_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._refresh_cache_btn = ttk.Button(
            row_cache, text="Refresh list", command=self._refresh_cached_zip_list
        )
        self._refresh_cache_btn.pack(side=tk.LEFT)

        self._cache_detail_label = ttk.Label(
            search_left, text="", font=("Segoe UI", 8), foreground="#444444"
        )
        self._cache_detail_label.pack(anchor=tk.W, pady=(2, 0))

        ttk.Label(
            search_left,
            text=f"Shows homes aged {AGE_MIN}–{AGE_MAX} years (select a range above). "
            "Requires RENTCAST_API_KEY in .env — see About → API key setup.",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(6, 0))

        self._api_usage_label = ttk.Label(search_left, text="", font=("Segoe UI", 8))
        self._api_usage_label.pack(anchor=tk.W, pady=(2, 0))

        filter_frame = ttk.LabelFrame(self, text="Filter by estimated value ($)", padding=8)
        filter_frame.pack(fill=tk.X, padx=8, pady=4)

        self._value_min_var = tk.IntVar(value=0)
        self._value_max_var = tk.IntVar(value=1_500_000)
        self._value_max_cap = 2_000_000

        ttk.Label(filter_frame, text="Min:").grid(row=0, column=0, sticky=tk.W)
        self._min_scale = ttk.Scale(
            filter_frame,
            from_=0,
            to=self._value_max_cap,
            variable=self._value_min_var,
            orient=tk.HORIZONTAL,
            command=self._on_value_filter_change,
        )
        self._min_scale.grid(row=0, column=1, sticky=tk.EW, padx=6)
        self._min_label = ttk.Label(filter_frame, text="$0")
        self._min_label.grid(row=0, column=2)

        ttk.Label(filter_frame, text="Max:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self._max_scale = ttk.Scale(
            filter_frame,
            from_=0,
            to=self._value_max_cap,
            variable=self._value_max_var,
            orient=tk.HORIZONTAL,
            command=self._on_value_filter_change,
        )
        self._max_scale.grid(row=1, column=1, sticky=tk.EW, padx=6, pady=(6, 0))
        self._max_label = ttk.Label(filter_frame, text="$1,500,000")
        self._max_label.grid(row=1, column=2, pady=(6, 0))

        filter_frame.columnconfigure(1, weight=1)
        ttk.Button(filter_frame, text="Apply filters", command=self._apply_filters).grid(
            row=0, column=3, rowspan=2, padx=(12, 0)
        )

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        list_frame = ttk.LabelFrame(paned, text="Addresses", padding=4)
        paned.add(list_frame, weight=1)

        cols = ("address", "age", "built", "value")
        self._tree = ttk.Treeview(
            list_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=20,
        )
        for col in cols:
            self._tree.heading(
                col,
                text=self._tree_column_titles[col],
                command=lambda c=col: self._on_tree_heading_click(c),
            )
        self._tree.column("address", width=220, stretch=True)
        self._tree.column("age", width=55, anchor=tk.CENTER)
        self._tree.column("built", width=70, anchor=tk.CENTER)
        self._tree.column("value", width=90, anchor=tk.E)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<<TreeviewSelect>>", self._on_list_select)

        map_outer = ttk.LabelFrame(
            paned, text="Map (click near a pin for details)", padding=4
        )
        paned.add(map_outer, weight=3)

        self._map = tkintermapview.TkinterMapView(map_outer, width=700, height=500, corner_radius=0)
        self._map.pack(fill=tk.BOTH, expand=True)
        self._map.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
        self._map.add_left_click_map_command(self._on_map_click)

        bottom = ttk.Panedwindow(self, orient=tk.VERTICAL)
        bottom.pack(fill=tk.BOTH, expand=False, padx=8, pady=(4, 8))

        detail_frame = ttk.LabelFrame(bottom, text="Selected property", padding=6)
        bottom.add(detail_frame, weight=0)
        self._detail_label = ttk.Label(
            detail_frame,
            text="Run a search, then click near a map pin or select a row in the list.",
            wraplength=1200,
        )
        self._detail_label.pack(anchor=tk.W)

        log_frame = ttk.LabelFrame(bottom, text="Activity", padding=4)
        bottom.add(log_frame, weight=1)
        self._log = tk.Text(log_frame, height=4, font=("Consolas", 9), state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True)

        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        self._status = ttk.Label(footer, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self._status.pack(fill=tk.X, side=tk.LEFT, expand=True)
        _add_creator_attribution(footer, anchor="e")

        self._update_value_labels()
        self._update_api_usage_display()
        self._refresh_cached_zip_list()

    def _refresh_cached_zip_list(self) -> None:
        cached = list_cached_zips()
        zips = [info.zip_code for info in cached]
        self._cached_zip_combo["values"] = zips
        current = self._zip_var.get().strip()
        if current in zips:
            self._cached_zip_var.set(current)
            self._update_cache_detail_label(current)
        elif zips and not self._cached_zip_var.get():
            self._cached_zip_var.set(zips[0])
            self._update_cache_detail_label(zips[0])
        elif not zips:
            self._cached_zip_var.set("")
            self._cache_detail_label.configure(text="No cached zip codes yet — run a search to cache one.")
        self._update_cache_buttons()

    def _update_cache_detail_label(self, zip_code: str) -> None:
        info = get_cached_zip_info(zip_code)
        if info is None:
            self._cache_detail_label.configure(text=f"{zip_code} is not cached on disk.")
            return
        self._cache_detail_label.configure(text=info.summary)

    def _update_cache_buttons(self) -> None:
        zip_code = self._cached_zip_var.get().strip()
        has_cache = bool(zip_code) and has_cached_zip(zip_code)
        self._load_cached_btn.configure(state=tk.NORMAL if has_cache else tk.DISABLED)
        self._update_cache_btn.configure(state=tk.NORMAL if zip_code else tk.DISABLED)

    def _on_cached_zip_selected(self, _event: tk.Event | None = None) -> None:
        zip_code = self._cached_zip_var.get().strip()
        if not zip_code:
            return
        self._zip_var.set(zip_code)
        self._update_cache_detail_label(zip_code)
        self._update_cache_buttons()

    def _load_cached_zip(self) -> None:
        zip_code = self._cached_zip_var.get().strip()
        if not zip_code:
            messagebox.showinfo("Load cached", "Select a cached zip code from the list.")
            return
        if not has_cached_zip(zip_code):
            messagebox.showerror(
                "Load cached",
                f"No cache file found for zip {zip_code}.\n\n"
                "Click Refresh list or run Search to fetch it from the API.",
            )
            self._refresh_cached_zip_list()
            return
        self._zip_var.set(zip_code)
        self._run_search(force_refresh=False)

    def _update_cached_zip(self) -> None:
        zip_code = self._cached_zip_var.get().strip() or self._zip_var.get().strip()
        if len(zip_code) != 5 or not zip_code.isdigit():
            messagebox.showerror("Update from API", "Select or enter a valid 5-digit zip code.")
            return
        self._zip_var.set(zip_code)
        if not messagebox.askyesno(
            "Update from API",
            f"Fetch fresh RentCast data for zip {zip_code}?\n\n"
            "This uses one API request and replaces the local cache file.",
        ):
            return
        self._run_search(force_refresh=True)

    def _update_api_usage_display(self) -> None:
        self._api_usage_label.configure(
            text=format_usage_status(API_USAGE_PATH)
        )

    def _show_api_usage(self) -> None:
        month_key, count = get_month_usage(API_USAGE_PATH)
        messagebox.showinfo(
            "RentCast API usage",
            f"{format_usage_status(API_USAGE_PATH)}\n\n"
            f"Stored in:\n  {API_USAGE_PATH}\n\n"
            "New zip codes call the API once, then reuse data/cache/<zip>.json.\n"
            "Re-searching a cached zip does not use API credits.\n"
            "Force refresh (Settings) fetches again and updates the cache.\n\n"
            "The counter resets automatically when the calendar month changes.\n\n"
            "Optional in .env: RENTCAST_MONTHLY_LIMIT=50 (0 to hide the limit hint).",
        )

    def _source_label(self, source: str) -> str:
        if source == "rentcast-cache":
            return "RentCast (cached)"
        return "RentCast"

    def _show_api_limit_warning(self) -> None:
        limit = monthly_limit()
        _, count = get_month_usage(API_USAGE_PATH)
        messagebox.showwarning(
            "RentCast monthly API limit reached",
            f"You have used {count} of {limit} RentCast API requests this month.\n\n"
            "The free plan includes 50 calls per month; additional requests are "
            "billed on your RentCast account until the counter resets at the start "
            "of the next calendar month.\n\n"
            "Tip: Re-searching a zip you already loaded uses local cache and does "
            "not call the API. Use Settings → Force refresh only when you need "
            "new data from RentCast.",
        )
        mark_limit_notice_shown(API_USAGE_PATH)

    def _check_api_limit_on_startup(self) -> None:
        if should_show_limit_notice(API_USAGE_PATH):
            self._show_api_limit_warning()

    def _handle_api_limit_notify(self, notify: bool) -> None:
        if notify:
            self._show_api_limit_warning()

    def _log_msg(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._log.configure(state=tk.NORMAL)
            self._log.insert(tk.END, msg + "\n")
            self._log.see(tk.END)
            self._log.configure(state=tk.DISABLED)
        self.after(100, self._drain_log_queue)

    def _load_readme_text(self) -> str:
        try:
            return README_PATH.read_text(encoding="utf-8")
        except OSError:
            return (
                "README.txt was not found.\n\n"
                f"Expected location:\n  {README_PATH}\n"
            )

    def _show_about_readme(self) -> None:
        win = tk.Toplevel(self)
        win.title("About House Finder — User Guide")
        win.geometry("920x720")
        win.minsize(640, 480)
        win.transient(self)

        header = ttk.Frame(win, padding=(12, 10, 12, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text="House Finder — Age & Value Search",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)
        _add_creator_attribution(header, anchor="w")

        body = ttk.Frame(win, padding=(12, 4, 12, 8))
        body.pack(fill=tk.BOTH, expand=True)
        text = scrolledtext.ScrolledText(
            body,
            wrap=tk.WORD,
            font=("Consolas", 10),
            padx=6,
            pady=6,
        )
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, self._load_readme_text())
        text.configure(state=tk.DISABLED)

        btn_row = ttk.Frame(win, padding=(12, 0, 12, 12))
        btn_row.pack(fill=tk.X)
        ttk.Button(
            btn_row,
            text=f"Open {CREATOR_NAME} website",
            command=lambda: webbrowser.open(CREATOR_URL),
        ).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Close", command=win.destroy).pack(side=tk.RIGHT)

    def _show_help(self) -> None:
        messagebox.showinfo(
            "RentCast API key",
            "Live property data uses the RentCast API (50 free calls/month).\n\n"
            "1. Sign up at https://app.rentcast.io/app/api\n"
            "2. Add to .env:  RENTCAST_API_KEY=your_key_here\n"
            "3. Restart the app and run a search\n\n"
            "For the full user guide, open About → User guide (README).",
        )

    def _default_export_path(self) -> Path:
        zip_code = self._zip_var.get().strip() or "results"
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        return ROOT / "exports" / f"houses_{zip_code}_{stamp}.txt"

    def _save_results(self) -> None:
        if not self._houses:
            messagebox.showinfo(
                "Save results",
                "No houses to save. Run a search first.",
            )
            return
        default_path = self._default_export_path()
        path = filedialog.asksaveasfilename(
            title="Save house list",
            defaultextension=".txt",
            initialdir=str(default_path.parent),
            initialfile=default_path.name,
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            save_houses_to_file(
                Path(path),
                self._houses,
                zip_code=self._zip_var.get().strip(),
                source=self._source_label(self._last_source),
            )
        except OSError as e:
            messagebox.showerror("Save failed", str(e))
            return
        self._log_msg(f"Saved {len(self._houses)} homes to {path}")
        messagebox.showinfo("Save results", f"Saved {len(self._houses)} homes to:\n{path}")

    def _age_bounds(self) -> tuple[int, int]:
        min_age = int(self._age_min_var.get())
        max_age = int(self._age_max_var.get())
        min_age = max(AGE_MIN, min(AGE_MAX, min_age))
        max_age = max(AGE_MIN, min(AGE_MAX, max_age))
        if min_age > max_age:
            min_age, max_age = max_age, min_age
            self._age_min_var.set(min_age)
            self._age_max_var.set(max_age)
        return min_age, max_age

    def _value_bounds(self) -> tuple[int | None, int | None]:
        vmin = int(self._value_min_var.get())
        vmax = int(self._value_max_var.get())
        if vmin > vmax:
            vmin, vmax = vmax, vmin
        min_v = vmin if vmin > 0 else None
        max_v = vmax if vmax < self._value_max_cap else None
        return min_v, max_v

    def _update_value_labels(self) -> None:
        vmin, vmax = self._value_bounds()
        self._min_label.configure(text=f"${vmin or 0:,}")
        self._max_label.configure(text=f"${vmax or self._value_max_cap:,}")

    def _on_value_filter_change(self, _value: str = "") -> None:
        self._update_value_labels()

    def _apply_filters(self) -> None:
        if not self._raw_houses:
            messagebox.showinfo("Filter", "Run a search first.")
            return
        self._refresh_display(self._raw_houses)

    def _run_search(self, *, force_refresh: bool | None = None) -> None:
        if self._busy:
            return
        zip_code = self._zip_var.get().strip()
        if len(zip_code) != 5 or not zip_code.isdigit():
            messagebox.showerror("Zip code", "Enter a valid 5-digit US zip code.")
            return

        if force_refresh is None:
            force_refresh = self._force_refresh_var.get()

        self._busy = True
        self._search_btn.configure(state=tk.DISABLED)
        self._load_cached_btn.configure(state=tk.DISABLED)
        self._update_cache_btn.configure(state=tk.DISABLED)
        self._status.configure(text="Searching…")
        mode = "API refresh" if force_refresh else "search"
        self._log_msg(f"--- {mode.capitalize()} zip {zip_code} ---")

        def worker() -> None:
            try:
                min_age, max_age = self._age_bounds()
                min_v, max_v = self._value_bounds()
                houses, source, raw, limit_notify = search_houses(
                    zip_code,
                    min_age,
                    max_age,
                    min_v,
                    max_v,
                    log=self._log_msg,
                    force_refresh=force_refresh,
                )
                self.after(
                    0,
                    lambda h=houses, r=raw, s=source, n=limit_notify: self._on_search_done(
                        h, r, s, None, n
                    ),
                )
            except Exception as e:
                self.after(0, lambda err=e: self._on_search_done([], [], "", err, False))

        threading.Thread(target=worker, daemon=True).start()

    def _on_search_done(
        self,
        houses: list[House],
        raw: list[House],
        source: str,
        error: Exception | None,
        api_limit_notify: bool = False,
    ) -> None:
        self._busy = False
        self._search_btn.configure(state=tk.NORMAL)
        self._update_cache_buttons()
        if error:
            self._status.configure(text="Search failed")
            messagebox.showerror("Search failed", str(error))
            return
        self._raw_houses = raw
        self._houses = houses
        self._last_source = source
        self._sync_map_and_list(houses)
        label = self._source_label(source)
        self._update_api_usage_display()
        self._handle_api_limit_notify(api_limit_notify)
        month_key, count = get_month_usage(API_USAGE_PATH)
        status = f"{len(houses)} homes — source: {label} | API requests this month: {count}"
        self._log_msg(f"RentCast API requests this month ({month_key}): {count}")
        self._status.configure(text=status)
        self._log_msg(f"Showing {len(houses)} homes on map and list.")
        if self._force_refresh_var.get():
            self._force_refresh_var.set(False)
        self._refresh_cached_zip_list()
        if zip_code := self._zip_var.get().strip():
            self._cached_zip_var.set(zip_code)
            self._update_cache_detail_label(zip_code)

    def _refresh_display(self, raw_houses: list[House]) -> None:
        min_age, max_age = self._age_bounds()
        min_v, max_v = self._value_bounds()
        from house_finder.filters import filter_houses

        filtered = filter_houses(raw_houses, min_age, max_age, min_v, max_v)
        self._houses = filtered
        self._sync_map_and_list(filtered)
        if not filtered:
            self._detail_label.configure(
                text="No homes match the current age and value filters."
            )
        self._status.configure(text=f"{len(filtered)} homes shown")
        self._log_msg(
            f"Showing {len(filtered)} homes on map and list "
            f"(of {len(raw_houses)} loaded for this zip)."
        )

    def _house_sort_key(self, house: House, column: str):
        if column == "address":
            return house.full_address.lower()
        if column == "age":
            return house.age_years
        if column == "built":
            return house.year_built
        if column == "value":
            return house.estimated_value
        return 0

    def _houses_for_display(self, houses: list[House]) -> list[House]:
        if not self._sort_column:
            return houses
        return sorted(
            houses,
            key=lambda h: self._house_sort_key(h, self._sort_column),
            reverse=self._sort_reverse,
        )

    def _update_tree_headings(self) -> None:
        for col, title in self._tree_column_titles.items():
            if col == self._sort_column:
                arrow = " ▼" if self._sort_reverse else " ▲"
                text = f"{title}{arrow}"
            else:
                text = title
            self._tree.heading(col, text=text, command=lambda c=col: self._on_tree_heading_click(c))

    def _on_tree_heading_click(self, column: str) -> None:
        if not self._houses:
            return
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self._update_tree_headings()
        selected = self._selected_house()
        self._populate_list(self._houses)
        if selected is not None:
            self._highlight_in_list(selected)

    def _selected_house(self) -> House | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return self._house_by_tree_iid.get(sel[0])

    def _populate_list(self, houses: list[House]) -> None:
        houses = self._houses_for_display(houses)
        self._tree.delete(*self._tree.get_children())
        self._house_by_tree_iid.clear()
        for index, h in enumerate(houses):
            tree_iid = f"row-{index}"
            self._house_by_tree_iid[tree_iid] = h
            self._tree.insert(
                "",
                tk.END,
                iid=tree_iid,
                values=(
                    h.full_address,
                    h.age_years,
                    h.year_built,
                    f"${h.estimated_value:,}",
                ),
            )

    def _show_details(self, house: House) -> None:
        self._detail_label.configure(text=_detail_line(house))

    def _clear_map(self) -> None:
        self._map.delete_all_marker()
        self._markers.clear()

    def _on_map_click(self, coords: tuple[float, float]) -> None:
        """Select the nearest home to a map click (single event, no pin command hooks)."""
        if self._map_click_pending or not self._houses:
            return
        self._map_click_pending = True

        def finish() -> None:
            self._map_click_pending = False
            if not coords:
                return
            lat, lon = coords
            house = _nearest_house(lat, lon, self._houses, max_miles=0.2)
            if house is None:
                self._log_msg("Click was not close enough to a pin.")
                return
            self._show_details(house)
            self._highlight_in_list(house)
            self._log_msg(f"Selected: {house.full_address}")

        self.after_idle(finish)

    def _highlight_in_list(self, house: House) -> None:
        tree_iid = self._tree_iid_for_house(house)
        if not tree_iid or not self._tree.exists(tree_iid):
            return
        self._updating_selection = True
        try:
            self._tree.selection_set(tree_iid)
            self._tree.see(tree_iid)
        finally:
            self._updating_selection = False

    def _sync_map_and_list(self, houses: list[House]) -> None:
        """Keep list and map in sync — always clear pins when count is zero."""
        self._populate_list(houses)
        self._clear_map()
        if not houses:
            return
        lats = [h.latitude for h in houses]
        lons = [h.longitude for h in houses]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)
        self._map.set_position(center_lat, center_lon)
        self._map.set_zoom(13)
        for h in houses:
            marker = self._map.set_marker(
                h.latitude,
                h.longitude,
                text=_pin_label(h),
            )
            self._markers.append(marker)

    def _tree_iid_for_house(self, house: House) -> str | None:
        for tree_iid, h in self._house_by_tree_iid.items():
            if h is house:
                return tree_iid
        return None

    def _on_list_select(self, _event: tk.Event | None = None) -> None:
        if self._updating_selection:
            return
        sel = self._tree.selection()
        if not sel:
            return
        house = self._house_by_tree_iid.get(sel[0])
        if house is not None:
            self._show_details(house)


def main() -> int:
    app = HouseFinderApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
