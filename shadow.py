"""יומן למידה: כל מועמד שנבדק (התקבל / נדחה ולמה) נרשם עם הנתונים בזמן ההחלטה. shadow_eval.py בודק אחר כך מה קרה לו."""
import csv
import os
from datetime import datetime

FILE = "shadow_log.csv"
COLS = ["date", "time_et", "ticker", "kind", "reason", "price", "entry", "stop", "target", "rsi", "mom", "tier",
        "analyst_mean", "upside_pct", "sector", "spy_chg_pct", "r5", "outcome"]


def log(kind, c, reason="", a=None, spy_chg=None, et=None):
    """kind: accepted | rej_analyst | rej_target | rej_earnings | rej_sector | not_picked."""
    now = et or datetime.now()
    day = f"{now:%Y-%m-%d}"
    rows = []
    if os.path.exists(FILE):
        with open(FILE, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    if any(r["date"] == day and r["ticker"] == c["ticker"] and r["kind"] == kind for r in rows):
        return
    a = a or c.get("analyst") or {}
    up = (a["target"] / c["entry"] - 1) * 100 if a.get("target") else ""
    new = {"date": day, "time_et": f"{now:%H:%M}", "ticker": c["ticker"], "kind": kind, "reason": reason[:120],
           "price": round(c["live"], 2), "entry": c["entry"], "stop": c["stop"], "target": c["target"],
           "rsi": round(c["rsi"], 1), "mom": round(c["mom"], 3), "tier": c["tier"],
           "analyst_mean": a.get("mean", ""), "upside_pct": round(up, 1) if up != "" else "",
           "sector": a.get("sector", ""), "spy_chg_pct": round(spy_chg * 100, 2) if spy_chg is not None else "",
           "r5": "", "outcome": ""}
    exists = os.path.exists(FILE)
    with open(FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if not exists:
            w.writeheader()
        w.writerow(new)
