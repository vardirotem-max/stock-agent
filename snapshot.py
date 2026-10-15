"""תמונת מצב של החשבון לקובץ JSON (משמש את דף ה-Dashboard): יתרה, פוזיציות, הוראות ממתינות, עקומת שווי מול SPY."""
import csv
import json
from datetime import datetime, timezone

import broker
import config as C
import state as st


def spy_series(start_ts):
    """SPY מנורמל ל-100,000 מתאריך ההתחלה; מחזיר {} אם נכשל."""
    try:
        import yfinance as yf
        df = yf.download("SPY", period="2y", interval="1d", auto_adjust=True, progress=False)
        close = df["Close"].squeeze().dropna()
        out = {}
        for ts, v in close.items():
            out[ts.strftime("%Y-%m-%d")] = float(v)
        return out
    except Exception as e:
        print("spy failed", e)
        return {}


def levels():
    """סטופ ויעד לפי הלוג, לפי טיקר (השורה האחרונה לכל טיקר)."""
    out = {}
    try:
        with open("signals_log.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["ticker"]] = {"stop": float(r["stop"]), "target": float(r["target"])}
    except Exception as e:
        print("levels failed", e)
    return out


def build():
    acc = broker._req("GET", "/v2/account").json()
    pos = broker._req("GET", "/v2/positions").json()
    orders = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 100, "nested": "false"}).json()
    equity, last_eq = float(acc["equity"]), float(acc["last_equity"])
    hist = []
    try:
        h = broker.portfolio_history("all")
        for t, e in zip(h.get("timestamp", []), h.get("equity", [])):
            if e:
                hist.append({"d": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), "e": float(e)})
    except Exception as ex:
        print("history failed", ex)
    spy = spy_series(hist[0]["d"] if hist else None)
    base = next((spy[p["d"]] for p in hist if p["d"] in spy), None)
    start_eq = hist[0]["e"] if hist else equity
    for p in hist:
        p["spy"] = round(start_eq * spy[p["d"]] / base, 2) if base and p["d"] in spy else None
    s = st.load()
    lv = levels()
    # מקור אמת: הוראות מכירה פעילות ב-Alpaca (כולל סטופ של ליבת SPY)
    try:
        nested = broker._req("GET", "/v2/orders", params={"status": "open", "limit": 200, "nested": "true"}).json()
        flat = []
        for o in nested:
            flat.append(o); flat.extend(o.get("legs") or [])
        for o in flat:
            if o["side"] != "sell":
                continue
            d = lv.setdefault(o["symbol"], {})
            if o["type"] == "limit" and o.get("limit_price"):
                d["target"] = float(o["limit_price"])
            elif o["type"] in ("stop", "stop_limit") and o.get("stop_price"):
                d["stop"] = float(o["stop_price"])
    except Exception as ex:
        print("live levels failed", ex)
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "equity": equity, "cash": float(acc["cash"]), "buying_power": float(acc.get("buying_power") or 0),
        "day_pl": equity - last_eq, "day_pct": (equity - last_eq) / last_eq * 100 if last_eq else 0,
        "peak": float(s.get("peak_equity") or equity), "paused": bool(s.get("paused")), "dd_limit": C.MAX_DRAWDOWN_PCT,
        "positions": [{"symbol": p["symbol"], "qty": float(p["qty"]), "entry": float(p["avg_entry_price"]),
                       "price": float(p["current_price"]), "pl": float(p["unrealized_pl"]),
                       "plpc": float(p["unrealized_plpc"]) * 100, "core": p["symbol"] in C.CORE_SYMBOLS, **lv.get(p["symbol"], {})} for p in pos],
        "pending": [{"symbol": o["symbol"], "qty": o["qty"], "limit": float(o["limit_price"]), **lv.get(o["symbol"], {})}
                    for o in orders if o["side"] == "buy" and o["type"] == "limit"],
        "history": hist,
    }


def main():
    data = build()
    with open("dashboard_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("dashboard_data.json:", data["equity"], len(data["positions"]), "pos", len(data["history"]), "pts")


if __name__ == "__main__":
    main()
