"""1-minute scalping signal strategy with a 5-minute trend filter.
Signals only; this module does not place orders.
"""
from .indicators import ema, rsi, sma, macd_histogram, atr


def analyze(
    symbol,
    candles_5m,
    candles_1m,
    capital=100.0,
    risk_percent=1.0,
    max_leverage=20.0,
    min_confidence=75,
):
    # Exclude currently forming candles to avoid unstable/repainting signals.
    m5 = candles_5m[:-1]
    m1 = candles_1m[:-1]
    if len(m5) < 60 or len(m1) < 60:
        return {"symbol": symbol, "status": "INSUFFICIENT_DATA"}

    close5 = [c["close"] for c in m5]
    close1 = [c["close"] for c in m1]
    vol1 = [c["volume"] for c in m1]
    ema20_5 = ema(close5, 20)
    ema50_5 = ema(close5, 50)
    rsi5 = rsi(close5, 14)
    ema9_1 = ema(close1, 9)
    ema21_1 = ema(close1, 21)
    rsi1 = rsi(close1, 14)
    macd1 = macd_histogram(close1, 6, 13, 5)
    vol_avg = sma(vol1, 20)
    atr1 = atr(m1, 14)

    last = m1[-1]
    prev = m1[-2]
    price = last["close"]
    trend_long = ema20_5[-1] > ema50_5[-1] and rsi5[-1] >= 50
    trend_short = ema20_5[-1] < ema50_5[-1] and rsi5[-1] <= 50

    # Momentum crossover/reclaim with volume confirmation.
    volume_ok = last["volume"] >= vol_avg[-1]
    long_signal = (
        trend_long
        and ema9_1[-1] > ema21_1[-1]
        and last["close"] > last["open"]
        and last["close"] > ema9_1[-1]
        and prev["close"] <= ema9_1[-2]
        and rsi1[-1] > 50
        and macd1[-1] > 0
        and volume_ok
    )
    short_signal = (
        trend_short
        and ema9_1[-1] < ema21_1[-1]
        and last["close"] < last["open"]
        and last["close"] < ema9_1[-1]
        and prev["close"] >= ema9_1[-2]
        and rsi1[-1] < 50
        and macd1[-1] < 0
        and volume_ok
    )
    trend = "BULLISH" if trend_long else "BEARISH" if trend_short else "NEUTRAL"
    common = {
        "symbol": symbol,
        "last_price": price,
        "trend_5m": trend,
        "timeframes": ["5m", "1m"],
        "indicators": {
            "ema20_5m": round(ema20_5[-1], 8),
            "ema50_5m": round(ema50_5[-1], 8),
            "ema9_1m": round(ema9_1[-1], 8),
            "ema21_1m": round(ema21_1[-1], 8),
            "rsi5m": round(rsi5[-1], 2),
            "rsi1m": round(rsi1[-1], 2),
            "macd_hist_1m": round(macd1[-1], 8),
            "volume_confirmed": volume_ok,
            "atr1m": round(atr1[-1], 8),
        },
    }
    if not (long_signal or short_signal):
        return {**common, "status": "NO_SIGNAL"}

    side = "LONG" if long_signal else "SHORT"
    atr_now = atr1[-1]
    # Tight structure-based stop with ATR buffer, then exact 2R main target.
    if side == "LONG":
        sl = min(prev["low"], last["low"], price - 0.8 * atr_now)
        if sl >= price:
            return {"symbol": symbol, "status": "REJECTED", "reason": "Invalid LONG stop"}
    else:
        sl = max(prev["high"], last["high"], price + 0.8 * atr_now)
        if sl <= price:
            return {"symbol": symbol, "status": "REJECTED", "reason": "Invalid SHORT stop"}

    risk_distance = abs(price - sl)
    stop_fraction = risk_distance / price if price else 0
    if stop_fraction <= 0:
        return {"symbol": symbol, "status": "REJECTED", "reason": "Zero stop distance"}

    risk_usdt = capital * risk_percent / 100
    notional = risk_usdt / stop_fraction
    leverage = notional / capital if capital else 0
    risk_at_stop = risk_usdt
    risk_note = "Estimate excludes fees, slippage, funding and liquidation effects."
    if leverage > max_leverage:
        notional = capital * max_leverage
        leverage = max_leverage
        risk_at_stop = notional * stop_fraction
        risk_note = (
            f"Estimated risk at SL is {risk_at_stop:.4f} USDT after leverage cap; "
            "excludes fees, slippage, funding and liquidation effects."
        )

    # Keep three target fields for compatibility with existing signal displays.
    # TP1 = 1R partial, TP2 = the requested 2R primary target, TP3 = 3R extension.
    if side == "LONG":
        tp1, tp2, tp3 = price + risk_distance, price + 2 * risk_distance, price + 3 * risk_distance
    else:
        tp1, tp2, tp3 = price - risk_distance, price - 2 * risk_distance, price - 3 * risk_distance

    score = 60 + (10 if volume_ok else 0)
    score += 10 if (rsi1[-1] > 55 if side == "LONG" else rsi1[-1] < 45) else 0
    score += 10 if (ema9_1[-1] > ema21_1[-1] if side == "LONG" else ema9_1[-1] < ema21_1[-1]) else 0
    score += 10 if (trend_long if side == "LONG" else trend_short) else 0
    score = min(score, 90)
    if score < min_confidence:
        return {**common, "status": "FILTERED", "confidence_score": score}

    return {
        **common,
        "status": "SIGNAL",
        "side": side,
        "entry": round(price, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "sl": round(sl, 8),
        "capital_usdt": round(capital, 2),
        "risk_budget_usdt": round(risk_usdt, 2),
        "estimated_risk_at_sl_usdt": round(risk_at_stop, 4),
        "notional_usdt": round(notional, 4),
        "leverage": round(leverage, 4),
        "confidence_score": score,
        "confidence_note": "Heuristic score; not a verified probability of winning.",
        "risk_reward_tp1": 1.0,
        "risk_reward_main_target": 2.0,
        "risk_note": risk_note,
    }
