# אבטחה — צ'קליסט

חשבון Alpaca הוא דמה (paper) בלבד. ועדיין:

1. **לבטל ולייצר מחדש** כל מפתח/טוקן שהודבק אי פעם בצ'אט: Alpaca (Paper → API Keys → Regenerate), טלגרם (BotFather → /revoke), GitHub (Settings → Developer settings → Tokens → Delete).
2. **לעדכן את ה-Secrets** בריפו: Settings → Secrets and variables → Actions → ALPACA_KEY_ID, ALPACA_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
3. **להפעיל אימות דו-שלבי** (2FA) ב-GitHub וב-Alpaca.
4. אל מעבר לחשבון אמיתי בלי: מפתח ייעודי עם הרשאות מינימום, ובדיקה חוזרת של כל הסעיפים.

הבדיקות האוטומטיות (`tests/test_security.py`) נכשלות אם סוד מוצג בקבצים של הריפו.
