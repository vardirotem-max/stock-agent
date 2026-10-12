"""בדיקת מצב מלאה: הוראות (כולל מילויים וביטולים), פוזיציות, מחירי היום מול הלימיט."""
import broker

L = []
acc = broker._req("GET", "/v2/account").json()
clock = broker._req("GET", "/v2/clock").json()
L.append(f"שווי {float(acc['equity']):,.2f}$ | מזומן {float(acc['cash']):,.2f}$ | שוק {'פתוח' if clock.get('is_open') else 'סגור'} | {clock.get('timestamp')}")
orders = broker._req("GET", "/v2/orders", params={"status": "all", "limit": 50, "nested": "true", "direction": "desc"}).json()
syms = sorted({o["symbol"] for o in orders})
snaps = {}
try:
    snaps = broker.snapshots(syms) if syms else {}
except Exception as e:
    L.append(f"snapshots נכשל: {e}")
L.append("")
for o in orders:
    if o.get("order_class") not in ("bracket", "") and o.get("parent_order_id"):
        continue
    s = snaps.get(o["symbol"], {})
    day = s.get("dailyBar", {}) or {}
    last = (s.get("latestTrade") or {}).get("p")
    lim = float(o["limit_price"]) if o.get("limit_price") else None
    L.append(f"{o['symbol']}: {o['side']} {o['qty']} @ {lim} | סטטוס {o['status']} | מולא {o.get('filled_qty')} @ {o.get('filled_avg_price')}"
             f" | היום פתיחה {day.get('o')} שפל {day.get('l')} גבוה {day.get('h')} | אחרון {last}")
    for leg in o.get("legs") or []:
        L.append(f"   ↳ {leg['type']} {leg['side']} סטטוס {leg['status']} מחיר {leg.get('limit_price') or leg.get('stop_price')}")
pos = broker._req("GET", "/v2/positions").json()
L.append("")
L.append(f"פוזיציות פתוחות: {len(pos)}")
for p in pos:
    L.append(f"  {p['symbol']}: {p['qty']} @ {p['avg_entry_price']} עכשיו {p['current_price']} P/L {p['unrealized_pl']}")
t = "\n".join(L)
print(t)
open("status_report.txt", "w", encoding="utf-8").write(t + "\n")
