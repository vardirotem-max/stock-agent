"""שחרור העצירה האוטומטית: מאפס את השיא לשווי הנוכחי ומחזיר את הבוט לשלוח הוראות."""
import broker
import state as st
from notify import send_telegram

eq = broker.equity()
s = st.load()
was = s.get("paused")
s.update(paused=False, paused_at="")
if eq:
    s["peak_equity"] = eq
st.save(s)
msg = f"▶️ הבוט שוחרר מעצירה (היה מושהה: {was}). שיא חדש: {eq:,.0f}$" if eq else "▶️ הבוט שוחרר מעצירה."
print(msg)
send_telegram(msg)
