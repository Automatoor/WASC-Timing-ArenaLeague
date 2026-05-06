"""
ArenaLink v1.0.3
Winsford Swim Team — Arena League timing data capture
"""
import tkinter as tk
from tkinter import messagebox, filedialog
import json
import os
import sys
import re
import time
import threading
import logging
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
import pyperclip
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

VERSION = "v1.0.3"
APP_NAME = "ArenaLink"

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE    = BASE_DIR / "logs" / "processed.log"
APP_LOG     = BASE_DIR / "logs" / "app.log"
LOGO_PATH   = BASE_DIR / "assets" / "logo.png"
ICO_PATH    = BASE_DIR / "assets" / "arenalink.ico"

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(filename=APP_LOG, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# ── Theme — Orange on Black ────────────────────────────────────────────────────
BG_BLACK   = "#0a0a0a"       # near-black base
BG_DARK    = "#111111"       # panel backgrounds
BG_MID     = "#1a1208"       # warm dark for header
BG_PANEL   = "#1c1c1c"       # status bar etc
ORANGE     = "#ff6600"       # primary — Winsford orange
ORANGE_DIM = "#994000"       # dimmed orange for inactive
ORANGE_LT  = "#ff9944"       # light orange for secondary text
WHITE      = "#ffffff"
WHITE_DIM  = "#aaaaaa"
WARN_BG    = "#2a0d00"       # deep red-orange for warnings
WARN_FG    = "#ff6600"
WARN_DET   = "#cc5500"
INFO_BG    = "#1e1a00"       # yellow-tinted for backup notice (non-blocking)
INFO_FG    = "#ccaa00"
INFO_DET   = "#997700"
DIM        = "#333333"
GREEN      = "#44cc66"
MONO       = "Courier New"

# ── Config ─────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {"watch_folder": "", "sound_alerts": True, "team": "A", "excel_path": "", "excel_autofill": True}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Processed log ──────────────────────────────────────────────────────────────
# Log format per line: timestamp|gen_filename|html_filename|status
# status = 'processed' or 'confirmed'

def _parse_log_line(line):
    """Parse a log line returning dict or None. Handles old single-field format."""
    line = line.strip()
    if not line:
        return None
    parts = line.split("|")
    if len(parts) == 4:
        return {"ts": parts[0], "gen": parts[1], "html": parts[2], "status": parts[3]}
    # Legacy single-field line (just gen filename)
    return {"ts": "", "gen": parts[0], "html": "", "status": "processed"}

def load_processed():
    """Return set of processed gen filenames."""
    if not LOG_FILE.exists():
        return set()
    result = set()
    with open(LOG_FILE) as f:
        for line in f:
            entry = _parse_log_line(line)
            if entry:
                result.add(entry["gen"])
    return result

def load_log_entries():
    """Return list of all log entry dicts, newest first."""
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE) as f:
        for line in f:
            entry = _parse_log_line(line)
            if entry:
                entries.append(entry)
    return list(reversed(entries))

def count_confirmed():
    """Count lines with status=confirmed."""
    if not LOG_FILE.exists():
        return 0
    count = 0
    with open(LOG_FILE) as f:
        for line in f:
            entry = _parse_log_line(line)
            if entry and entry["status"] == "confirmed":
                count += 1
    return count

def mark_processed(gen_filename, html_filename=""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{ts}|{gen_filename}|{html_filename}|processed\n")

def mark_confirmed(gen_filename):
    """Update the last matching processed entry to confirmed."""
    if not LOG_FILE.exists():
        return
    with open(LOG_FILE) as f:
        lines = f.readlines()
    updated = False
    new_lines = []
    for line in reversed(lines):
        entry = _parse_log_line(line)
        if not updated and entry and entry["gen"] == gen_filename and entry["status"] == "processed":
            new_lines.append(line.rstrip().replace("|processed", "|confirmed") + "\n")
            updated = True
        else:
            new_lines.append(line)
    with open(LOG_FILE, "w") as f:
        f.writelines(reversed(new_lines))

# ── Parsing ────────────────────────────────────────────────────────────────────
def decimal_seconds_to_formatted(val):
    """162.16 → '024216' (MMSSHH, always 6 chars)"""
    try:
        total = float(val)
        if total <= 0:
            return ""
        mins       = int(total // 60)
        remaining  = total - mins * 60
        secs       = int(remaining)
        hundredths = round((remaining - secs) * 100)
        return f"{mins:02d}{secs:02d}{hundredths:02d}"
    except Exception:
        return ""

def formatted_to_display(t):
    """'024216' → '2:42.16', '005516' → '55.16'"""
    if len(t) == 6:
        mins = int(t[:2])
        secs_hunds = f"{t[2:4]}.{t[4:]}"
        if mins == 0:
            return secs_hunds        # e.g. '55.16'
        return f"{mins}:{secs_hunds}"  # e.g. '2:42.16'
    return "--"

def ordinal(n):
    """1 → '1st', 2 → '2nd' etc."""
    if n == 1: return "1st"
    if n == 2: return "2nd"
    if n == 3: return "3rd"
    return f"{n}th"

def calculate_places(times):
    """Calculate finish positions based only on the 4 displayed lane times.
    Returns list of 4 place strings e.g. ['(1st)', '(3rd)', '(2nd)', '']
    Empty lanes get empty string."""
    # Build list of (time_as_int, lane_index) for non-empty lanes
    ranked = sorted(
        [(int(t), i) for i, t in enumerate(times) if t],
        key=lambda x: x[0]
    )
    places = [""] * 4
    for pos, (_, idx) in enumerate(ranked):
        places[idx] = f"({ordinal(pos + 1)})"
    return places

def parse_gen(gen_path):
    """Parse .gen returning list of 4 time strings for lanes 1-4.

    Row POSITION (1-indexed) = lane number.
    Col 0 = finish place in full field (ignored — we recalculate from displayed lanes).
    Finish time = second-to-last populated numeric value from col 1 onwards.
    Works for all race distances (50m, 100m, 200m etc).
    """
    times = []
    with open(gen_path) as f:
        lines = f.readlines()
    for line in lines[1:5]:
        parts = line.strip().split(";")
        if not parts or parts[0] == "0":
            times.append("")
            continue
        vals = []
        for p in parts[1:]:
            p = p.strip()
            if p:
                try:
                    float(p)
                    vals.append(p)
                except ValueError:
                    pass
        finish = vals[-2] if len(vals) >= 2 else (vals[0] if vals else "")
        times.append(decimal_seconds_to_formatted(finish))
    return times

def parse_gen_filename(gen_path):
    """001-002-01F0005.gen → event='002', race='0005' (second segment = event)"""
    stem = Path(gen_path).stem
    m = re.match(r'^\d+-(\d+)-[A-Za-z0-9]+?F(\d{4})$', stem)
    if m:
        return m.group(1), m.group(2)
    return None, None

def find_html_companion(gen_path):
    folder = Path(gen_path).parent
    event, race = parse_gen_filename(gen_path)
    if not event or not race:
        return None
    for f in folder.glob("*.html"):
        m = re.search(r'Event\s+(\d+)-\S+\s+\(Race\s+(\d+)\)', f.name)
        if m and m.group(1) == event and m.group(2) == race:
            return f
    return None

def parse_html_asterisks(html_path):
    asterisked = set()
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return asterisked
    for td in tables[0].find_all("td"):
        cell_text = td.get_text(strip=True)
        if cell_text.replace("*", "").strip().isdigit():
            lane_num = int(cell_text.replace("*", "").strip())
            if "*" in cell_text and lane_num <= 4:
                asterisked.add(lane_num)
    return asterisked

def parse_html_race_info(html_path):
    """Returns (event_race_label, description)
    e.g. ('Event 2   Race 5', 'Female 9 Yrs/Over 50m Breaststroke')"""
    try:
        with open(html_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
        h1 = soup.find("h1")
        event_label = ""
        if h1:
            text = h1.get_text()
            em = re.search(r'Event\s+(\d+)', text)
            rm = re.search(r'Race\s+(\d+)', text)
            if em and rm:
                event_label = f"Event {int(em.group(1))}   Race {int(rm.group(1))}"
        h2s = soup.find_all("h2")
        description = h2s[0].get_text(strip=True) if h2s else ""
        return event_label, description
    except Exception:
        return "", ""

def format_clipboard(times):
    return "\t".join(times)

def find_unprocessed_gen_files(folder, processed):
    folder = Path(folder)
    if not folder.exists():
        return []
    return [f for f in sorted(folder.glob("*.gen")) if f.name not in processed]

# ── Excel integration ─────────────────────────────────────────────────────────
SHEET_NAME   = "Recording"
EXCEL_COLS   = {"1": "D", "2": "E", "3": "F", "4": "G"}  # lane → column
EVENT_COL    = "C"   # column C contains event labels and TIME marker
ARENA_XLSX_DIR = BASE_DIR / "arena_xlsx"

def find_or_open_excel(excel_path):
    """Return an xlwings Book for the spreadsheet, opening it if needed."""
    import xlwings as xw
    path = Path(excel_path)
    if not path.exists():
        raise FileNotFoundError(f"Spreadsheet not found: {excel_path}")
    # Check if already open
    try:
        for app in xw.apps:
            for book in app.books:
                if Path(book.fullname).resolve() == path.resolve():
                    logging.info(f"Excel already open: {book.name}")
                    return book
    except Exception:
        pass
    # Open it
    logging.info(f"Opening Excel: {path}")
    book = xw.Book(str(path))
    return book

def fill_spreadsheet(excel_path, event_num, times):
    """Find the TIME row for event_num in Recording sheet and fill D-G.

    Column B contains EVENT labels (merged cells — value only on top row).
    Column C contains row type: PLACE, TIME, SWIMMER, DQ REASON.
    Strategy: scan col B for EVENT {n}, then scan col C in that block for TIME.
    """
    import xlwings as xw
    book  = find_or_open_excel(excel_path)
    # Retry sheet access — Excel may need a moment after opening
    sheet = None
    for attempt in range(3):
        try:
            sheet = book.sheets[SHEET_NAME]
            break
        except Exception:
            if attempt < 2:
                import time as _time
                _time.sleep(1)
    if sheet is None:
        raise ValueError(
            f"Sheet '{SHEET_NAME}' not found in the spreadsheet. "
            f"Check the tab is named exactly '{SHEET_NAME}' (case-sensitive)."
        )

    search_str = f"EVENT {event_num}"
    # Read a range of col B and C values into memory for fast scanning
    last_row = 200  # spreadsheet has 33 events, 200 rows is well beyond that
    b_vals = sheet.range(f"B1:B{last_row}").value  # list of values (None for empty)
    c_vals = sheet.range(f"C1:C{last_row}").value

    # Find the row where B = "EVENT {n}" — handles merged cells (only top row has value)
    event_row = None
    for i, val in enumerate(b_vals):
        if val is not None and str(val).strip().upper() == search_str:
            event_row = i + 1  # 1-indexed
            break

    if event_row is None:
        raise ValueError(f"Could not find '{search_str}' in column B of sheet '{SHEET_NAME}'")

    # Scan col C from event_row downward for TIME, stop when next EVENT found
    target_row = None
    for i in range(event_row - 1, min(event_row + 15, last_row)):
        c_val = str(c_vals[i] or "").strip().upper()
        b_val = str(b_vals[i] or "").strip().upper()
        # Stop if we've hit the next event
        if i > event_row - 1 and b_val.startswith("EVENT "):
            break
        if c_val == "TIME":
            target_row = i + 1  # 1-indexed
            break

    if target_row is None:
        raise ValueError(f"Found '{search_str}' at row {event_row} but no TIME row within 15 rows")

    # Write times to D, E, F, G — store as integers (MMSSHH format)
    cols = ["D", "E", "F", "G"]
    for idx, time_str in enumerate(times[:4]):
        cell = sheet.range(f"{cols[idx]}{target_row}")
        cell.value = int(time_str) if time_str else None

    book.save()
    logging.info(f"Filled row {target_row} for {search_str}: {times}")
    return target_row

# ── Sound ──────────────────────────────────────────────────────────────────────
def beep(kind="info"):
    """Play raw tones via winsound.Beep — no dependency on Windows sound scheme."""
    try:
        import winsound
        if kind == "info":
            winsound.Beep(880, 150)   # short high beep
        elif kind == "warning":
            winsound.Beep(440, 300)   # lower longer beep
            time.sleep(0.1)
            winsound.Beep(330, 300)   # descending — attention needed
        elif kind == "error":
            for _ in range(3):
                winsound.Beep(220, 300)  # low urgent beep x3
                time.sleep(0.15)
        logging.info(f"Beep played: {kind}")
    except Exception as e:
        logging.warning(f"Beep failed ({kind}): {e}")

# ── App ────────────────────────────────────────────────────────────────────────
class ArenaLinkApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        # Note: title bar colour is controlled by Windows — cannot be changed via tkinter
        self.resizable(False, False)
        self.configure(bg=BG_BLACK)
        self.minsize(960, 100)  # fix width, height will be locked after render
        self.config_data   = load_config()
        self.processed     = load_processed()
        self.observer      = None
        self._pending_clip      = None
        self._logo_img          = None
        self._reprocess_queue   = []     # queue for batch reprocessing
        self._current_html_path = None
        self._current_gen_name  = None   # gen filename of current displayed race
        self._settings_open     = False
        self._settings_win      = None
        self._copied_once       = False  # track if clipboard copied this race
        self._review_mode       = False  # True when reviewing a previous file
        self._waiting_queue     = []     # files arrived while user confirming
        self._awaiting_entry_done = False  # True after file processed, until Entry Done
        self._review_prev_win   = None   # reference to review picker window
        self._base_height       = 600    # set properly after first render

        self._build_ui()
        self._show_single_button(disabled=True)  # start disabled

        # Window icon — iconbitmap handles both title bar and taskbar on Windows
        ico_path = BASE_DIR / "assets" / "arenalink.ico"
        if ico_path.exists():
            try:
                self.iconbitmap(default=str(ico_path))
                logging.info("ICO loaded for title bar and taskbar")
            except Exception as e:
                logging.warning(f"iconbitmap failed: {e}")
                # Fallback: try wm_iconbitmap
                try:
                    self.wm_iconbitmap(str(ico_path))
                    logging.info("ICO loaded via wm_iconbitmap fallback")
                except Exception as e2:
                    logging.warning(f"wm_iconbitmap also failed: {e2}")
        else:
            logging.warning(f"ICO not found at {ico_path}")

        # Lock window size after first render
        self.after(100, self._lock_window_size)
        self.after(150, self._update_team_label)

        if not self.config_data["watch_folder"]:
            self.after(200, self.open_settings)
        else:
            self.after(200, self.start_watching)

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────────────
        # Logo and title sit in same row. Title uses place() to centre on the
        # full header width regardless of logo size.
        hdr = tk.Frame(self, bg=BG_MID, height=140)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.pack_propagate(False)
        hdr.grid_propagate(False)

        # Load logo first so we know its size
        self._logo_img = self._load_logo()

        # Logo — packed left
        logo_lbl = tk.Label(hdr, bg=BG_MID,
                            image=self._logo_img if self._logo_img else None,
                            text="" if self._logo_img else "WST",
                            font=(MONO, 18, "bold") if not self._logo_img else None,
                            fg=ORANGE)
        logo_lbl.place(x=18, rely=0.5, anchor="w")

        # Settings button — placed right
        settings_btn = tk.Button(hdr, text="⚙", command=self.open_settings,
                  bg=BG_MID, fg=WHITE_DIM, relief="flat",
                  activebackground="#2a1a00", activeforeground=ORANGE,
                  font=(MONO, 16), cursor="hand2", padx=10)
        settings_btn.place(relx=1.0, rely=0.5, anchor="e", x=-14)

        # Title — placed at true centre of full header width
        tk.Label(hdr, text=APP_NAME, font=(MONO, 32, "bold"),
                 bg=BG_MID, fg=ORANGE).place(relx=0.5, rely=0.38, anchor="center")
        tk.Label(hdr, text=VERSION, font=(MONO, 11, "bold"),
                 bg=BG_MID, fg=ORANGE_DIM).place(relx=0.5, rely=0.72, anchor="center")

        # ── Status ──────────────────────────────────────────────────────────────
        sf = tk.Frame(self, bg=BG_PANEL)
        sf.grid(row=1, column=0, sticky="ew")
        self.status_var = tk.StringVar(value="Initialising…")
        tk.Label(sf, textvariable=self.status_var, font=(MONO, 11),
                 bg=BG_PANEL, fg=ORANGE_LT, anchor="w"
                 ).pack(fill="x", padx=20, pady=6)

        # ── Race info ───────────────────────────────────────────────────────────
        race_frame = tk.Frame(self, bg=BG_BLACK)
        race_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(16, 0))
        self.team_label_var  = tk.StringVar(value="")
        self.event_label_var = tk.StringVar(value="")
        self.desc_label_var  = tk.StringVar(value="")
        tk.Label(race_frame, textvariable=self.team_label_var,
                 font=(MONO, 26, "bold"), bg=BG_BLACK, fg=WHITE,
                 anchor="center").pack(fill="x")
        tk.Label(race_frame, textvariable=self.event_label_var,
                 font=(MONO, 18, "bold"), bg=BG_BLACK, fg=WHITE,
                 anchor="center").pack(fill="x")
        tk.Label(race_frame, textvariable=self.desc_label_var,
                 font=(MONO, 14), bg=BG_BLACK, fg=ORANGE_LT,
                 anchor="center").pack(fill="x")

        # ── Separator: event info → lanes ───────────────────────────────────────
        tk.Frame(self, bg="#333333", height=1).grid(
            row=3, column=0, sticky="ew", padx=0, pady=(10, 0))

        # ── Lane display ────────────────────────────────────────────────────────
        lanes_outer = tk.Frame(self, bg=BG_BLACK)
        lanes_outer.grid(row=4, column=0, sticky="ew", padx=0, pady=(8, 0))
        lanes_outer.columnconfigure((0, 1, 2, 3), weight=1, uniform="lane")
        self.lane_vars      = []
        self.lane_labels    = []
        self.lane_sub       = []
        self.lane_borders   = []   # border frames for asterisk/empty indicators
        self.lane_place_vars = []  # finish position labels
        for i in range(4):
            # Outer col holds lane label + border frame
            col = tk.Frame(lanes_outer, bg=BG_BLACK, width=200)
            col.grid(row=0, column=i, padx=10)
            col.grid_propagate(False)  # hold fixed width
            tk.Label(col, text=f"LANE {i+1}", font=(MONO, 13, "bold"),
                     bg=BG_BLACK, fg=ORANGE_DIM).pack(anchor="center")
            # Border frame — default no border (bg matches parent)
            border = tk.Frame(col, bg=BG_BLACK,
                                  highlightthickness=1,
                                  highlightbackground=BG_BLACK)
            border.pack(anchor="center")
            var = tk.StringVar(value="--")
            lbl = tk.Label(border, textvariable=var, font=(MONO, 34, "bold"),
                           bg=BG_BLACK, fg=ORANGE)
            lbl.pack(padx=6, pady=0, anchor="center")
            sub_var = tk.StringVar(value="")
            tk.Label(col, textvariable=sub_var, font=(MONO, 10),
                     bg=BG_BLACK, fg="#cc4400").pack(pady=0)
            place_var = tk.StringVar(value="")
            tk.Label(col, textvariable=place_var, font=(MONO, 13, "bold"),
                     bg=BG_BLACK, fg=ORANGE_DIM).pack(pady=0)
            self.lane_vars.append(var)
            self.lane_labels.append(lbl)
            self.lane_sub.append(sub_var)
            self.lane_borders.append(border)
            self.lane_place_vars.append(place_var)

        # ── Warning panel — blocking (empty lanes, red) ──────────────────────────
        self.warn_frame = tk.Frame(self, bg=WARN_BG)
        self.warn_title = tk.Label(self.warn_frame, text="",
                                   font=(MONO, 13, "bold"),
                                   bg=WARN_BG, fg=WARN_FG, anchor="w")
        self.warn_title.pack(fill="x", padx=20, pady=(13, 3))
        self.warn_lanes = tk.Label(self.warn_frame, text="",
                                   font=(MONO, 11),
                                   bg=WARN_BG, fg=WARN_DET,
                                   justify="left", anchor="w",
                                   wraplength=880)
        self.warn_lanes.pack(fill="x", padx=20, pady=(0, 13))
        self.warn_spacer = tk.Frame(self, bg=BG_BLACK, height=15)

        # ── Info panel — non-blocking (backup times, yellow) ─────────────────────
        self.info_frame = tk.Frame(self, bg=INFO_BG)
        self.info_label = tk.Label(self.info_frame, text="",
                                   font=(MONO, 11),
                                   bg=INFO_BG, fg=INFO_FG,
                                   justify="left", anchor="w",
                                   wraplength=880)
        self.info_label.pack(fill="x", padx=20, pady=10)
        self.info_spacer = tk.Frame(self, bg=BG_BLACK, height=8)

        # ── Review notice panel (shown instead of warning in review mode) ────────
        REVIEW_BG = "#0d1f3c"
        self.review_notice_frame = tk.Frame(self, bg=REVIEW_BG)
        tk.Label(self.review_notice_frame,
                 text="📂  Note: You are viewing a previously confirmed file — no changes will be made.",
                 font=(MONO, 11, "bold"),
                 bg=REVIEW_BG, fg="#55aaff", anchor="w"
                 ).pack(fill="x", padx=20, pady=12)
        self.review_notice_spacer = tk.Frame(self, bg=BG_BLACK, height=15)

        # ── Separator: positions → buttons ──────────────────────────────────────
        tk.Frame(self, bg="#333333", height=1).grid(
            row=6, column=0, sticky="ew", padx=0, pady=(6, 0))

        # ── Action buttons: always 3 columns once a file is processed ──────────
        action = tk.Frame(self, bg=BG_BLACK)
        action.grid(row=7, column=0, sticky="ew", padx=20, pady=(8, 0))
        action.columnconfigure(0, weight=1)
        action.columnconfigure(1, weight=1)
        action.columnconfigure(2, weight=1)
        action.columnconfigure(3, weight=1)

        action.columnconfigure(3, weight=1)  # 4 columns for 4 buttons

        self.review_btn = tk.Button(action, text="🌐  OPEN & REVIEW HTML",
                                    font=(MONO, 11, "bold"),
                                    bg=ORANGE_DIM, fg=WHITE,
                                    activebackground=ORANGE,
                                    activeforeground=WHITE,
                                    relief="flat", padx=6, pady=14,
                                    state="disabled", cursor="hand2",
                                    command=self.open_html_review)
        self.review_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2))

        self.copy_btn_single = tk.Button(action, text="📋  COPY TO CLIPBOARD",
                                         font=(MONO, 11, "bold"),
                                         bg=ORANGE_DIM, fg=WHITE,
                                         activebackground=ORANGE,
                                         activeforeground=WHITE,
                                         relief="flat", padx=6, pady=14,
                                         state="disabled", cursor="hand2",
                                         command=self.manual_copy)
        self.copy_btn_single.grid(row=0, column=1, sticky="ew", padx=2)

        self.fill_btn = tk.Button(action, text="📊  FILL SPREADSHEET",
                                  font=(MONO, 11, "bold"),
                                  bg="#003a5c", fg=WHITE,
                                  activebackground="#005a8c",
                                  activeforeground=WHITE,
                                  relief="flat", padx=6, pady=14,
                                  state="disabled", cursor="hand2",
                                  command=self.fill_spreadsheet_action)
        self.fill_btn.grid(row=0, column=2, sticky="ew", padx=2)

        self.entry_done_btn = tk.Button(action, text="✅  ENTRY DONE",
                                        font=(MONO, 11, "bold"),
                                        bg="#1a4a1a", fg="#446644",
                                        activebackground="#226622",
                                        activeforeground=WHITE,
                                        relief="flat", padx=6, pady=14,
                                        state="disabled", cursor="hand2",
                                        command=self.entry_done)
        self.entry_done_btn.grid(row=0, column=3, sticky="ew", padx=(2, 0))

        # keep review_btn_review as alias for compatibility
        self.copy_btn_review = self.copy_btn_single

        self.copied_label = tk.Label(action, text="",
                                     font=(MONO, 11),
                                     bg=BG_BLACK, fg=GREEN)
        self.copied_label.grid(row=1, column=0, columnspan=4, pady=(5, 0))

        # ── Separator: buttons → info row ───────────────────────────────────────
        tk.Frame(self, bg="#333333", height=1).grid(
            row=8, column=0, sticky="ew", padx=0, pady=(6, 0))

        # ── Info row: last file left, confirmed count right ─────────────────────
        info_row = tk.Frame(self, bg=BG_BLACK)
        info_row.grid(row=9, column=0, sticky="ew", padx=20, pady=(5, 2))
        info_row.columnconfigure(0, weight=1)
        info_row.columnconfigure(1, weight=1)

        self.last_file_var = tk.StringVar(value="No file processed yet")
        tk.Label(info_row, textvariable=self.last_file_var,
                 font=(MONO, 11), bg=BG_BLACK, fg="#555533",
                 anchor="w").grid(row=0, column=0, sticky="w")

        self.confirmed_count_var = tk.StringVar(value="")
        tk.Label(info_row, textvariable=self.confirmed_count_var,
                 font=(MONO, 11), bg=BG_BLACK, fg="#336633",
                 anchor="e").grid(row=0, column=1, sticky="e")

        # ── Waiting alert — shown in info row when queue has files ─────────────
        # Not a separate grid row — lives alongside last_file_var
        self.waiting_frame = tk.Frame(self, bg="#1a1a00")  # kept for compat
        self.waiting_label = tk.Label(self.waiting_frame, text="",
                                      font=(MONO, 10, "bold"),
                                      bg="#1a1a00", fg="#cccc00", anchor="w")
        self.waiting_label.pack(fill="x", padx=16, pady=0)
        # Inline waiting label in info row
        self.waiting_inline = tk.Label(info_row, text="",
                                       font=(MONO, 10, "bold"),
                                       bg="#1a1a00", fg="#cccc00", anchor="w")
        self.waiting_inline.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2,0))

        # ── Bottom row: reprocess + review previous + next file ─────────────────
        bottom = tk.Frame(self, bg=BG_BLACK)
        bottom.grid(row=11, column=0, sticky="ew", padx=20, pady=(4, 15))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        bottom.columnconfigure(2, weight=1)

        self.reprocess_btn = tk.Button(bottom, text="↺  Process Unprocessed Files",
                  font=(MONO, 10), bg="#1a1100", fg="#664400",
                  relief="flat", cursor="hand2",
                  activebackground="#2a1f00", activeforeground=ORANGE_DIM,
                  command=self.reprocess_unprocessed)

        self.review_prev_btn = tk.Button(bottom, text="📂  Review a Previous File",
                                         font=(MONO, 10), bg="#1a1100", fg="#664400",
                                         relief="flat", cursor="hand2",
                                         activebackground="#2a1f00", activeforeground=ORANGE_DIM,
                                         state="disabled",
                                         command=self.open_review_previous)

        self.next_btn = tk.Button(bottom, text="",
                                  font=(MONO, 11, "bold"),
                                  bg="#1a1100", fg=ORANGE_DIM,
                                  relief="flat", cursor="hand2",
                                  activebackground="#2a1f00", activeforeground=ORANGE,
                                  state="disabled",
                                  command=self._process_next_in_queue)
        self._next_btn_visible = False
        self._layout_bottom_row()  # initial 2-button layout

        self.columnconfigure(0, weight=1)

    # ── Logo loader ────────────────────────────────────────────────────────────
    def _load_logo(self):
        """Load logo PNG and return PhotoImage, or None on failure."""
        if not LOGO_PATH.exists():
            logging.warning(f"Logo not found at {LOGO_PATH}")
            return None
        try:
            from PIL import Image, ImageTk
            img = Image.open(LOGO_PATH).convert("RGB")
            photo = ImageTk.PhotoImage(img)
            logging.info(f"Logo loaded via Pillow: {img.size}")
            return photo
        except Exception as e:
            logging.warning(f"Pillow logo load failed: {e}")
        try:
            photo = tk.PhotoImage(file=str(LOGO_PATH))
            logging.info(f"Logo loaded via tk.PhotoImage")
            return photo
        except Exception as e:
            logging.warning(f"tk.PhotoImage logo load failed: {e}")
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _layout_bottom_row(self, show_next=False):
        """Re-grid bottom row: 2 buttons when next hidden, 3 when shown."""
        self.reprocess_btn.grid_forget()
        self.review_prev_btn.grid_forget()
        self.next_btn.grid_forget()
        if show_next:
            self.reprocess_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
            self.review_prev_btn.grid(row=0, column=1, sticky="ew", padx=3)
            self.next_btn.grid(row=0, column=2, sticky="ew", padx=(3, 0))
            self.next_btn.master.columnconfigure(0, weight=1)
            self.next_btn.master.columnconfigure(1, weight=1)
            self.next_btn.master.columnconfigure(2, weight=1)
        else:
            self.reprocess_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
            self.review_prev_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))
            self.next_btn.master.columnconfigure(0, weight=1)
            self.next_btn.master.columnconfigure(1, weight=1)
            self.next_btn.master.columnconfigure(2, weight=0)
        self._next_btn_visible = show_next

    def _show_single_button(self, disabled=False):
        """Show waiting state on startup / between files."""
        self._set_waiting_state()

    def _update_confirmed_count(self):
        count = count_confirmed()
        if count == 0:
            self.confirmed_count_var.set("")
        else:
            self.confirmed_count_var.set(f"Entries confirmed: {count}")

    def _check_waiting_queue(self):
        """Show/hide waiting alert based on queue size."""
        n = len(self._waiting_queue)
        if n > 0:
            self.waiting_inline.config(
                text=f"  ⚠  {n} file{'s' if n>1 else ''} arrived and waiting",
                bg="#1a1a00")
            self.next_btn.config(state="normal",
                                 text=f"▶  Next File  ({n} waiting)",
                                 fg=ORANGE, bg="#1a1100")
            self._layout_bottom_row(show_next=True)
        else:
            self.waiting_inline.config(text="", bg=BG_BLACK)
            if not self._review_mode:
                self.next_btn.config(state="disabled", text="")
                self._layout_bottom_row(show_next=False)

    # ── Review Previous File ───────────────────────────────────────────────────
    def open_review_previous(self):
        """Show a visual picker of previously processed files."""
        entries = load_log_entries()
        if not entries:
            messagebox.showinfo("No history", "No processed files found in log.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title("Review a Previous File")
        win.configure(bg=BG_MID)
        win.resizable(False, False)
        self._review_prev_win = win
        self.wm_attributes("-alpha", 0.6)

        def on_review_win_close():
            self._review_prev_win = None
            self.wm_attributes("-alpha", 1.0)
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_review_win_close)

        def on_main_close_while_reviewing():
            self._shake_window()
            if win.winfo_exists():
                win.lift()
                win.focus_force()
        self.protocol("WM_DELETE_WINDOW", on_main_close_while_reviewing)
        win.transient(self)
        win.focus_force()

        tk.Label(win, text="Select a file to review",
                 font=(MONO, 12, "bold"), bg=BG_MID, fg=ORANGE
                 ).pack(padx=20, pady=(16, 8))

        # Scrollable list frame
        container = tk.Frame(win, bg=BG_MID)
        container.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        canvas = tk.Canvas(container, bg=BG_DARK, highlightthickness=0, width=560, height=320)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=BG_DARK)

        scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scroll_frame.bind("<MouseWheel>", _on_mousewheel)

        def select_entry(entry):
            on_review_win_close()   # restores alpha, WM_DELETE_WINDOW protocol, clears ref
            self._load_previous_file(entry)

        for entry in entries:
            status_colour = "#226622" if entry["status"] == "confirmed" else "#664400"
            status_text   = "✅ confirmed" if entry["status"] == "confirmed" else "⏳ processed"
            row = tk.Frame(scroll_frame, bg=BG_PANEL, cursor="hand2")
            row.pack(fill="x", padx=4, pady=3)

            tk.Label(row, text=entry["gen"], font=(MONO, 9, "bold"),
                     bg=BG_PANEL, fg=ORANGE_LT, anchor="w"
                     ).pack(side="left", padx=(10, 4), pady=8)
            tk.Label(row, text=entry["ts"][:16] if entry["ts"] else "",
                     font=(MONO, 8), bg=BG_PANEL, fg="#556655", anchor="e"
                     ).pack(side="right", padx=(4, 6), pady=8)
            tk.Label(row, text=status_text,
                     font=(MONO, 8), bg=BG_PANEL, fg=status_colour, anchor="e"
                     ).pack(side="right", padx=4, pady=8)

            row.bind("<Button-1>", lambda e, en=entry: select_entry(en))
            row.bind("<MouseWheel>", _on_mousewheel)
            for child in row.winfo_children():
                child.bind("<Button-1>", lambda e, en=entry: select_entry(en))
                child.bind("<MouseWheel>", _on_mousewheel)
            row.bind("<Enter>", lambda e, r=row: r.configure(bg="#2a2a3a"))
            row.bind("<Leave>", lambda e, r=row: r.configure(bg=BG_PANEL))

        tk.Button(win, text="Cancel", command=on_review_win_close,
                  font=(MONO, 9), bg=BG_MID, fg=WHITE_DIM,
                  relief="flat", cursor="hand2", pady=6
                  ).pack(pady=(4, 16))

    def _load_previous_file(self, entry):
        """Load and display a previously processed file for review."""
        folder = Path(self.config_data.get("watch_folder", ""))
        gen_path  = folder / entry["gen"]
        html_name = entry["html"]

        # Find html companion
        html_path = None
        if html_name:
            hp = folder / html_name
            if hp.exists():
                html_path = hp
        if not html_path:
            html_path = find_html_companion(gen_path)

        if not gen_path.exists():
            messagebox.showerror("File not found",
                                 f"Cannot find {entry['gen']} in watch folder.", parent=self)
            return

        self._review_mode = True
        self.set_status(f"📂 Note: This file has already been processed — {entry["gen"]}")

        # Update bottom row for review mode — show Exit Review button
        self.next_btn.config(state="normal", text="↩  Exit Review Mode",
                             fg=ORANGE, bg="#1a1100",
                             activeforeground=ORANGE,
                             command=self._exit_review_mode)
        self._layout_bottom_row(show_next=True)
        self.review_prev_btn.config(text="📂  Review Another File")

        # Process and display (with review_mode flag)
        self.after(0, lambda: self._process_files(gen_path, html_path, review_mode=True))

    def _exit_review_mode(self):
        self._review_mode = False
        self._awaiting_entry_done = False
        self._current_gen_name = None
        self.review_prev_btn.config(text="📂  Review a Previous File")
        self.next_btn.config(state="disabled", text="", command=self._process_next_in_queue)
        self._layout_bottom_row(show_next=False)
        self._hide_warning()  # also hides info panel
        self._set_waiting_state()
        self.set_status(f"👁  Watching: {self.config_data.get('watch_folder', '')}")
        # Restore event/race labels
        self.event_label_var.set("")
        self.desc_label_var.set("")
        for i in range(4):
            self.lane_vars[i].set("--")
            self.lane_labels[i].config(fg=DIM, bg=BG_BLACK)
            self.lane_sub[i].set("")
            self.lane_place_vars[i].set("")
            self.lane_borders[i].config(highlightbackground=BG_BLACK, highlightthickness=1, bg=BG_BLACK)
        self.last_file_var.set("No file processed yet")
        self.waiting_inline.config(text="", bg=BG_BLACK)
        self._check_waiting_queue()

    # ── Team label ────────────────────────────────────────────────────────────
    def _update_team_label(self):
        team = self.config_data.get("team", "")
        if team == "A":
            self.team_label_var.set("—  A TEAMS  —")
        elif team == "B":
            self.team_label_var.set("—  B TEAMS  —")
        else:
            self.team_label_var.set("")

    # ── Window size lock ───────────────────────────────────────────────────────
    def _lock_window_size(self):
        """Record base window height (no warning panel) and set minimum."""
        self.update_idletasks()
        w = max(self.winfo_width(), 960)
        h = self.winfo_reqheight() + 20
        self._base_height = h
        self.geometry(f"{w}x{h}")
        self.minsize(w, h)
        self.resizable(False, True)   # allow vertical resize for warnings
        logging.info(f"Window base locked at {w}x{h}")

    # ── Warning helpers ────────────────────────────────────────────────────────
    def _show_warning(self, title, detail):
        self.review_notice_frame.grid_forget()
        self.review_notice_spacer.grid_forget()
        self.info_frame.grid_forget()
        self.info_spacer.grid_forget()
        self.warn_title.config(text=title)
        self.warn_lanes.config(text=detail)
        self.warn_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.warn_spacer.grid(row=6, column=0, sticky="ew")
        self._adjust_window_height()

    def _show_info(self, text):
        """Show non-blocking yellow info panel (backup times)."""
        self.warn_frame.grid_forget()
        self.warn_spacer.grid_forget()
        self.review_notice_frame.grid_forget()
        self.review_notice_spacer.grid_forget()
        self.info_label.config(text=text)
        self.info_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.info_spacer.grid(row=6, column=0, sticky="ew")
        self._adjust_window_height()

    def _hide_warning(self):
        self.warn_frame.grid_forget()
        self.warn_spacer.grid_forget()
        self.info_frame.grid_forget()
        self.info_spacer.grid_forget()
        self.review_notice_frame.grid_forget()
        self.review_notice_spacer.grid_forget()
        self._adjust_window_height()

    def _show_review_notice(self):
        """Show the blue 'previously confirmed' notice instead of warning panel."""
        self.warn_frame.grid_forget()
        self.warn_spacer.grid_forget()
        self.review_notice_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 0))
        self.review_notice_spacer.grid(row=6, column=0, sticky="ew")
        self._adjust_window_height()

    def _adjust_window_height(self):
        """Resize window to fit content after warning panel shown/hidden."""
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_reqheight()
        # Add headroom for bottom buttons always being visible
        h = max(h, self._base_height) + 20
        self.geometry(f"{w}x{h}")

    # ── Settings ───────────────────────────────────────────────────────────────
    def _shake_window(self):
        """Shake the window left/right to signal it cannot be closed."""
        self.update_idletasks()
        w  = self.winfo_width()
        h  = self.winfo_height()
        x0 = self.winfo_x()
        y0 = self.winfo_y()
        logging.info(f"Shake: window at {x0},{y0} size {w}x{h}")
        shakes = [15, -15, 12, -12, 8, -8, 4, -4, 0]
        def do_shake(i=0):
            if i < len(shakes):
                self.geometry(f"{w}x{h}+{x0 + shakes[i]}+{y0}")
                self.update_idletasks()
                self.after(30, lambda: do_shake(i + 1))
            else:
                self.geometry(f"{w}x{h}+{x0}+{y0}")
        do_shake()

    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg=BG_MID)
        win.resizable(False, False)
        win.minsize(520, 100)
        self._settings_open = True
        self._settings_win  = win

        # Dim overlay on main window to show settings is active
        overlay = tk.Frame(self, bg="black")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.configure(cursor="arrow")
        # Semi-transparent effect via reduced opacity label
        tk.Label(overlay, bg="black", text="").place(relwidth=1, relheight=1)
        overlay.bind("<Button-1>", lambda e: (self._shake_window(), win.lift(), win.focus_force()))
        self.wm_attributes("-alpha", 0.6)

        def on_settings_close():
            self._settings_open = False
            self._settings_win  = None
            self.wm_attributes("-alpha", 1.0)
            overlay.destroy()
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_settings_close)

        # X on main window shakes it (no grab_set so this actually fires)
        def on_main_close_blocked():
            self._shake_window()
            if win.winfo_exists():
                win.lift()
                win.focus_force()

        self.protocol("WM_DELETE_WINDOW", on_main_close_blocked)
        win.transient(self)
        win.focus_force()

        tk.Label(win, text="Watch Folder", font=(MONO, 9, "bold"),
                 bg=BG_MID, fg=ORANGE_LT).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 2))

        folder_var = tk.StringVar(value=self.config_data["watch_folder"])
        tk.Entry(win, textvariable=folder_var, width=50,
                 font=(MONO, 9), bg=BG_PANEL, fg=WHITE,
                 insertbackground=WHITE, relief="flat"
                 ).grid(row=1, column=0, padx=16, pady=2)

        def browse():
            p = filedialog.askdirectory(title="Select Watch Folder")
            if p:
                folder_var.set(p)

        tk.Button(win, text="Browse…", command=browse,
                  bg=ORANGE_DIM, fg=WHITE, relief="flat", cursor="hand2"
                  ).grid(row=1, column=1, padx=(0, 16), pady=2)

        sound_var = tk.BooleanVar(value=self.config_data["sound_alerts"])
        tk.Checkbutton(win, text="Sound alerts", variable=sound_var,
                       font=(MONO, 9), bg=BG_MID, fg=ORANGE_LT,
                       selectcolor=BG_PANEL, activebackground=BG_MID,
                       activeforeground=WHITE
                       ).grid(row=2, column=0, sticky="w", padx=16, pady=10)

        # Team selector
        tk.Label(win, text="Recording for Team",
                 font=(MONO, 9, "bold"), bg=BG_MID, fg=ORANGE_LT
                 ).grid(row=3, column=0, sticky="w", padx=16, pady=(4, 2))

        team_note = tk.Label(win, text="A Teams = Heat 1 files only   |   B Teams = Heat 2 files only",
                             font=(MONO, 8), bg=BG_MID, fg="#557755")
        team_note.grid(row=4, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 6))

        team_var = tk.StringVar(value=self.config_data.get("team", "A"))
        team_frame = tk.Frame(win, bg=BG_MID)
        team_frame.grid(row=5, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 10))

        for label, val in [("A Teams (Heat 1)", "A"), ("B Teams (Heat 2)", "B")]:
            tk.Radiobutton(team_frame, text=label, variable=team_var, value=val,
                           font=(MONO, 10, "bold"), bg=BG_MID, fg=ORANGE_LT,
                           selectcolor=BG_PANEL, activebackground=BG_MID,
                           activeforeground=WHITE
                           ).pack(side="left", padx=(0, 20))

        def save():
            folder = folder_var.get().strip()
            if not folder:
                messagebox.showwarning("Required", "Please set a watch folder.", parent=win)
                return
            self.config_data["watch_folder"] = folder
            self.config_data["sound_alerts"]  = sound_var.get()
            self.config_data["team"]          = team_var.get()
            self.config_data["excel_path"]     = excel_var.get().strip()
            self.config_data["excel_autofill"] = autofill_var.get()
            save_config(self.config_data)
            on_settings_close()  # restore main window X before destroying
            self._update_team_label()
            if hasattr(self, 'fill_btn'):
                self._update_fill_btn_state()
            self.start_watching()

        tk.Button(win, text="Save & Start Watching", command=save,
                  font=(MONO, 10, "bold"), bg=ORANGE_DIM, fg=WHITE,
                  activebackground=ORANGE,
                  relief="flat", padx=16, pady=8, cursor="hand2"
                  ).grid(row=13, column=0, columnspan=2, padx=16, pady=(8, 4))

        # Separator
        tk.Frame(win, bg="#333333", height=1).grid(
            row=14, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 8))

        # Excel spreadsheet path
        tk.Label(win, text="Excel Spreadsheet Path",
                 font=(MONO, 9, "bold"), bg=BG_MID, fg=ORANGE_LT
                 ).grid(row=9, column=0, sticky="w", padx=16, pady=(12, 2))

        excel_var = tk.StringVar(value=self.config_data.get("excel_path", ""))
        tk.Entry(win, textvariable=excel_var, width=50,
                 font=(MONO, 9), bg=BG_PANEL, fg=WHITE,
                 insertbackground=WHITE, relief="flat"
                 ).grid(row=10, column=0, padx=16, pady=2)

        def browse_excel():
            from tkinter import filedialog as _fd
            path = _fd.askopenfilename(
                title="Select Excel Spreadsheet",
                filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
                initialdir=str(ARENA_XLSX_DIR) if ARENA_XLSX_DIR.exists() else str(BASE_DIR),
                parent=win)
            if path:
                excel_var.set(path)

        tk.Button(win, text="Browse…", command=browse_excel,
                  bg=ORANGE_DIM, fg=WHITE, relief="flat", cursor="hand2"
                  ).grid(row=10, column=1, padx=(0, 16), pady=2)

        autofill_var = tk.BooleanVar(value=self.config_data.get("excel_autofill", True))
        tk.Checkbutton(win, text="Auto-fill spreadsheet (📊 Fill Spreadsheet button enabled)",
                       variable=autofill_var,
                       font=(MONO, 9), bg=BG_MID, fg=ORANGE_LT,
                       selectcolor=BG_PANEL, activebackground=BG_MID,
                       activeforeground=WHITE
                       ).grid(row=11, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 4))

        # Separator before save
        tk.Frame(win, bg="#333333", height=1).grid(
            row=12, column=0, columnspan=2, sticky="ew", padx=16, pady=(8, 4))

        def delete_log():
            confirm = messagebox.askyesno(
                "Delete Processed Files Log",
                "⚠ This will delete the log of all files processed on this computer.\n\n"
                "ArenaLink will re-process any files it finds in the watch folder.\n\n"
                "Are you sure?",
                icon="warning", parent=win)
            if confirm:
                try:
                    LOG_FILE.unlink(missing_ok=True)
                    self.processed = set()
                    logging.info("Processed log deleted by user")
                    messagebox.showinfo("Done", "Processed files log deleted.", parent=win)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not delete log:\n{e}", parent=win)

        tk.Button(win, text="🗑  Delete Processed Files Log",
                  font=(MONO, 9), bg="#2a0a0a", fg="#cc4444",
                  activebackground="#440000", activeforeground="#ff6666",
                  relief="flat", padx=16, pady=6, cursor="hand2",
                  command=delete_log
                  ).grid(row=15, column=0, columnspan=2, padx=16, pady=(0, 16))

    # ── Watcher ────────────────────────────────────────────────────────────────
    def start_watching(self):
        folder = self.config_data["watch_folder"]
        if not folder or not os.path.exists(folder):
            self.set_status(f"⚠ Folder not found: {folder}")
            return
        if self.observer:
            self.observer.stop()
            self.observer.join()
        handler = GenFileHandler(self)
        self.observer = PollingObserver(timeout=1)
        self.observer.schedule(handler, folder, recursive=False)
        self.observer.start()
        self.set_status(f"👁  Watching: {folder}")
        logging.info(f"Watching: {folder}")

    # ── Reprocess ──────────────────────────────────────────────────────────────
    def reprocess_unprocessed(self):
        folder = self.config_data.get("watch_folder", "")
        self.processed = load_processed()
        files  = find_unprocessed_gen_files(folder, self.processed)
        if not files:
            messagebox.showinfo("Nothing to do",
                                "No unprocessed .gen files found.", parent=self)
            return
        names   = "\n".join(f.name for f in files[:10])
        more    = f"\n…and {len(files) - 10} more" if len(files) > 10 else ""
        confirm = messagebox.askyesno(
            "Process unprocessed files?",
            f"Found {len(files)} unprocessed file(s):\n\n{names}{more}\n\nProcess now (one at a time)?",
            parent=self)
        if confirm:
            self._reprocess_queue = list(files)
            self._process_next_in_queue()

    def _process_next_in_queue(self):
        """Process next from reprocess or waiting queue."""
        self.next_btn.config(state="disabled", text="")
        self._layout_bottom_row(show_next=False)
        self._awaiting_entry_done = False
        self._current_gen_name = None  # clear so on_gen_detected doesn't re-queue
        logging.info(f"_process_next: waiting={len(self._waiting_queue)} reprocess={len(self._reprocess_queue)}")

        # Waiting queue takes priority (live files)
        if self._waiting_queue:
            gen_path = self._waiting_queue.pop(0)
            remaining = len(self._waiting_queue) + len(self._reprocess_queue)
            self.set_status(f"📄 {gen_path.name} detected — waiting for HTML…"
                            + (f"  ({remaining} more queued)" if remaining else ""))
            threading.Thread(target=self._wait_for_html, args=(gen_path,), daemon=True).start()
        elif self._reprocess_queue:
            gen_path = self._reprocess_queue.pop(0)
            remaining = len(self._reprocess_queue)
            self.set_status(
                f"📂 Processing queued file: {gen_path.name}"
                + (f"  ({remaining} remaining)" if remaining else "  (last file)"))
            threading.Thread(target=self._wait_for_html, args=(gen_path,), daemon=True).start()
        else:
            self.set_status("✅ All queued files processed")
            self._set_waiting_state()

    def _advance_queue_if_pending(self):
        """Called after a file is processed — show Next button if queue has more."""
        if self._reprocess_queue:
            remaining = len(self._reprocess_queue)
            self.next_btn.config(state="normal",
                                 text=f"Next File →  ({remaining} remaining)")
            self._layout_bottom_row(show_next=True)
        else:
            self._layout_bottom_row(show_next=False)

    # ── File pipeline ──────────────────────────────────────────────────────────
    def on_gen_detected(self, gen_path):
        gen_path = Path(gen_path)
        if gen_path.name in self.processed:
            logging.info(f"Skipping already processed: {gen_path.name}")
            return
        # Filter by team (heat number) if configured
        team = self.config_data.get("team", "")
        if team in ("A", "B"):
            m = re.match(r'^\d+-\d+-(\d+)F\d+\.gen$', gen_path.name)
            if m:
                heat_num = int(m.group(1))
                expected = 1 if team == "A" else 2
                if heat_num != expected:
                    logging.info(f"Skipping {gen_path.name} — wrong team (heat {heat_num}, configured for {team} Teams)")
                    return
        # If user hasn't confirmed current entry, queue this file
        if self._awaiting_entry_done and not self._review_mode:
            if gen_path not in self._waiting_queue:
                self._waiting_queue.append(gen_path)
                self._check_waiting_queue()
                if self.config_data["sound_alerts"]:
                    beep("warning")
                logging.info(f"Queued (awaiting entry done): {gen_path.name}")
            return
        self.set_status(f"📄 {gen_path.name} detected — waiting for HTML…")
        logging.info(f"GEN detected: {gen_path.name}")
        if not self._review_mode:
            self._awaiting_entry_done = True  # block further files immediately
        threading.Thread(target=self._wait_for_html, args=(gen_path,), daemon=True).start()

    def _wait_for_html(self, gen_path):
        for attempt in range(1, 5):
            time.sleep(2)
            html_path = find_html_companion(gen_path)
            if html_path:
                self.after(0, lambda p=html_path: self.set_status(
                    f"✅ {p.name} detected — parsing…"))
                logging.info(f"HTML found: {html_path.name}")
                self.after(0, lambda p=html_path: self._process_files(gen_path, p))
                return
            self.after(0, lambda a=attempt: self.set_status(
                f"⏳ Waiting for HTML… ({a*2}s)"))
        logging.error(f"HTML not found for {gen_path.name} after 8s")
        self.after(0, lambda: self._html_missing_error(gen_path.name))

    def _html_missing_error(self, filename=""):
        self.set_status("🚨 HTML FILE NOT FOUND — CHECK NETWORK SHARE")
        self._show_warning(
            "⚠ HTML file did not arrive within 8 seconds.",
            f"File: {filename}\n"
            "Please check the network share manually.\n"
            "This race will need manual entry.")
        beep("error")

    def _process_files(self, gen_path, html_path, review_mode=False):
        try:
            times      = parse_gen(gen_path)
            places     = calculate_places(times)
            asterisked = parse_html_asterisks(html_path) if html_path else set()
            empty_lanes = {i + 1 for i, t in enumerate(times) if t == ""}
            event_label, description = parse_html_race_info(html_path)

            self.event_label_var.set(event_label)
            self.desc_label_var.set(description)

            # Bring app to front so operator sees the result immediately
            self.wm_attributes("-topmost", True)
            self.lift()
            self.focus_force()
            if self._settings_win:
                self._settings_win.wm_attributes("-topmost", True)
                self._settings_win.lift()
                self._settings_win.focus_force()
                self.after(500, lambda: self._settings_win.wm_attributes("-topmost", False) if self._settings_win else None)
            self.after(500, lambda: self.wm_attributes("-topmost", False))

            # Reset all lane borders and button state before applying new state
            for i in range(4):
                self.lane_borders[i].config(highlightbackground=BG_BLACK, highlightthickness=1, bg=BG_BLACK)
                self.lane_labels[i].config(bg=BG_BLACK)
                self.lane_place_vars[i].set("")
            self.copied_label.config(text="")

            for i, t in enumerate(times):
                lane_num = i + 1
                is_asterisked = lane_num in asterisked
                is_empty      = t == ""

                if t:
                    display = formatted_to_display(t)
                    if is_asterisked:
                        display = display + "*"
                    self.lane_vars[i].set(display)
                    self.lane_labels[i].config(fg=ORANGE)
                    self.lane_sub[i].set("")
                    self.lane_place_vars[i].set(places[i] if i < len(places) else "")
                else:
                    self.lane_vars[i].set("--")
                    self.lane_labels[i].config(fg=DIM)
                    self.lane_sub[i].set("LANE EMPTY")
                    self.lane_place_vars[i].set("")

                # Border: red for asterisk, white for empty, none otherwise
                if is_asterisked:
                    # No red border — backup is non-blocking
                    self.lane_borders[i].config(highlightbackground=BG_BLACK, highlightthickness=1, bg=BG_BLACK)
                    self.lane_labels[i].config(bg=BG_BLACK)
                elif is_empty:
                    self.lane_borders[i].config(highlightbackground="#888888", highlightthickness=1, bg="#111111")
                    self.lane_labels[i].config(bg="#111111")
                else:
                    self.lane_borders[i].config(highlightbackground=BG_BLACK, highlightthickness=1, bg=BG_BLACK)
                    self.lane_labels[i].config(bg=BG_BLACK)

            self._pending_clip = format_clipboard(times)
            self.last_file_var.set(
                f"Last: {gen_path.name}  •  {datetime.now().strftime('%H:%M:%S')}")

            issues_title  = []
            issues_detail = []

            backup_lines = []
            empty_lines  = []
            if asterisked:
                for l in sorted(asterisked):
                    backup_lines.append(f"ℹ  Lane {l} — Backup time used — The Ref will be notified by the Timing Team.")
            if empty_lanes:
                for l in sorted(empty_lanes):
                    empty_lines.append(f"Lane {l} — EMPTY LANE — Please confirm no swimmer was present!")

            if review_mode:
                self._show_review_notice()
                self._setup_action_buttons(has_issues=bool(empty_lanes), html_path=html_path, review_mode=True)
            elif empty_lanes:
                # Blocking — orange warning, manual copy required
                warn_text = "\n".join(empty_lines)
                if backup_lines:
                    warn_text = "\n".join(backup_lines) + "\n\n" + warn_text
                self._show_warning(
                    "⚠ Empty lane(s) detected — please confirm before copying",
                    warn_text)
                self._setup_action_buttons(has_issues=True, html_path=html_path, review_mode=False)
                self.set_status("⚠ Manual review required — empty Lane(s) " +
                                ", ".join(str(l) for l in sorted(empty_lanes)))
                if self.config_data["sound_alerts"]:
                    beep("warning")
            elif asterisked:
                # Non-blocking — yellow info panel, auto-copy
                self._show_info("\n".join(backup_lines))
                self._setup_action_buttons(has_issues=False, html_path=html_path, review_mode=False)
                pyperclip.copy(self._pending_clip)
                self._on_copied()
                self.copied_label.config(text="")
                self.set_status("✅ Copied — backup time noted on Lane(s) " +
                                ", ".join(str(l) for l in sorted(asterisked)))
                if self.config_data["sound_alerts"]:
                    beep("info")
            else:
                self._hide_warning()
                self._setup_action_buttons(has_issues=False, html_path=html_path, review_mode=review_mode)
                pyperclip.copy(self._pending_clip)
                self._on_copied()
                self.copied_label.config(text="")
                self.set_status("✅ Parsed & copied — ready to paste")
                if self.config_data["sound_alerts"]:
                    beep("info")

            self._current_gen_name  = gen_path.name
            self._current_html_path = html_path
            if not review_mode:
                mark_processed(gen_path.name, html_path.name if html_path else "")
                self.processed.add(gen_path.name)
                self._update_confirmed_count()
                # If we're working through a reprocess queue, show Next button
                self._advance_queue_if_pending()
                # Alert if files arrived while we were processing
                self._check_waiting_queue()
            logging.info(
                f"{'Review' if review_mode else 'Processed'}: {gen_path.name} | "
                f"Times: {times} | Asterisked: {asterisked} | Empty: {empty_lanes}")

        except Exception as e:
            logging.exception(f"Error processing {gen_path.name}")
            self.set_status(f"❌ Parse error: {e}")

    def _set_waiting_state(self):
        """Show single greyed 'Waiting for files' box across all 4 button slots."""
        self.review_btn.grid_remove()
        self.copy_btn_single.grid_remove()
        self.fill_btn.grid_remove()
        self.entry_done_btn.grid_remove()
        self.copied_label.grid_remove()
        if not hasattr(self, '_waiting_btn'):
            self._waiting_btn = tk.Button(
                self.review_btn.master,
                text="⏳  Waiting for timing files to arrive…",
                font=(MONO, 12), bg="#1a1a1a", fg="#444444",
                relief="flat", padx=8, pady=14, state="disabled")
        self._waiting_btn.grid(row=0, column=0, columnspan=4, sticky="ew")

    def _clear_waiting_state(self):
        """Restore 3-button layout."""
        if hasattr(self, '_waiting_btn'):
            self._waiting_btn.grid_remove()
        self.review_btn.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        self.copy_btn_single.grid(row=0, column=1, sticky="ew", padx=2)
        self.fill_btn.grid(row=0, column=2, sticky="ew", padx=2)
        self.entry_done_btn.grid(row=0, column=3, sticky="ew", padx=(2, 0))
        self.copied_label.grid(row=1, column=0, columnspan=4, pady=(5, 0))

    def _setup_action_buttons(self, has_issues=False, html_path=None, review_mode=False):
        """Configure the 4 action buttons for current race state."""
        logging.info(f"_setup_action_buttons: has_issues={has_issues} html={html_path is not None} review={review_mode}")
        self._clear_waiting_state()
        self._current_html_path = html_path
        self._copied_once = False

        # HTML review — always enabled when html available
        if html_path:
            self.review_btn.config(state="normal",
                                   bg="#5a1a00" if has_issues else ORANGE_DIM)
        else:
            self.review_btn.config(state="disabled", bg=ORANGE_DIM)

        # Copy — always enabled
        self.copy_btn_single.config(state="normal", bg=ORANGE_DIM,
                                    activebackground=ORANGE,
                                    text="📋  COPY TO CLIPBOARD")

        # Fill Spreadsheet — enabled if configured and autofill on, disabled otherwise
        self._update_fill_btn_state()

        if review_mode:
            self.entry_done_btn.config(state="disabled", bg="#1a4a1a",
                                       fg="#446644", text="✅  ALREADY CONFIRMED",
                                       command=lambda: None)
            self.fill_btn.config(state="disabled")
        else:
            self.entry_done_btn.config(state="disabled", bg="#1a4a1a",
                                       fg="#446644", text="✅  ENTRY DONE",
                                       command=self.entry_done)

    def _update_fill_btn_state(self):
        """Show fill button as enabled, disabled-by-config, or disabled-no-path."""
        excel_path  = self.config_data.get("excel_path", "")
        autofill    = self.config_data.get("excel_autofill", True)
        if not excel_path:
            self.fill_btn.config(state="disabled", bg="#1a2a3a",
                                 text="📊  No spreadsheet configured",
                                 font=(MONO, 9))
        elif not autofill:
            self.fill_btn.config(state="disabled", bg="#1a2a3a",
                                 text="📊  Fill disabled in settings",
                                 font=(MONO, 9))
        else:
            self.fill_btn.config(state="normal", bg="#003a5c",
                                 text="📊  FILL SPREADSHEET",
                                 font=(MONO, 11, "bold"))

    def fill_spreadsheet_action(self):
        """Triggered by Fill Spreadsheet button."""
        excel_path = self.config_data.get("excel_path", "")
        if not excel_path:
            self.set_status("⚠ No spreadsheet configured — check Settings")
            return
        if not self._current_gen_name or self._pending_clip is None:
            self.set_status("⚠ No race data to fill")
            return
        # Get event number from current display
        event_label = self.event_label_var.get()  # e.g. "Event 2   Race 5"
        import re as _re
        m = _re.search(r'Event\s+(\d+)', event_label)
        if not m:
            self.set_status("⚠ Could not determine event number")
            return
        event_num = int(m.group(1))
        times     = self._pending_clip.split("	") if self._pending_clip else []
        # Pad to 4
        while len(times) < 4:
            times.append("")
        self.set_status(f"📊 Filling spreadsheet — Event {event_num}…")
        self.fill_btn.config(state="disabled", text="📊  Filling…")
        def do_fill():
            try:
                row = fill_spreadsheet(excel_path, event_num, times[:4])
                self.after(0, lambda: self._on_filled(event_num, row))
            except Exception as e:
                logging.exception("Excel fill error")
                self.after(0, lambda: self._on_fill_error(str(e)))
        threading.Thread(target=do_fill, daemon=True).start()

    def _on_filled(self, event_num, row):
        self.fill_btn.config(state="normal", bg="#1a5c1a",
                             text="📊  FILLED ✓ — CLICK TO RE-FILL",
                             font=(MONO, 10, "bold"))
        self.set_status(f"✅ Spreadsheet filled — Event {event_num} row {row}")
        self._on_copied()  # also enable Entry Done

    def _on_fill_error(self, msg):
        # COM errors can return None or unhelpful strings — use a fallback
        display = msg if msg and msg.strip() and msg != "None" else \
            "Could not access spreadsheet. Is it open and not read-only?"
        self.fill_btn.config(state="normal", bg="#5c1a00",
                             text="📊  FILL FAILED — RETRY",
                             font=(MONO, 10, "bold"))
        self.set_status(f"❌ Spreadsheet fill failed: {display}")
        beep("error")

    def _on_copied(self):
        """Called after any copy or fill — turn copy button green, enable Entry Done."""
        self._copied_once = True
        self.copy_btn_single.config(bg="#1a6e1a", activebackground="#22aa22",
                                    text="📋  COPIED — RE-COPY IF NEEDED")
        self.entry_done_btn.config(state="normal", bg="#226622", fg=WHITE,
                                   activebackground="#33aa33")

    def _show_split_buttons(self, html_path):
        """Kept for compatibility — now just calls _setup_action_buttons."""
        self._setup_action_buttons(has_issues=True, html_path=html_path)

    def open_html_review(self):
        """Open the companion HTML in the default browser."""
        if self._current_html_path and Path(self._current_html_path).exists():
            import webbrowser
            webbrowser.open(str(self._current_html_path))
        else:
            self.set_status("⚠ HTML file not found for review")

    def manual_copy(self):
        if self._pending_clip is not None:
            pyperclip.copy(self._pending_clip)
            self._on_copied()
            self.set_status("✅ Copied — ready to paste")

    def entry_done(self):
        """Mark current race as confirmed, update counter, unlock queue."""
        self._awaiting_entry_done = False
        self.entry_done_btn.config(state="disabled", bg="#1a4a1a", fg="#446644",
                                   text="✅  ENTRY DONE")
        if self._review_mode:
            self.set_status("✅ Review done — return to normal or review another")
            return
        if self._current_gen_name:
            mark_confirmed(self._current_gen_name)
            logging.info(f"Entry confirmed: {self._current_gen_name}")
        self._update_confirmed_count()
        self.review_prev_btn.config(state="normal", fg=ORANGE_DIM)
        self.set_status("✅ Entry confirmed — waiting for next file")
        self._process_next_in_queue()

    def set_status(self, msg):
        self.status_var.set(msg)
        self.update_idletasks()

    def on_close(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.destroy()

# ── Watchdog Handler ───────────────────────────────────────────────────────────
class GenFileHandler(FileSystemEventHandler):
    def __init__(self, app):
        self.app = app

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".gen"):
            self.app.after(0, lambda: self.app.on_gen_detected(event.src_path))

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ArenaLinkApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
