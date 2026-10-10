"""מצב קבוע של הבוט (שיא החשבון ועצירה אוטומטית). נשמר ב-state.json ב-repo."""
import json
import os

FILE = "state.json"
DEFAULT = {"peak_equity": None, "paused": False, "paused_at": ""}


def load():
    if os.path.exists(FILE):
        try:
            with open(FILE, encoding="utf-8") as f:
                return {**DEFAULT, **json.load(f)}
        except Exception as e:
            print("state load failed", e)
    return dict(DEFAULT)


def save(s):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
