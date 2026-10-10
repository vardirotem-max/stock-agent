"""בדיקת הגנה לפי דרישה: האם לכל הוראה פעילה בחשבון הדמה יש יעד (מכירה בלימיט) וסטופ במחירים הנכונים."""
import csv
import os
import sys

import broker
from notify import send_telegram


def check_row(r):
    o = broker.get_order(r["order_id"])
    legs = o.get("legs") or []
    tp = [l for l in legs if l["side"] == "sell" and l["type"] == "limit"]
    sl = [l for l in legs if l["side"] == "sell" and l["type"] in ("stop", "stop_limit")]
    issues = []
    if o.get("order_class") != "bracket":
        issues.append("לא Bracket")
    if o.get("limit_price") is None or abs(float(o["limit_price"]) - float(r["entry"])) > 0.005:
        issues.append("מחיר כניסה שונה")
    if not tp:
        issues.append("חסר יעד")
    elif abs(float(tp[0]["limit_price"]) - float(r["target"])) > 0.005:
        issues.append("יעד שונה")
    if not sl:
        issues.append("חסר סטופ")
    elif abs(float(sl[0]["stop_price"]) - float(r["stop"])) > 0.005:
        issues.append("סטופ שונה")
    tp_p = tp[0]["limit_price"] if tp else "-"
    sl_p = sl[0]["stop_price"] if sl else "-"
    return o["status"], tp_p, sl_p, issues


def main():
    if not broker.enabled():
        print("אין מפתחות Alpaca")
        sys.exit(1)
    rows = []
    if os.path.exists("signals_log.csv"):
        with open("signals_log.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    lines, bad, n = ["🔍 בדיקת הגנה - חשבון הדמה"], 0, 0
    for r in rows:
        oid = r.get("order_id") or ""
        if oid in ("", "skipped") or r["status"] in ("target", "stopped", "timeout", "expired"):
            continue
        n += 1
        try:
            status, tp, sl, issues = check_row(r)
        except Exception as e:
            issues, status, tp, sl = [f"שגיאה: {str(e)[:60]}"], "?", "-", "-"
        bad += bool(issues)
        mark = "✅" if not issues else "❌ " + ", ".join(issues)
        lines.append(f"{r['ticker']}: {status} | כניסה {r['entry']} | יעד {tp} | סטופ {sl} {mark}")
    problems, n_pos = broker.audit()
    lines += problems
    lines.append(f"נבדקו {n} הוראות פעילות, {n_pos} פוזיציות פתוחות. " + ("הכל תקין ✅" if not bad and not problems else "יש בעיות ⚠️"))
    text = "\n".join(lines)
    print(text)
    send_telegram(text)


if __name__ == "__main__":
    main()
