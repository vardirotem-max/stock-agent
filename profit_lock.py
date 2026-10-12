"""נעילת רווח יומי: אם הרווח היומי של החשבון הגיע ליעד, סוגרים את כל הפוזיציות ומבטלים את כל ההוראות הפתוחות.

רץ כל 10 דקות בשעות המסחר (workflow). DRY=1: מדפיס בלבד.
הרווח היומי = שווי החשבון עכשיו פחות שווי הסגירה הקודמת (כולל ממומש ולא ממומש).
"""
import os
import sys
import time

import broker
import config as C
import state as st
from notify import send_telegram
from scanner import OPEN, load_log, reconcile_actuals, save_log

DRY = os.getenv("DRY") == "1"
FORCE = os.getenv("FORCE_TEST") == "1"  # בדיקה: מתעלם מהיעד (רק עם DRY=1)
L = []


def out(s):
    print(s)
    L.append(s)


def main():
    if not broker.enabled():
        sys.exit("אין מפתחות Alpaca")
    clock = broker._req("GET", "/v2/clock").json()
    if not clock.get("is_open"):
        out("השוק סגור.")
        return
    day = clock["timestamp"][:10]
    state = st.load()
    acc = broker._req("GET", "/v2/account").json()
    equity, last_eq = float(acc["equity"]), float(acc["last_equity"])
    day_pl = equity - last_eq
    out(f"{day}: שווי {equity:,.2f}$, רווח יומי {day_pl:+,.2f}$ (יעד {C.DAILY_PROFIT_TARGET:,.0f}$)")
    if state.get("locked_on") == day:
        out("כבר ננעל היום.")
        return
    if day_pl < C.DAILY_PROFIT_TARGET and not (DRY and FORCE):
        out("היעד לא הושג.")
        return

    pos = broker._req("GET", "/v2/positions").json()
    orders = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 200, "nested": "false"}).json()
    out(f"יעד הושג. פוזיציות לסגירה: {len(pos)} ({', '.join(p['symbol'] for p in pos)}), הוראות פתוחות לביטול: {len(orders)}")
    if DRY:
        out("DRY: לא בוצעה פעולה.")
        return

    # סוגרים הכל: מבטלים את כל ההוראות ואז מוכרים את הפוזיציות
    r = broker._req("DELETE", "/v2/positions", params={"cancel_orders": "true"})
    out(f"סגירת פוזיציות: HTTP {r.status_code}")
    if r.status_code not in (200, 207):
        send_telegram(f"⚠️ נעילת רווח יומי נכשלה: HTTP {r.status_code} {r.text[:150]}")
        sys.exit(1)
    time.sleep(8)
    left = broker._req("GET", "/v2/positions").json()
    if left:
        send_telegram(f"⚠️ נעילת רווח: נשארו {len(left)} פוזיציות פתוחות ({', '.join(p['symbol'] for p in left)}). בדוק ב-Alpaca.")

    # עדכון הלוג כדי שהסימולציה לא תמשיך לנהל עסקאות שנסגרו
    rows = load_log()
    for row in rows:
        oid = row.get("order_id") or ""
        if row["status"] not in OPEN or oid in ("", "skipped"):
            continue
        try:
            o = broker.get_order(oid)
        except Exception as e:
            out(f"לוג {row['ticker']}: {e}")
            continue
        row["status"] = "timeout" if o.get("filled_avg_price") else "expired"
        row["broker_done"] = "1"
    reconcile_actuals(rows)
    save_log(rows)

    state["locked_on"] = day
    st.save(state)
    after = broker._req("GET", "/v2/account").json()
    send_telegram(
        f"🔒 נעילת רווח יומי: הרווח היומי הגיע ל-{day_pl:+,.2f}$ (יעד {C.DAILY_PROFIT_TARGET:,.0f}$).\n"
        f"נסגרו {len(pos)} פוזיציות ובוטלו {len(orders)} הוראות פתוחות (כולל קניות ממתינות).\n"
        f"שווי החשבון: {float(after['equity']):,.2f}$, מזומן {float(after['cash']):,.2f}$.\n"
        "הבוט ימשיך לשלוח סיגנלים חדשים בסריקה הבאה.\nמסחר דמה בלבד."
    )


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        out("שגיאה:\n" + traceback.format_exc())
        send_telegram("⚠️ נעילת רווח יומי: שגיאה בהרצה, ראה את ה-Actions.")
        sys.exit(1)
    finally:
        open("profit_lock_report.txt", "w", encoding="utf-8").write("\n".join(L) + "\n")
