"""סוגר רק את הפוזיציות שברווח (רווח לא ממומש > 0) ומשאיר את אלה שבהפסד עם הסטופ והיעד שלהן."""
import os
import sys
import time

import broker
import config as C
from notify import send_telegram
from scanner import OPEN, load_log, reconcile_actuals, save_log

DRY = os.getenv("DRY") == "1"
L = []


def out(s):
    print(s)
    L.append(s)


def main():
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        out("השוק סגור - לא מבצע.")
        return
    pos = broker._req("GET", "/v2/positions").json()
    pos = [p for p in pos if p["symbol"] not in C.CORE_SYMBOLS]
    win = [p for p in pos if float(p["unrealized_pl"]) > 0]
    keep = [p for p in pos if float(p["unrealized_pl"]) <= 0]
    for p in pos:
        out(f"{p['symbol']}: {p['qty']} מניות | כניסה {float(p['avg_entry_price']):.2f} עכשיו {float(p['current_price']):.2f} | P/L {float(p['unrealized_pl']):+.2f}$")
    out(f"לסגירה (ברווח): {[p['symbol'] for p in win]} | נשארות (בהפסד): {[p['symbol'] for p in keep]}")
    if DRY or not win:
        return
    closed = []
    for p in win:
        sym = p["symbol"]
        # מבטלים קודם את הוראות הסטופ/יעד של הסימבול (הן מחזיקות את המניות), ואז מוכרים בשוק
        for o in broker._req("GET", "/v2/orders", params={"status": "open", "symbols": sym, "limit": 50, "nested": "false"}).json():
            broker._req("DELETE", f"/v2/orders/{o['id']}")
        time.sleep(2)
        r = broker._req("DELETE", f"/v2/positions/{sym}")
        out(f"{sym}: סגירה HTTP {r.status_code}")
        if r.status_code in (200, 207):
            closed.append((sym, float(p["unrealized_pl"]), float(p["unrealized_plpc"]) * 100))
        else:
            out(f"  שגיאה: {r.text[:150]}")
    time.sleep(6)
    rows = load_log()
    names = {c[0] for c in closed}
    for row in rows:
        oid = row.get("order_id") or ""
        if row["ticker"] in names and row["status"] in OPEN and oid not in ("", "skipped"):
            row["status"], row["broker_done"] = "timeout", "1"
    reconcile_actuals(rows)
    save_log(rows)
    acc = broker._req("GET", "/v2/account").json()
    total = sum(c[1] for c in closed)
    lines = ["💰 מימוש רווחים", ""]
    lines += [f"🟢 {s}: {u:+,.2f}$ ({pc:+.1f}%)" for s, u, pc in closed]
    lines += ["", f"סה\"כ רווח שמומש (לפני עמלות והחלקה): {total:+,.2f}$"]
    if keep:
        lines += ["", "נשארו פתוחות (בהפסד, עם סטופ ויעד):"]
        lines += [f"🔴 {p['symbol']}: {float(p['unrealized_pl']):+,.2f}$" for p in keep]
    lines += ["", f"📈 שווי החשבון: {float(acc['equity']):,.2f}$ | מזומן {float(acc['cash']):,.2f}$", "", "מסחר דמה בלבד."]
    send_telegram("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    finally:
        open("close_winners_report.txt", "w", encoding="utf-8").write("\n".join(L) + "\n")
