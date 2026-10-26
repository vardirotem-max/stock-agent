"""בדיקות אבטחה: אין סודות בקבצים במעקב, ואין שימוש מסוכן ב-workflows."""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATTERNS = [
    r"\b(PK|AK)[A-Z0-9]{18}\b",            # מפתח Alpaca
    r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b",  # טוקן טלגרם
    r"\bghp_[A-Za-z0-9]{30,}\b", r"\bgithub_pat_[A-Za-z0-9_]{30,}\b", r"\bsk-[A-Za-z0-9]{20,}\b",
]


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return [ROOT / f for f in out if f.endswith((".py", ".yml", ".txt", ".md", ".json", ".csv", ".html"))]


def test_no_secrets_in_tracked_files():
    bad = []
    for f in tracked():
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for p in PATTERNS:
            if re.search(p, txt):
                bad.append(f"{f.name}: {p}")
    assert not bad, bad


def test_workflows_safe():
    for f in (ROOT / ".github" / "workflows").glob("*.yml"):
        t = f.read_text(encoding="utf-8")
        assert "pull_request_target" not in t, f.name
        assert "set -x" not in t, f.name
        assert not re.search(r"echo\s+.*\$\{\{\s*secrets\.", t), f.name
