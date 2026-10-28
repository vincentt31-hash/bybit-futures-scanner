from .indicators import ema, rsi, sma, macd_histogram, atr


def _fib_levels(swing_low, swing_high):
    """Retracement levels measured from the recent swing range."""
    span = swing_high - swing_low
    if span <= 0:
        return {}
    return {
        "0.382": swing_high - 0.382 * span,
        "0.500": swing_high - 0.500 * span,
        "0.618": swing_high - 0.618 * span,
    }


def analyze(
    symbol,
    candles_1h,
    candles_15m,
    capital=100.0,
    risk_percent=1.0,
    max_leverage=20.0,
    min_confidence=75,
):
    # Only completed candles are used; ignore the currently forming candle.
    h1 = candles_1h[:-1]
    m15 = candles_15m[:-1]
    if len(h1) < 210 or len(m15) < 60:
        return {"symbol": symbol, "status": "INSUFFICIENT_DATA"}

    closes1 = [c["close"] for c in h1]
    closes15 = [c["close"] for c in m15]
    volumes15 = [c["volume"] for c in m15]

    ema50_1h = ema(closes1, 50)
    ema200_1h = ema(closes1, 200)
    rsi1h = rsi(closes1, 14)
    macd1h = macd_histogram(closes1)

    ema20_15m = ema(closes15, 20)
    rsi15 = rsi(closes15, 14)
    macd15 = macd_histogram(closes15)
    volume_sma20 = sma(volumes15, 20)
    atr15 = atr(m15, 14)

    last1 = h1[-1]
    last15 = m15[-1]
    price = last15["close"]

    # Higher-timeframe trend filter: EMA alignment + momentum.
    bullish_trend = (
        ema50_1h[-1] > ema200_1h[-1]
        and rsi1h[-1] > 50
        and macd1h[-1] > 0
    )
    bearish_trend = (
        ema50_1h[-1] < ema200_1h[-1]
        and rsi1h[-1] < 50
        and macd1h[-1] < 0
    )

    prior = m15[-21:-1]
    resistance = max(c["high"] for c in prior)
    support = min(c["low"] for c in prior)

    # Correction-confirmation setup on completed 15m candles only.
    # A prior candle must pull back into the EMA20 / Fibonacci retracement zone.
    # Latest closed candle then confirms rejection in the higher-timeframe trend.
    swing = m15[-50:]
    swing_low = min(c["low"] for c in swing)
    swing_high = max(c["high"] for c in swing)
    fib = _fib_levels(swing_low, swing_high)

    prev15 = m15[-2]
    ema20_now = ema20_15m[-1]
    ema20_prev = ema20_15m[-2]
    volume_confirmed = last15["volume"] > volume_sma20[-1]

    fib_long_zone = bool(fib) and fib["0.382"] <= prev15["low"] <= fib["0.618"]
    fib_short_zone = bool(fib) and fib["0.382"] <= prev15["high"] <= fib["0.618"]
    ema_long_correction = prev15["low"] <= ema20_prev * 1.003
    ema_short_correction = prev15["high"] >= ema20_prev * 0.997

    # Confirmation: latest fully closed candle reclaims EMA20 and breaks
    # the previous candle's extreme with a directional close.
    bullish_confirmation = (
        last15["close"] > last15["open"]
        and last15["close"] > prev15["high"]
        and last15["close"] > ema20_now
        and rsi15[-1] > 50
        and macd15[-1] > 0
    )
    bearish_confirmation = (
        last15["close"] < last15["open"]
        and last15["close"] < prev15["low"]
        and last15["close"] < ema20_now
        and rsi15[-1] < 50
        and macd15[-1] < 0
    )

    long_setup = (
        bullish_trend
        and (ema_long_correction or fib_long_zone)
        and bullish_confirmation
        and volume_confirmed
    )
    short_setup = (
        bearish_trend
        and (ema_short_correction or fib_short_zone)
        and bearish_confirmation
        and volume_confirmed
    )

    trend = "BULLISH" if bullish_trend else "BEARISH" if bearish_trend else "NEUTRAL"

    if not (long_setup or short_setup):
        return {
            "symbol": symbol,
            "status": "NO_SIGNAL",
            "last_price": price,
            "trend_1h": trend,
            "indicators": {
                "ema50_1h": round(ema50_1h[-1], 8),
                "ema200_1h": round(ema200_1h[-1], 8),
                "ema20_15m": round(ema20_15m[-1], 8),
                "rsi1h": round(rsi1h[-1], 2),
                "rsi15m": round(rsi15[-1], 2),
                "macd_hist_1h": round(macd1h[-1], 8),
                "macd_hist_15m": round(macd15[-1], 8),
                "breakout_resistance": round(resistance, 8),
                "breakout_support": round(support, 8),
                "fib_382": round(fib.get("0.382", 0), 8),
                "fib_500": round(fib.get("0.500", 0), 8),
                "fib_618": round(fib.get("0.618", 0), 8),
                "volume_confirmed": volume_confirmed,
            },
        }

    side = "LONG" if long_setup else "SHORT"
    latest_atr = atr15[-1]

    # Structural stop with a small ATR buffer.
    if side == "LONG":
        sl = min(prev15["low"], last15["low"], support) - 0.2 * latest_atr
        if sl >= price:
            return {"symbol": symbol, "status": "REJECTED", "reason": "Invalid LONG stop"}
    else:
        sl = max(prev15["high"], last15["high"], resistance) + 0.2 * latest_atr
        if sl <= price:
            return {"symbol": symbol, "status": "REJECTED", "reason": "Invalid SHORT stop"}

    risk_usdt = capital * risk_percent / 100.0
    stop_fraction = abs(price - sl) / price
    if stop_fraction <= 0:
        return {"symbol": symbol, "status": "REJECTED", "reason": "Zero stop distance"}

    notional = risk_usdt / stop_fraction
    leverage = notional / capital if capital else 0
    if leverage > max_leverage:
        notional = capital * max_leverage
        leverage = max_leverage
        risk_at_stop = notional * stop_fraction
        risk_note = (
            f"Estimated risk at SL is {risk_at_stop:.4f} USDT after leverage cap; "
            "excludes fees, slippage, funding and liquidation effects."
        )
    else:
        risk_at_stop = risk_usdt
        risk_note = "Estimate excludes fees, slippage, funding and liquidation effects."

    risk_distance = abs(price - sl)
    # TP1 must satisfy at least 2:1 reward-to-risk. Higher targets are 3R/4R.
    if side == "LONG":
        tp1 = price + 2 * risk_distance
        tp2 = price + 3 * risk_distance
        tp3 = price + 4 * risk_distance
        rr_tp1 = (tp1 - price) / risk_distance
    else:
        tp1 = price - 2 * risk_distance
        tp2 = price - 3 * risk_distance
        tp3 = price - 4 * risk_distance
        rr_tp1 = (price - tp1) / risk_distance

    if rr_tp1 < 2.0:
        return {"symbol": symbol, "status": "REJECTED", "reason": "TP1 RR below minimum 1:2"}

    # Transparent score, not a calibrated win probability.
    score = 60
    score += 10 if volume_confirmed else 0
    score += 10 if (rsi15[-1] > 55 if side == "LONG" else rsi15[-1] < 45) else 0
    score += 10 if (price > fib["0.500"] if side == "LONG" else price < fib["0.500"]) else 0
    score += 10 if (price > ema20_15m[-1] if side == "LONG" else price < ema20_15m[-1]) else 0
    score = min(score, 90)

    if score < min_confidence:
        return {
            "symbol": symbol,
            "status": "FILTERED",
            "confidence_score": score,
            "trend_1h": trend,
        }

    return {
        "symbol": symbol,
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
        "risk_reward_tp1": round(rr_tp1, 2),
        "risk_note": risk_note,
        "trend_1h": trend,
        "indicators": {
            "ema50_1h": round(ema50_1h[-1], 8),
            "ema200_1h": round(ema200_1h[-1], 8),
            "ema20_15m": round(ema20_15m[-1], 8),
            "rsi1h": round(rsi1h[-1], 2),
            "rsi15m": round(rsi15[-1], 2),
            "macd_hist_1h": round(macd1h[-1], 8),
            "macd_hist_15m": round(macd15[-1], 8),
            "breakout_resistance": round(resistance, 8),
            "breakout_support": round(support, 8),
            "fib_382": round(fib["0.382"], 8),
            "fib_500": round(fib["0.500"], 8),
            "fib_618": round(fib["0.618"], 8),
            "volume_confirmed": volume_confirmed,
        },
        "timeframes": ["1h", "15m"],
    }
