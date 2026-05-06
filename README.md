# ArenaLink v1.0

**Winsford Swim Team — Arena League Timing Data Capture**

ArenaLink watches a network share for timing system output files, parses race results, and automatically fills the Arena League scoring spreadsheet. Built for race-day use by non-technical volunteers.

---

## What It Does

1. Watches a network folder for new timing files (`.gen` + `.html`)
2. Parses lane times, finishing positions, and event details
3. Displays results in a clear GUI with lane-by-lane times
4. Auto-copies times to clipboard and fills the Excel spreadsheet
5. Queues files that arrive while you are confirming the previous race
6. Logs all processed and confirmed races locally

---

## Setup

### Requirements
- Windows 10/11
- Python 3.10+ installed and on PATH — download from [python.org](https://www.python.org/downloads/)
- The Arena League Excel spreadsheet placed in `arena_xlsx/`

> **Important — Python installation options:**
> During the Python installer, ensure the following are ticked:
> - **Add Python to PATH**
> - **tcl/tk and IDLE** — required for the ArenaLink graphical interface
>
> If ArenaLink fails with a `tkinter` error, re-run the Python installer, click **Modify**,
> and tick **tcl/tk and IDLE** under Optional Features. See Troubleshooting below for full steps.

### First Run
1. Double-click `ArenaLink.bat`
2. On first run the venv is created and dependencies installed automatically
3. Settings window opens — configure:
   - **Watch Folder**: path to the timing system network share (UNC or mapped drive)
   - **Team**: A Teams (Heat 1) or B Teams (Heat 2)
   - **Excel Spreadsheet Path**: browse to the `.xlsx` file in `arena_xlsx/`
   - **Auto-fill spreadsheet**: leave enabled for normal use
   - **Sound alerts**: leave enabled

### Desktop Shortcut
Right-click `ArenaLink.bat` and choose Send to > Desktop (create shortcut). To set the Winsford icon: right-click the shortcut, Properties, Change Icon, browse to `assets/arenalink.ico`.

---

## File Structure

```
WASC-Timing-ArenaLeague/
├── ArenaLink.py          # Main application
├── ArenaLink.bat         # Launch script (creates venv on first run)
├── requirements.txt      # Python dependencies
├── assets/
│   ├── logo.png          # Winsford logo
│   └── arenalink.ico     # Windows icon
├── arena_xlsx/           # Place spreadsheet here (gitignored)
│   └── .gitkeep
├── test_files/           # Generated test timing files
├── logs/                 # App and processed file logs (gitignored)
├── config.json           # Local settings (gitignored)
└── .gitignore
```

---

## Race Day Operation

### Normal Flow
1. Launch ArenaLink — it starts watching the configured folder
2. Open the Arena League spreadsheet in Excel (ensure no read-only warning)
3. When a timing file arrives, results display automatically and are copied to clipboard
4. Click **Fill Spreadsheet** to write directly to Excel
5. Eyeball the spreadsheet entry
6. Click **Entry Done** to confirm and unlock the next race

### If Files Queue Up
If a new file arrives before you confirm the current one, it queues automatically. An alert shows the count. After clicking Entry Done, the next file processes immediately.

### If ArenaLink Crashes
1. Restart ArenaLink
2. Click **Process Unprocessed Files** to catch up on any missed races
3. Work through them one by one as normal

### Reviewing a Previous Race
Click **Review a Previous File** at any time to reload and re-fill any previously processed race.

---

## Settings

| Setting | Description |
|---|---|
| Watch Folder | UNC path or mapped drive to the timing system share |
| Sound alerts | Audible beep on events (recommended: on) |
| Team | A Teams = Heat 1 files only, B Teams = Heat 2 files only |
| Excel Spreadsheet Path | Full path to the `.xlsx` scoring file |
| Auto-fill spreadsheet | Enables the Fill Spreadsheet button |
| Delete Processed Files Log | Resets the processed file history |

---

## File Naming Convention

The timing system outputs files in this format:

```
001-002-01F0003.gen
Event 002-01F (Race 0003).html
```

- `002` = Event number (matches spreadsheet EVENT 2)
- `01F` = Heat 1 (A Teams), `02F` = Heat 2 (B Teams)
- Race number increments globally across all events and heats

---

## Spreadsheet Integration

ArenaLink writes to the **Recording** sheet. It finds the correct row by scanning:
- Column B for `EVENT {n}` (e.g. `EVENT 2`)
- Column C for `TIME` within that event block

Times are written in MMSSHH format (e.g. `25744`) to columns D, E, F, G (Lanes 1-4).

The spreadsheet must be open and not in read-only mode when Fill Spreadsheet is clicked.

---

## Visual Indicators

| Display | Meaning |
|---|---|
| Green copy button | Copied — ready to paste or fill |
| Yellow panel | Backup time used — ref has been notified, no action needed |
| Orange panel | Empty lane detected — confirm before proceeding |
| `*` after time | Backup time was used for this lane |

---

## Troubleshooting

**App shakes when I press X** — a settings or review window is open. Close it first.

**Fill Spreadsheet fails: Sheet 'Recording' not found** — the spreadsheet tab has been renamed. Rename it back to exactly `Recording`.

**Files not being detected** — check the watch folder path in Settings. Ensure the network share is accessible and the correct team is selected.

**Times look wrong** — check `logs/app.log` for parse errors.

**ArenaLink won't start — `tkinter` or `_tkinter` error** — tkinter was not installed with Python. To fix:
1. Open Windows **Control Panel → Apps**, find your Python installation and click **Modify**
2. On the Optional Features screen, tick **tcl/tk and IDLE**
3. Complete the installation, then re-run `ArenaLink.bat`

Alternatively, re-run the Python installer from [python.org](https://www.python.org/downloads/) and tick **tcl/tk and IDLE** during setup.

---

## Dependencies

```
watchdog==4.0.1        File system monitoring
pyperclip==1.8.2       Clipboard access
beautifulsoup4==4.12.3 HTML parsing
Pillow==12.2.0         Logo image handling
pywin32==311           Windows integration
xlwings==0.33.14       Excel automation
```

---

## Changelog

### v1.0.3
- Fixed: scroll wheel now works in the "Review a Previous File" list
- Added: Python and tkinter checks in ArenaLink.bat with clear fix instructions if missing

### v1.0 — Production Release
- Improved error message when Excel Recording sheet is renamed
- Version number displayed bold
- Lane time and position label spacing tightened
- Queue race condition fixed — files now gate immediately on detection

### v0.8.x — Excel Integration
- v0.8.9 Waiting box full width, time/position spacing, bold version
- v0.8.8 Queue race condition fix
- v0.8.7 Queue fix with awaiting entry done flag
- v0.8.6 Separator lines between UI sections
- v0.8.5 Waiting button columnspan fix
- v0.8.4 INFO_BG constant fix, review window shake fix
- v0.8.3 Asterisk now non-blocking with yellow info panel
- v0.8.2 Team radio button default, emoji rendering fix
- v0.8.1 Excel fill logic for real spreadsheet layout
- v0.8.0 Excel Fill Spreadsheet button, xlwings, pywin32

### v0.7.x — A/B Teams
- v0.7.1 Team radio button default to A
- v0.7.0 Settings window sizing fix
- v0.6.9 A/B Teams setting, heat number filter, team label display

### v0.6.x — Queue, Review and Logging
- v0.6.8 Title centred with place(), fixed header height
- v0.6.7 Bottom row dynamic 2/3 button layout
- v0.6.6 Review mode blue notice panel
- v0.6.5 Settings save bug fix, clean race green button fix
- v0.6.4 Dynamic window height for warnings
- v0.6.3 Review mode log write fixed, Exit Review button
- v0.6.2 Places calculated from 4 displayed lanes
- v0.6.1 Finishing positions, waiting state, review mode
- v0.6.0 Entry Done flow, confirmed counter, Review a Previous File, rich log format

### v0.5.x — Polish and Reliability
- v0.5.10 Settings window brought to front on file process
- v0.5.8 Settings dim overlay, shake on blocked close
- v0.5.5 Clipboard re-copy, green button stays enabled
- v0.5.4 Sound via winsound.Beep (bypasses Windows sound scheme)
- v0.5.1 Dynamic window height, delete log in settings
- v0.5.0 Fixed window size, lane columns fixed width

### v0.4.x — Core Functionality
- v0.4.8 Lane border indicators, asterisk suffix on time
- v0.4.7 Open and Review HTML button
- v0.4.6 Leading zero stripped from display times
- v0.4.5 parse_gen row position equals lane number fix
- v0.4.3 parse_gen rewritten, reprocess queue, taskbar icon
- v0.4.2 Race info display, filename matching fix
- v0.4.1 Logo loading fixed
- v0.4.0 ArenaLink branding, orange/black theme, Winsford logo

### v0.1–v0.3 — Foundation
- Network share folder watcher using PollingObserver
- HTML and GEN file parsing
- Clipboard copy with tab-separated lane times
- Settings with watch folder and sound alerts
- Processed file log and first-run setup
- Combined bat file for setup and launch
