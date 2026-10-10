import numpy as np
import pandas as pd

import config as C


def add_indicators(df):
    df = df.copy()
    c = df["Close"]
    df["sma20"] = c.rolling(20).mean()
    df["sma50"] = c.rolling(50).mean()
    df["sma200"] = c.rolling(200).mean()
    df["sma200_up"] = df["sma200"] > df["sma200"].shift(20)

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)

    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - c.shift()).abs(), (df["Low"] - c.shift()).abs()],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    df["dollar_vol"] = (c * df["Volume"]).rolling(20).mean()
    df["mom"] = c.pct_change(C.MOMENTUM_DAYS)
    return df


def compute_signals(df):
    """מחשב לכל יום: האם יש סיגנל + רמות כניסה/סטופ/יעד. df חייב לעבור add_indicators."""
    c = df["Close"]
    entry = np.minimum(c, df["sma20"])
    stop = entry - C.STOP_ATR * df["atr"]
    risk = entry - stop
    risk_pct = risk / entry

    cond = (
        (c >= C.MIN_PRICE)
        & (df["dollar_vol"] >= C.MIN_DOLLAR_VOLUME)
        & (c > df["sma200"])
        & (df["sma50"] > df["sma200"])
        & df["sma200_up"]
        & (c <= df["sma20"] * C.PULLBACK_MAX_ABOVE_SMA20)
        & (c >= df["sma50"] * C.MIN_VS_SMA50)
        & (df["rsi"] <= C.RSI_MAX)
        & (risk_pct >= C.MIN_RISK_PCT)
        & (risk_pct <= C.MAX_RISK_PCT)
    )
    out = df.copy()
    out["sig"] = cond.astype(bool)
    out["entry"] = entry.round(2)
    out["stop"] = stop.round(2)
    out["target"] = (entry + C.RR * risk).round(2)
    out["risk_pct"] = risk_pct
    return out


def simulate(future, entry, stop, target):
    """
    מדמה הוראת Buy Limit עם סטופ ויעד על הנרות שאחרי יום הסיגנל.
    הנחות שמרניות: אם באותו נר נגעו גם בסטופ וגם ביעד - נחשב סטופ.
    גאפ למטה ממלא בפתיחה; גאפ דרך הסטופ יוצא בפתיחה.
    """
    o = future["Open"].to_numpy()
    h = future["High"].to_numpy()
    l = future["Low"].to_numpy()
    cl = future["Close"].to_numpy()
    idx = future.index
    risk = entry - stop
    fill = None
    fill_i = None

    def closed(status, px, i):
        return {
            "status": status, "fill_price": fill, "fill_date": idx[fill_i],
            "exit_price": px, "exit_date": idx[i], "r": (px - fill) / risk,
        }

    for i in range(len(future)):
        if fill is None:
            if i >= C.ORDER_VALID_DAYS:
                return {"status": "expired"}
            if l[i] > entry:
                continue
            fill = min(entry, o[i])
            fill_i = i
            ref = fill
        else:
            ref = o[i]

        if l[i] <= stop:
            return closed("stopped", min(stop, ref), i)
        if h[i] >= target:
            return closed("target", max(target, ref), i)
        if i - fill_i >= C.MAX_HOLD_DAYS:
            return closed("timeout", cl[i], i)

    if fill is None:
        return {"status": "expired"} if len(future) >= C.ORDER_VALID_DAYS else {"status": "pending"}
    return {"status": "open", "fill_price": fill, "fill_date": idx[fill_i]}
