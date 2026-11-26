"""Step 2: poll TfL every N minutes and store each disruption with the time we FIRST saw it.

Setup:  pip install requests
Run:    python step2_poll_tfl.py            (leave it running; Ctrl+C to stop)
        python step2_poll_tfl.py --once     (single poll, for GitHub Actions)
Output: disruptions.db (SQLite). Look at it with DB Browser for SQLite, or:
        python step2_poll_tfl.py --export   -> disruptions.csv
"""
import csv
import hashlib
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

try:  # use the Windows/macOS certificate store (fixes "self-signed certificate in chain" behind antivirus/proxy)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

BASE = "https://api.tfl.gov.uk"
MODES = "tube,elizabeth-line,dlr,overground,tram,bus,national-rail,river-bus,cable-car"
POLL_SECONDS = 120
DB = "disruptions.db"

ONCE = "--once" in sys.argv  # one poll then exit (used by GitHub Actions)
db = sqlite3.connect(DB)
db.execute("""CREATE TABLE IF NOT EXISTS disruptions (
    key TEXT PRIMARY KEY, first_seen_utc TEXT, last_seen_utc TEXT, ended_utc TEXT,
    line TEXT, mode TEXT, severity TEXT, category TEXT, tfl_created TEXT, description TEXT)""")
db.commit()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect():
    """Return a list of dicts: one per non-'Good Service' line status."""
    out = []
    lines = requests.get(f"{BASE}/Line/Mode/{MODES}/Status", timeout=30).json()
    for ln in lines:
        for st in ln["lineStatuses"]:
            if st["statusSeverityDescription"] == "Good Service":
                continue
            desc = (st.get("reason") or "").strip()
            key = hashlib.sha1(f'{ln["id"]}|{st["statusSeverityDescription"]}|{desc}'.encode()).hexdigest()[:16]
            out.append(dict(key=key, line=ln["name"], mode=ln.get("modeName", ""), severity=st["statusSeverityDescription"],
                            category=st.get("disruption", {}).get("category", ""),
                            created=st.get("created", ""), desc=desc))
    return out


def export():
    from zoneinfo import ZoneInfo
    rows = db.execute("SELECT * FROM disruptions ORDER BY first_seen_utc").fetchall()
    with open("disruptions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([c[1] for c in db.execute("PRAGMA table_info(disruptions)")] + ["first_seen_london"])
        for r in rows:
            lon = datetime.fromisoformat(r[1]).astimezone(ZoneInfo("Europe/London")).strftime("%Y-%m-%d %H:%M")
            w.writerow(list(r) + [lon])
    print("Wrote disruptions.csv with", len(rows), "rows")


if "--export" in sys.argv:
    export()
    sys.exit()

print("Polling every", POLL_SECONDS, "s. Ctrl+C to stop." if not ONCE else "Single run.")
while True:
    try:
        t = now()
        current = collect()
        seen = {d["key"] for d in current}
        for d in current:
            if ONCE:  # cloud mode: don't rewrite the row on every run (keeps git history small)
                exists = db.execute("SELECT 1 FROM disruptions WHERE key=?", (d["key"],)).fetchone()
                if exists:
                    db.execute("UPDATE disruptions SET ended_utc=NULL WHERE key=? AND ended_utc IS NOT NULL", (d["key"],))
                updated = 1 if exists else 0
            else:
                updated = db.execute("UPDATE disruptions SET last_seen_utc=?, ended_utc=NULL WHERE key=?",
                                     (t, d["key"])).rowcount
            if updated == 0:
                db.execute("INSERT INTO disruptions VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (d["key"], t, t, None, d["line"], d["mode"], d["severity"], d["category"], d["created"], d["desc"]))
                print(t, "NEW:", d["line"], "-", d["severity"], "|", d["desc"][:100])
        # mark disruptions that disappeared
        for (k,) in db.execute("SELECT key FROM disruptions WHERE ended_utc IS NULL").fetchall():
            if k not in seen:
                db.execute("UPDATE disruptions SET ended_utc=? WHERE key=?", (t, k))
        db.commit()
        if ONCE:
            export()
    except Exception as e:  # network hiccup: log and keep going
        print(now(), "error:", e)
    if ONCE:
        break
    time.sleep(POLL_SECONDS)
