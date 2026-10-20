"""Filter a Moodle iCal export into a clean deadline-only calendar for iCloud.

Usage:
  python filter.py --url "$MOODLE_URL" --out docs/<feed>.ics
  python filter.py --file export.ics --out test.ics
"""
import argparse
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

KEEP = re.compile(
    r"\bdue\b|\bcloses?\b|turnitin|quiz|submission|deadline|exam|\btest\b|"
    r"功課|作業|截止|繳交|測驗|考試",
    re.I,
)
STALE_DAYS = 365   # events not edited for over a year = copied from an old course
PAST_GRACE = timedelta(hours=12)
ALARMS = ["-P1D", "-PT3H"]


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def parse_events(text):
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            cur[key.split(";")[0]] = val
    return events


def ts(val):
    return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def course(ev):
    cat = ev.get("CATEGORIES", "")
    return cat.split("_")[0] if cat else ""


def keep(ev, now):
    try:
        start = ts(ev["DTSTART"])
    except (KeyError, ValueError):
        return False
    if start < now - PAST_GRACE:
        return False
    lm = ev.get("LAST-MODIFIED")
    if lm and ts(lm) < now - timedelta(days=STALE_DAYS):
        return False
    return bool(KEEP.search(ev.get("SUMMARY", "")))


def esc(s):
    return s.replace("\n", "\\n")


def build(events, now, warning=None):
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//moodle-calendar//EN",
        "METHOD:PUBLISH", "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:HKU Moodle Deadlines", "X-WR-TIMEZONE:Asia/Hong_Kong",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    for ev in sorted(events, key=lambda e: e["DTSTART"]):
        code = course(ev)
        summary = ev.get("SUMMARY", "").replace(" is due", " due")
        title = f"[{code}] {summary}" if code else summary
        out += ["BEGIN:VEVENT", f"UID:{ev.get('UID')}", f"DTSTAMP:{stamp}",
                f"DTSTART:{ev['DTSTART']}", f"DTEND:{ev.get('DTEND', ev['DTSTART'])}",
                f"SUMMARY:{title}"]
        if ev.get("DESCRIPTION", "").strip("\\n "):
            out.append(f"DESCRIPTION:{ev['DESCRIPTION']}")
        for trig in ALARMS:
            out += ["BEGIN:VALARM", "ACTION:DISPLAY",
                    f"DESCRIPTION:{esc(title)}", f"TRIGGER:{trig}", "END:VALARM"]
        out.append("END:VEVENT")
    if warning:
        day = (now + timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        out += ["BEGIN:VEVENT", "UID:sync-warning@moodle-calendar",
                f"DTSTAMP:{stamp}", f"DTSTART:{day}", f"DTEND:{day}",
                "SUMMARY:⚠️ Moodle sync failed - re-export calendar URL",
                f"DESCRIPTION:{esc(warning)}",
                "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Moodle sync failed",
                "TRIGGER:-PT0M", "END:VALARM", "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--file")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    try:
        if a.file:
            text = open(a.file, encoding="utf-8").read()
        else:
            req = urllib.request.Request(a.url, headers={"User-Agent": "Mozilla/5.0"})
            text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
        if "BEGIN:VCALENDAR" not in text:
            raise ValueError("Response is not an iCal file (token expired?)")
        events = [e for e in parse_events(text) if keep(e, now)]
        cal = build(events, now)
        print(f"Kept {len(events)} deadline(s)")
    except Exception as exc:  # keep the feed alive and tell the user
        cal = build([], now, warning=str(exc))
        print(f"Sync failed: {exc}", file=sys.stderr)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(cal)


if __name__ == "__main__":
    main()
