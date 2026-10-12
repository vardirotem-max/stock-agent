"""בונה את דף ה-Dashboard מ-dashboard_data.json לתוך dashboard/dashboard.html (מוכן לפרסום כ-Artifact)."""
import json

d = json.load(open("dashboard_data.json", encoding="utf-8"))
d.setdefault("dd_limit", 5.0)
t = open("dashboard/template.html", encoding="utf-8").read()
assert "/*DATA*/null" in t
open("dashboard/dashboard.html", "w", encoding="utf-8").write(t.replace("/*DATA*/null", json.dumps(d, ensure_ascii=False)))
print("built", d["updated"], d["equity"])
