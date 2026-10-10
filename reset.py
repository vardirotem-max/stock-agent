"""איפוס חד-פעמי: מבטל את כל ההוראות הפתוחות בחשבון הדמה ומארכב את לוג הסיגנלים. לא סוגר פוזיציות."""
import csv
import datetime as dt
import os
import time

import broker
from scanner import FIELDS

lines = []
r = broker._req("DELETE", "/v2/orders")
lines.append(f"cancel_all_http={r.status_code}")
time.sleep(5)
o = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100, "nested": "true"})
open_orders = o.json() if o.ok else []
p = broker._req("GET", "/v2/positions")
positions = p.json() if p.ok else []
lines.append(f"open_orders_after={len(open_orders)}")
lines.append(f"open_positions={len(positions)}")
if os.path.exists("signals_log.csv"):
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    os.replace("signals_log.csv", f"signals_log_archive_{day}.csv")
    lines.append(f"log_archived_to=signals_log_archive_{day}.csv")
with open("signals_log.csv", "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(FIELDS)
lines.append("fresh_log=ok")
open("reset_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
