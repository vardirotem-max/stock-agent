"""מחיל את תקרת הרווח לפוזיציה (POSITION_PROFIT_CAP) על כל הפוזיציות הפתוחות.

לכל פוזיציה: מחיר יעד = כניסה + תקרה/כמות. אם המחיר הנוכחי כבר שם או מעליו: סוגרים מיד בשוק.
אחרת: מורידים את הוראת היעד (limit sell) של הפוזיציה למחיר הזה, כך ש-Alpaca עצמה מוכרת ברגע שהמחיר מגיע אליו.
DRY=1: מדפיס בלבד.
"""
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
    cap = float(C.POSITION_PROFIT_CAP or 0)
    if cap <= 0:
        out("התקרה כבויה.")
        return
    pos = broker._req("GET", "/v2/positions").json()
    clock = broker._req("GET", "/v2/clock").json()
    closed, changed = [], []
    for p in pos:
        sym, qty = p["symbol"], float(p["qty"])
        entry, cur, upl = float(p["avg_entry_price"]), float(p["current_price"]), float(p["unrealized_pl"])
        cap_px = broker.profit_cap_price(entry, qty)
        orders = broker._req("GET", "/v2/orders", params={"status": "open", "symbols": sym, "limit": 50, "nested": "false"}).json()
        tp = next((o for o in orders if o["side"] == "sell" and o["type"] == "limit"), None)
        tp_px = float(tp["limit_price"]) if tp else None
        out(f"{sym}: {qty:g} @ {entry:.2f} עכשיו {cur:.2f} P/L {upl:+.2f}$ | תקרה {cap_px} | יעד נוכחי {tp_px}")
        if upl >= cap and clock.get("is_open"):
            out("  -> הרווח כבר מעל התקרה: סוגר בשוק")
            if not DRY:
                for o in orders:
                    broker._req("DELETE", f"/v2/orders/{o['id']}")
                time.sleep(2)
                r = broker._req("DELETE", f"/v2/positions/{sym}")
                out(f"  סגירה HTTP {r.status_code}")
                if r.status_code in (200, 207):
                    closed.append((sym, upl))
            continue
        if tp and (tp_px is None or cap_px < tp_px):
            out(f"  -> מוריד את היעד ל-{cap_px}")
            if not DRY:
                r = broker._req("PATCH", f"/v2/orders/{tp['id']}", json={"limit_price": f"{cap_px:.2f}"})
                out(f"  עדכון HTTP {r.status_code} {'' if r.ok else r.text[:150]}")
                if r.ok:
                    changed.append((sym, cap_px))
        elif not tp:
            out("  ! אין הוראת יעד פעילה לפוזיציה הזו")
    if DRY:
        return
    rows = load_log()
    for row in rows:
        oid = row.get("order_id") or ""
        for sym, px in changed:
            if row["ticker"] == sym and row["status"] in OPEN:
                row["target"] = px
        if row["ticker"] in {c[0] for c in closed} and row["status"] in OPEN and oid not in ("", "skipped"):
            row["status"], row["broker_done"] = "timeout", "1"
    reconcile_actuals(rows)
    save_log(rows)
    if closed:
        lines = ["💰 תקרת רווח הופעלה - נסגרו:"] + [f"🟢 {s}: {u:+,.2f}$" for s, u in closed]
        send_telegram("\n".join(lines))


if __name__ == "__main__":
    try:
        main()
    finally:
        open("profit_cap_report.txt", "w", encoding="utf-8").write("\n".join(L) + "\n")
