"""בודק מול Yahoo מה האנליסטים אומרים על ההוראות הפעילות. כותב analyst_report.txt."""
import csv

import analysts

rows = []
with open("signals_log.csv", newline="", encoding="utf-8") as f:
    rows = [r for r in csv.DictReader(f) if r["status"] in ("pending", "open")]
lines = ["בדיקת אנליסטים להוראות פעילות (מקור: Yahoo Finance)"]
ok = missing = rejected = 0
for r in rows:
    a = analysts.get_analyst(r["ticker"])
    close = float(r["entry"])
    verdict = "עובר" if analysts.passes(a, close) else "נפסל"
    if a is None or a["n"] < 5:
        missing += 1
    elif verdict == "עובר":
        ok += 1
    else:
        rejected += 1
    lines.append(f"{r['ticker']}: {analysts.describe(a, close)} -> {verdict}")
lines.append(f"סיכום: עברו {ok}, נפסלו {rejected}, אין נתונים {missing}")
open("analyst_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
