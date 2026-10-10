"""איפוס חד-פעמי: מבטל את כל ההוראות הפתוחות בחשבון הדמה ומארכב את לוג הסיגנלים."""
import datetime as dt
import os
import shutil
import sys

import broker
from notify import send_telegram

if not broker.enabled():
    print("אין מפתחות Alpaca")
    sys.exit(1)

lines = []
pos = broker._req("GET", "/v2/positions")
n_pos = len(pos.json()) if pos.ok else -1
lines.append(f"פוזיציות פתוחות: {n_pos} (לא נסגרות באיפוס)")

r = broker._req("DELETE", "/v2/orders")
if r.status_code in (200, 207):
    res = r.json()
    ok = sum(1 for x in res if str(x.get("status")) in ("200", "204"))
    lines.append(f"בוטלו {ok} הוראות מתוך {len(res)} שנמצאו")
elif r.status_code == 204:
    lines.append("לא היו הוראות פתוחות")
else:
    lines.append(f"שגיאה בביטול: {r.status_code} {r.text[:150]}")
    open("reset_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    send_telegram("⚠️ האיפוס נכשל בביטול הוראות. לא בוצעה סריקה חדשה.\n" + "\n".join(lines))
    sys.exit(1)

left = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100})
lines.append(f"הוראות פתוחות אחרי הביטול: {len(left.json()) if left.ok else '?'}")

if os.path.exists("signals_log.csv"):
    name = f"signals_log_archive_{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    shutil.move("signals_log.csv", name)
    lines.append(f"הלוג הישן נשמר בארכיון: {name}")

open("reset_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
send_telegram("🧹 איפוס מסחר הדמה\n" + "\n".join(lines) + "\nמריץ עכשיו סריקה חדשה.")
