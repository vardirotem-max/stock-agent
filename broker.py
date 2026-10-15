"""חיבור ל-Alpaca - מסחר דמה (Paper) בלבד. הכתובת קבועה בכוונה ואי אפשר לשנות אותה בהגדרות."""
import os
import time

import requests

BASE = "https://paper-api.alpaca.markets"


def enabled():
    return bool(os.getenv("ALPACA_KEY_ID") and os.getenv("ALPACA_SECRET_KEY"))


def _req(method, path, **kw):
    headers = {
        "APCA-API-KEY-ID": os.getenv("ALPACA_KEY_ID", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }
    return requests.request(method, BASE + path, headers=headers, timeout=30, **kw)


def profit_cap_price(entry, qty):
    """מחיר היעד שבו הרווח בפוזיציה מגיע לתקרה (POSITION_PROFIT_CAP). None אם כבוי."""
    import config as C
    cap = float(getattr(C, "POSITION_PROFIT_CAP", 0) or 0)
    if cap <= 0 or not qty:
        return None
    return round(float(entry) + cap / float(qty), 2)


def place_bracket(symbol, qty, entry, stop, target, client_id):
    """קנייה בלימיט + סטופ + יעד (OCO) כהוראה אחת. תקפה עד שמתמלאת או שהבוט מבטל.
    היעד מוגבל לתקרת הרווח לפוזיציה (POSITION_PROFIT_CAP)."""
    capp = profit_cap_price(entry, qty)
    if capp is not None:
        target = max(min(target, capp), round(entry + 0.01, 2))
    body = {
        "symbol": symbol,
        "qty": str(int(qty)),
        "side": "buy",
        "type": "limit",
        "limit_price": f"{entry:.2f}",
        "time_in_force": "gtc",
        "order_class": "bracket",
        "take_profit": {"limit_price": f"{target:.2f}"},
        "stop_loss": {"stop_price": f"{stop:.2f}"},
        "client_order_id": client_id,
    }
    r = _req("POST", "/v2/orders", json=body)
    if r.status_code in (200, 201):
        return r.json()["id"]
    if r.status_code == 422 and "client_order_id" in r.text:  # מזהה כבר קיים
        g = _req("GET", "/v2/orders:by_client_order_id", params={"client_order_id": client_id})
        if g.ok:
            old = g.json()
            if old.get("status") in ACTIVE or old.get("status") in ("filled", "partially_filled"):
                return old["id"]  # הוראה חיה או מומלאת - לא שולחים כפולה
            # ההוראה הישנה בוטלה/פגה/נדחתה - שולחים חדשה במזהה חדש
            body["client_order_id"] = f"{client_id}-r{int(time.time())}"
            r2 = _req("POST", "/v2/orders", json=body)
            if r2.status_code in (200, 201):
                return r2.json()["id"]
            raise RuntimeError(f"resend {r2.status_code} {r2.text[:200]}")
    raise RuntimeError(f"{r.status_code} {r.text[:200]}")


def cancel(order_id):
    r = _req("DELETE", f"/v2/orders/{order_id}")
    if r.status_code not in (200, 204, 404, 422):
        raise RuntimeError(f"cancel {r.status_code} {r.text[:150]}")


def close(symbol, order_id):
    """סוגר פוזיציה ומבטל את רגלי הסטופ/יעד הפתוחות."""
    g = _req("GET", f"/v2/orders/{order_id}", params={"nested": "true"})
    if g.ok:
        for leg in g.json().get("legs") or []:
            if leg.get("status") in ("new", "accepted", "held", "pending_new", "partially_filled"):
                _req("DELETE", f"/v2/orders/{leg['id']}")
    r = _req("DELETE", f"/v2/positions/{symbol}")
    if r.status_code not in (200, 204, 404):
        raise RuntimeError(f"close {r.status_code} {r.text[:150]}")


DATA_BASE = "https://data.alpaca.markets"
ACTIVE = {"new", "accepted", "held", "pending_new", "partially_filled", "pending_replace"}


def get_order(order_id):
    r = _req("GET", f"/v2/orders/{order_id}", params={"nested": "true"})
    if not r.ok:
        raise RuntimeError(f"get_order {r.status_code} {r.text[:150]}")
    return r.json()


def snapshots(symbols):
    """תמונת מצב יומית ממקור שני (IEX) - לאימות נתוני Yahoo."""
    headers = {
        "APCA-API-KEY-ID": os.getenv("ALPACA_KEY_ID", ""),
        "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }
    r = requests.get(
        DATA_BASE + "/v2/stocks/snapshots",
        headers=headers, params={"symbols": ",".join(symbols), "feed": "iex"}, timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"snapshots {r.status_code} {r.text[:150]}")
    j = r.json()
    return j.get("snapshots", j)


def audit():
    """בודק שלכל פוזיציה פתוחה יש הוראת יעד (limit sell) והוראת סטופ פעילות. מחזיר רשימת בעיות."""
    p = _req("GET", "/v2/positions")
    o = _req("GET", "/v2/orders", params={"status": "all", "nested": "true", "limit": 500, "direction": "desc"})
    if not p.ok or not o.ok:
        raise RuntimeError(f"audit {p.status_code}/{o.status_code}")
    flat = []
    for order in o.json():
        flat.append(order)
        flat.extend(order.get("legs") or [])
    problems = []
    for pos in p.json():
        sym, qty = pos["symbol"], float(pos["qty"])
        sells = [x for x in flat if x["symbol"] == sym and x["side"] == "sell" and x["status"] in ACTIVE]
        tp = sum(float(x["qty"]) for x in sells if x["type"] == "limit")
        sl = sum(float(x["qty"]) for x in sells if x["type"] in ("stop", "stop_limit"))
        if tp < qty or sl < qty:
            problems.append(f"🚨 {sym}: פוזיציה של {qty:g} מניות בלי הגנה מלאה (יעד {tp:g}, סטופ {sl:g})")
    return problems, len(p.json())


def equity():
    """שווי החשבון הנוכחי, או None אם נכשל."""
    try:
        r = _req("GET", "/v2/account")
        return float(r.json()["equity"]) if r.ok else None
    except Exception as e:
        print("equity failed", e)
        return None


def last_sell_fill(symbol, after_iso):
    """מחיר מילוי ממוצע של הוראת מכירה אחרונה שמולאה על הסימבול אחרי זמן המילוי של הקנייה."""
    r = _req("GET", "/v2/orders", params={"status": "closed", "symbols": symbol, "direction": "desc", "limit": 20})
    if not r.ok:
        return None
    for o in r.json():
        if o.get("side") == "sell" and o.get("filled_avg_price") and (not after_iso or (o.get("filled_at") or "") >= after_iso):
            return float(o["filled_avg_price"])
    return None


def portfolio_history(period="all"):
    r = _req("GET", "/v2/account/portfolio/history", params={"period": period, "timeframe": "1D"})
    if not r.ok:
        raise RuntimeError(f"history {r.status_code} {r.text[:150]}")
    return r.json()
