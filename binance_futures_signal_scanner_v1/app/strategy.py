import math
from typing import Any, Dict, List

from .indicators import ema, rsi, atr

# Hard floor: every target is at least 1:2.
MIN_RR_FLOOR = 2.0

# DAY TRADE settings: trend on 1H, entry on 15M, hold for hours.
# Stop distance limits (fraction of entry price)
MIN_STOP_PCT = 0.02    # stop never tighter than 2%
MAX_STOP_PCT = 0.08    # stop never wider than 8%


def analyze(
    symbol: str,
    candles_trend: List[Dict[str, Any]],   # 1H candles (trend filter)
    candles_entry: List[Dict[str, Any]],   # 15M candles (entry)
    capital: float = 100.0,
    risk_percent: float = 10.0,
    max_leverage: float = 10.0,
    min_confidence: int = 0,
    min_rr: float = 2.0,
    include_latest: bool = False,
) -> Dict[str, Any]:
    """
    Day-trade strategy (LONG and SHORT), signal only:
    - Trend filter : 1H  (EMA20 vs EMA50 + price vs EMA50)
    - Entry        : 15M (pullback to EMA9, then reclaim/reject EMA9)
    - Stop loss    : beyond the last ~12 hours of 1H swing, 2%-8% away
    - Take profit  : TP1 2R, TP2 3R, TP3 4R (minimum RR 1:2)
    - Sizing       : max loss at stop = risk_percent of capital;
                     leverage and margin are derived from the stop distance
    """

    symbol = str(symbol).upper().replace("/", "").replace(".P", "")

    # indicators object is ALWAYS returned (null until calculated)
    indicators_out: Dict[str, Any] = {
        "ema20_1h": None,
        "ema50_1h": None,
        "ema9_15m": None,
        "ema21_15m": None,
        "rsi_15m": None,
        "atr_15m": None,
        "atr_1h": None,
        "trend_1h": None,
        "volume_confirmed": None,
    }

    def no_signal(reason: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "signal": "NO_SIGNAL",
            "status": "NO_SIGNAL",
            "reason": reason,
            "timeframe_entry": "15m",
            "timeframe_trend": "1h",
            "trend_1h": indicators_out["trend_1h"],
            "indicators": indicators_out,
        }

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    if not candles_trend or not candles_entry:
        return no_signal("No candle data")

    if capital <= 0:
        return no_signal("Capital must be greater than zero")

    if risk_percent <= 0:
        return no_signal("Risk percent must be greater than zero")

    if max_leverage < 1:
        return no_signal("Leverage must be at least 1")

    if min_rr <= 0:
        return no_signal("Risk reward must be greater than zero")

    rr = max(float(min_rr), MIN_RR_FLOOR)

    # Exclude the latest candle if it is still forming.
    if include_latest:
        ch = candles_trend
        ce = candles_entry
    else:
        ch = candles_trend[:-1]
        ce = candles_entry[:-1]

    if len(ch) < 55 or len(ce) < 40:
        return no_signal("Insufficient closed candles")

    # ---------------------------------------------------------
    # PRICE DATA
    # ---------------------------------------------------------

    try:
        close_h = [float(c["close"]) for c in ch]
        close_e = [float(c["close"]) for c in ce]

        if any(price <= 0 for price in close_h + close_e):
            return no_signal("Invalid candle price")

    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    # ---------------------------------------------------------
    # INDICATORS
    # ---------------------------------------------------------

    ema20_h = ema(close_h, 20)
    ema50_h = ema(close_h, 50)
    atr_h_series = atr(ch, 14)

    ema9_e = ema(close_e, 9)
    ema21_e = ema(close_e, 21)
    rsi_e = rsi(close_e, 14)
    atr_e_series = atr(ce, 14)

    i = len(ce) - 1
    j = len(ch) - 1

    required = [
        ema20_h[j], ema50_h[j], atr_h_series[j],
        ema9_e[i], ema21_e[i], rsi_e[i], atr_e_series[i],
    ]
    if any(value is None for value in required):
        return no_signal("Indicators not ready")

    try:
        last = ce[i]
        o = float(last["open"])
        h = float(last["high"])
        l = float(last["low"])
        entry = float(last["close"])
    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    atr_e = float(atr_e_series[i])
    atr_h = float(atr_h_series[j])
    current_rsi = float(rsi_e[i])

    # ---------------------------------------------------------
    # 1H TREND FILTER
    # ---------------------------------------------------------

    trend_up = ema20_h[j] > ema50_h[j] and close_h[j] > ema50_h[j]
    trend_down = ema20_h[j] < ema50_h[j] and close_h[j] < ema50_h[j]
    trend = "UP" if trend_up else "DOWN" if trend_down else "SIDEWAYS"

    # ---------------------------------------------------------
    # VOLUME (soft factor: boosts confidence, not a hard block)
    # ---------------------------------------------------------

    try:
        volumes = [float(c.get("volume", 0)) for c in ce]
    except (TypeError, ValueError):
        return no_signal("Invalid volume data")

    average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    volume_confirmed = average_volume > 0 and volumes[i] >= average_volume

    indicators_out.update({
        "ema20_1h": round(float(ema20_h[j]), 8),
        "ema50_1h": round(float(ema50_h[j]), 8),
        "ema9_15m": round(float(ema9_e[i]), 8),
        "ema21_15m": round(float(ema21_e[i]), 8),
        "rsi_15m": round(current_rsi, 4),
        "atr_15m": round(atr_e, 8),
        "atr_1h": round(atr_h, 8),
        "trend_1h": trend,
        "volume_confirmed": volume_confirmed,
    })

    if entry <= 0 or atr_e <= 0 or atr_h <= 0:
        return no_signal("Invalid ATR or entry price")

    if trend == "SIDEWAYS":
        return no_signal("1H trend is sideways")

    # Skip candles that already ran too far (chasing)
    if (h - l) > 2.5 * atr_e:
        return no_signal("Entry candle too extended")

    # ---------------------------------------------------------
    # 15M TRIGGER
    # Pullback = within the last 4 candles price touched EMA9
    # Reclaim/Reject = current candle closes back beyond EMA9
    # ---------------------------------------------------------

    recent = ce[i - 4:i]

    try:
        pulled_back_long = any(
            float(c["low"]) <= ema9_e[i - 4 + k] for k, c in enumerate(recent)
        )
        pulled_back_short = any(
            float(c["high"]) >= ema9_e[i - 4 + k] for k, c in enumerate(recent)
        )
    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    long_signal = (
        trend_up
        and ema9_e[i] > ema21_e[i]
        and pulled_back_long
        and entry > ema9_e[i]
        and entry > o
        and 45 <= current_rsi <= 70
    )

    short_signal = (
        trend_down
        and ema9_e[i] < ema21_e[i]
        and pulled_back_short
        and entry < ema9_e[i]
        and entry < o
        and 30 <= current_rsi <= 55
    )

    if not long_signal and not short_signal:
        if trend_up:
            return no_signal("1H uptrend, waiting for 15m pullback + EMA9 reclaim")
        return no_signal("1H downtrend, waiting for 15m pullback + EMA9 rejection")

    # ---------------------------------------------------------
    # STOP LOSS / TAKE PROFIT (day trade, RR >= 1:2)
    # Stop goes beyond the last 12 hours of 1H swing, kept between
    # max(2x 1H ATR, MIN_STOP_PCT) and a cap (4x 1H ATR, MAX_STOP_PCT).
    # ---------------------------------------------------------

    stop_floor = max(2.0 * atr_h, MIN_STOP_PCT * entry)
    stop_cap = max(stop_floor, min(max(4.0 * atr_h, 1.5 * stop_floor), MAX_STOP_PCT * entry))

    swing = ch[-12:]

    if long_signal:
        direction = "LONG"
        swing_low = min(float(c["low"]) for c in swing)
        raw_stop = swing_low - 0.5 * atr_h
        risk = entry - raw_stop
        risk = min(max(risk, stop_floor), stop_cap)
        stop_loss = entry - risk
    else:
        direction = "SHORT"
        swing_high = max(float(c["high"]) for c in swing)
        raw_stop = swing_high + 0.5 * atr_h
        risk = raw_stop - entry
        risk = min(max(risk, stop_floor), stop_cap)
        stop_loss = entry + risk

    sign = 1 if direction == "LONG" else -1
    tp1 = entry + sign * rr * risk
    tp2 = entry + sign * (rr + 1.0) * risk
    tp3 = entry + sign * (rr + 2.0) * risk

    if risk <= 0 or stop_loss <= 0 or tp1 <= 0:
        return no_signal("Invalid risk geometry")

    # ---------------------------------------------------------
    # POSITION SIZE + LEVERAGE
    # Max loss at stop = risk_percent of capital.
    #   notional = max_loss / stop_distance_pct
    #   leverage = notional / capital (rounded up, capped)
    #   margin   = notional / leverage  (USDT to commit)
    # ---------------------------------------------------------

    risk_amount = capital * (risk_percent / 100.0)
    stop_pct = risk / entry

    notional_target = risk_amount / stop_pct

    # Leverage cap: user's max, and a liquidation-safety limit so the
    # stop is hit well before liquidation (~80% of 1/leverage).
    safe_leverage = max(1, int(math.floor(0.8 / stop_pct)))
    effective_max_leverage = max(1.0, min(float(max_leverage), float(safe_leverage)))

    notional = min(notional_target, capital * effective_max_leverage)
    leverage_used = int(min(max(1, math.ceil(notional / capital)), effective_max_leverage))
    leverage_used = max(1, leverage_used)

    position_qty = notional / entry
    margin_usdt = notional / leverage_used
    estimated_loss = notional * stop_pct
    profit_tp1 = notional * stop_pct * rr
    profit_tp2 = notional * stop_pct * (rr + 1.0)

    # ---------------------------------------------------------
    # CONFIDENCE SCORE
    # ---------------------------------------------------------

    confidence = 60

    if volume_confirmed:
        confidence += 10

    # Strong 1H trend separation
    if abs(ema20_h[j] - ema50_h[j]) / close_h[j] >= 0.003:
        confidence += 8

    # RSI in momentum sweet spot
    if direction == "LONG" and 52 <= current_rsi <= 65:
        confidence += 7
    if direction == "SHORT" and 35 <= current_rsi <= 48:
        confidence += 7

    # Price on the right side of the 1H EMA20
    if (direction == "LONG" and close_h[j] > ema20_h[j]) or (
        direction == "SHORT" and close_h[j] < ema20_h[j]
    ):
        confidence += 5

    confidence = min(confidence, 90)

    if confidence < min_confidence:
        return no_signal(f"Confidence {confidence} below minimum {min_confidence}")

    # ---------------------------------------------------------
    # RETURN SIGNAL
    # ---------------------------------------------------------

    return {
        "symbol": symbol,
        "signal": direction,
        # The Android app treats status == "SIGNAL" as an active call
        "status": "SIGNAL",
        "side": direction,

        "entry": round(entry, 8),
        "tp1": round(tp1, 8),
        "tp2": round(tp2, 8),
        "tp3": round(tp3, 8),
        "sl": round(stop_loss, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(tp1, 8),

        "rr": float(rr),
        "confidence": confidence,
        "confidence_score": confidence,

        "capital": round(capital, 2),
        "capital_usdt": round(capital, 2),
        "risk_percent": float(risk_percent),
        "risk_amount": round(risk_amount, 8),
        "risk_budget_usdt": round(risk_amount, 8),
        "estimated_loss": round(estimated_loss, 8),
        "estimated_risk_at_sl_usdt": round(estimated_loss, 8),

        "position_qty": round(position_qty, 8),
        "position_value": round(notional, 8),
        "notional_usdt": round(notional, 8),
        "margin_usdt": round(margin_usdt, 4),
        "stop_distance_pct": round(stop_pct * 100, 3),
        "estimated_profit_tp1_usdt": round(profit_tp1, 8),
        "estimated_profit_tp2_usdt": round(profit_tp2, 8),

        "max_leverage": float(max_leverage),
        "leverage": float(leverage_used),

        "trend_1h": trend,

        "reason": (
            "1H trend + 15m EMA9 pullback/"
            + ("reclaim" if direction == "LONG" else "rejection")
            + (" + volume confirmation" if volume_confirmed else "")
            + " · day trade, hold sampai TP/SL"
        ),

        "timeframe_entry": "15m",
        "timeframe_trend": "1h",

        "indicators": indicators_out,
    }
