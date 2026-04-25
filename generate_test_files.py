"""
Arena League Test File Generator — Enhanced
Generates 33 events x 2 heats (A=Heat01, B=Heat02) = 66 pairs of .gen + .html files.

Realistic variation:
  - Different times per race (varied by event type/distance)
  - Random finishing order
  - ~30% chance of one DNS lane per race
  - ~20% chance of one backup time (asterisk) per race
  - Mix of event types (50m, 100m, 200m, relay)
  - Male/Female/Mixed alternating per heat
"""

import random
import os
from pathlib import Path

random.seed(42)  # reproducible but varied

OUTPUT_DIR = Path(__file__).parent / "test_files"
EVENTS     = 33
DNS_PROB   = 0.30   # probability of one DNS lane per race
BACKUP_PROB = 0.20  # probability of one backup time per race

# ── Event definitions ──────────────────────────────────────────────────────────
EVENT_TYPES = [
    # (description_template, distance_m, is_relay, min_secs, max_secs)
    ("9 Yrs/Over 50m Freestyle",          50,  False, 28,  45),
    ("9 Yrs/Over 100m Freestyle",         100, False, 62,  95),
    ("9 Yrs/Over 200m Individual Medley", 200, False, 140, 200),
    ("9 Yrs/Over 50m Breaststroke",       50,  False, 35,  55),
    ("9 Yrs/Over 100m Breaststroke",      100, False, 75,  110),
    ("9 Yrs/Over 50m Backstroke",         50,  False, 32,  50),
    ("9 Yrs/Over 100m Backstroke",        100, False, 68,  100),
    ("9 Yrs/Over 50m Butterfly",          50,  False, 30,  48),
    ("9/10 Yrs Freestyle Relay",          None, True, 55,  80),
    ("11 Years Medley Relay",             None, True, 65,  90),
    ("12 Years Freestyle Relay",          None, True, 58,  85),
]

GENDERS = ["Male/Open", "Female", "Mixed"]

def random_time_seconds(min_s, max_s):
    """Return a random float time in seconds, realistic hundredths."""
    secs = random.uniform(min_s, max_s)
    # Round to nearest hundredth
    return round(secs, 2)

def seconds_to_gen_splits(total_secs, distance, is_relay):
    """Generate plausible split times for a given total and distance."""
    if is_relay or distance is None:
        # Single split = finish time
        backup = round(total_secs + random.uniform(-0.5, 0.5), 2)
        return [total_secs, backup]
    elif distance == 50:
        backup = round(total_secs + random.uniform(-0.3, 0.3), 2)
        return [total_secs, backup]
    elif distance == 100:
        split1 = round(total_secs * random.uniform(0.46, 0.50), 2)
        backup = round(total_secs + random.uniform(-0.3, 0.3), 2)
        return [split1, total_secs, backup]
    elif distance == 200:
        # 4 x 50m splits
        s1 = round(total_secs * random.uniform(0.22, 0.26), 2)
        s2 = round(total_secs * random.uniform(0.47, 0.52), 2)
        s3 = round(total_secs * random.uniform(0.73, 0.78), 2)
        backup = round(total_secs + random.uniform(-0.3, 0.3), 2)
        return [s1, s2, s3, total_secs, backup]
    return [total_secs]

def format_time_display(secs):
    """162.16 → '02:42.16' for HTML display."""
    mins = int(secs // 60)
    remaining = secs - mins * 60
    s = int(remaining)
    h = round((remaining - s) * 100)
    return f"{mins:02d}:{s:02d}.{h:02d}"

def generate_race(event_num, heat_num, race_num, event_type):
    """Generate .gen content and metadata for one race."""
    desc, distance, is_relay, min_s, max_s = event_type

    # Decide DNS and backup lanes
    dns_lane    = random.randint(1, 4) if random.random() < DNS_PROB else None
    backup_lane = random.randint(1, 4) if random.random() < BACKUP_PROB else None
    if backup_lane == dns_lane:
        backup_lane = None

    # Generate times for active lanes
    active_lanes = [l for l in range(1, 5) if l != dns_lane]
    raw_times = {l: random_time_seconds(min_s, max_s) for l in active_lanes}

    # Assign finish places by time (fastest = 1st)
    sorted_lanes = sorted(active_lanes, key=lambda l: raw_times[l])
    places = {l: sorted_lanes.index(l) + 1 for l in active_lanes}

    # Build .gen lines
    gen_header = f"1;{heat_num};4;F\n"
    gen_lines  = []
    for lane in range(1, 5):
        if lane == dns_lane:
            gen_lines.append("0;;;;;;;;")
            continue
        t = raw_times[lane]
        splits = seconds_to_gen_splits(t, distance, is_relay)
        place  = places[lane]
        # Format: place;split1;...;finish;backup;;;
        # For backup lane, add a slightly different backup
        if lane == backup_lane:
            backup_t = round(t + random.uniform(0.1, 2.0), 2)
            splits[-1] = backup_t
        parts = [str(place)] + [str(s) for s in splits]
        # Pad to 8 semicolons total
        while len(parts) < 9:
            parts.append("")
        gen_lines.append(";".join(parts[:9]))

    gen_content = gen_header + "\n".join(gen_lines) + "\n"

    return gen_content, raw_times, places, dns_lane, backup_lane, is_relay

def generate_html(event_num, heat_num, race_num, desc, gender,
                  raw_times, places, dns_lane, backup_lane):
    """Generate HTML content for one race."""
    # Finish order string (lanes sorted by place)
    active = [(l, p) for l, p in places.items()]
    finish_order = " ".join(str(l) for l, _ in sorted(active, key=lambda x: x[1]))

    # Build lane rows for "Finish By Lane" table
    lane_rows = ""
    for lane in range(1, 7):  # HTML shows 6 lanes
        if lane > 4:
            lane_rows += f"<td> {lane} </td><td></td><td></td><td></td><td></td><td></td>"
            continue
        if lane == dns_lane:
            lane_rows += f"<td> {lane} </td><td></td><td></td><td></td><td></td><td>Expecting 1 Buttons</td>"
            continue
        t    = raw_times[lane]
        disp = format_time_display(t)
        p    = places[lane]
        is_bk = lane == backup_lane
        star = "*" if is_bk else " "
        # backup time slightly different if backup lane
        bk_t  = round(t + random.uniform(0.1, 2.0), 2) if is_bk else t
        bk_d  = format_time_display(bk_t)
        bk_note = f"Backup Diff :{abs(t - bk_t):.2f}" if is_bk else ""
        lane_rows += (f"<td> {lane}{star}</td><td> {p}</td>"
                      f"<td>{disp}</td><td>{bk_d}</td><td>{bk_d}</td>"
                      f"<td>{bk_note}</td>")

    html = f"""<html><head><title>Superior Swim Timing</title>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
</head><body bgcolor="white">
<h1> Event {event_num}   Heat  {heat_num}   Race {race_num}</h1>
<p>Event Start Saturday, April 11, 2026 12:47:22 PM BST<p>
<p>Heat Start Saturday, April 11, 2026 1:28:53 PM BST</p>
<h2>{gender} {desc}</h2>
<h2>Finish Order: {finish_order}</h2>
<h3>Finish By Lane</h3>
<table border='1'><tr>
<th>LANE</th><th>PLACE</th><th>TIME</th><th>BACKUP</th><th>BUTTON1</th></tr><tr>
{lane_rows}</table>
</body></html>
"""
    return html

# ── Main generator ──────────────────────────────────────────────────────────────
def generate():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    race_num = 1
    stats = {"dns": 0, "backup": 0, "clean": 0}

    # Cycle through event types across 33 events
    for event in range(1, EVENTS + 1):
        event_type = EVENT_TYPES[(event - 1) % len(EVENT_TYPES)]
        desc       = event_type[0]

        for heat in range(1, 3):
            # Alternate gender per heat and event
            gender_idx = (event + heat) % len(GENDERS)
            gender     = GENDERS[gender_idx]

            event_str = f"{event:03d}"
            heat_str  = f"{heat:02d}"
            race_str  = f"{race_num:04d}"

            gen_content, raw_times, places, dns_lane, backup_lane, is_relay = \
                generate_race(event, heat, race_num, event_type)

            html_content = generate_html(
                event, heat, race_num, desc, gender,
                raw_times, places, dns_lane, backup_lane)

            gen_name  = f"001-{event_str}-{heat_str}F{race_str}.gen"
            html_name = f"Event {event_str}-{heat_str}F (Race {race_str}).html"

            (OUTPUT_DIR / gen_name).write_text(gen_content)
            (OUTPUT_DIR / html_name).write_text(html_content)

            team = "A Teams" if heat == 1 else "B Teams"
            flags = []
            if dns_lane:
                flags.append(f"DNS Lane {dns_lane}")
                stats["dns"] += 1
            if backup_lane:
                flags.append(f"Backup Lane {backup_lane}")
                stats["backup"] += 1
            if not flags:
                stats["clean"] += 1
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            print(f"  Event {event:02d} {team} Race {race_str} — {gender} {desc[:30]}{flag_str}")

            race_num += 1

    total = EVENTS * 2
    print(f"\n✅ Generated {total} pairs in: {OUTPUT_DIR}")
    print(f"   Clean: {stats['clean']}  |  DNS: {stats['dns']}  |  Backup: {stats['backup']}")

if __name__ == "__main__":
    print(f"Generating Arena League test files — {EVENTS} events x 2 heats...\n")
    generate()
