import os

import requests


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[אין פרטי טלגרם - מדפיס למסך]\n" + text)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text[:4000]},
        timeout=30,
    )
    if not r.ok:
        print("Telegram error:", r.status_code, r.text)
    return r.ok
