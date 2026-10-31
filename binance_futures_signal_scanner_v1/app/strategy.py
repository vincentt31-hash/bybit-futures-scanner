import math
from typing import Any, Dict, List

from .indicators import ema, rsi, atr

# Hard floor: the strategy never returns a trade with RR below 1:2.
MIN_RR_FLOOR = 2.0


def analyze(
    symbol: str,
    candles_5m: List[Dict[str, Any]],
    candles_1m: List[Dict[str, Any]],
    capital: float = 100.0,
    risk_percent: float = 1.0,
    max_leverage: float = 10.0,
    min_confidence: int = 0,
    min_rr: float = 2.0,
    include_latest: bool = False,
) -> Dict[str, Any]:
    """
    Scalping strategy (LONG and SHORT):
    - Trend filter : 5m  (EMA20 vs EMA50 + price vs EMA50)
    - Entry        : 1m  (pullback to EMA9/EMA21, then reclaim/reject EMA9)
    - Risk reward  : minimum 1:2 (never lower)
    - Leverage     : position size capped by max_leverage, and by a
                     liquidation-safety limit based on stop distance
    - Signal only, no order execution
    """

    symbol = str(symbol).upper().replace("/", "").replace(".P", "")

    # indicators object is ALWAYS returned (null until calculated)
    indicators_out: Dict[str, Any] = {
        "ema20_5m": None,
        "ema50_5m": None,
        "ema9_1m": None,
        "ema21_1m": None,
        "rsi_1m": None,
        "atr_1m": None,
        "trend_5m": None,
        "volume_confirmed": None,
    }

    def no_signal(reason: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "signal": "NO_SIGNAL",
            "status": "NO_SIGNAL",
            "reason": reason,
            "timeframe_entry": "1m",
            "timeframe_trend": "5m",
            "indicators": indicators_out,
        }

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    if not candles_5m or not candles_1m:
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
        c5 = candles_5m
        c1 = candles_1m
    else:
        c5 = candles_5m[:-1]
        c1 = candles_1m[:-1]

    if len(c5) < 55 or len(c1) < 40:
        return no_signal("Insufficient closed candles")

    # ---------------------------------------------------------
    # PRICE DATA
    # ---------------------------------------------------------

    try:
        close5 = [float(c["close"]) for c in c5]
        close1 = [float(c["close"]) for c in c1]

        if any(price <= 0 for price in close5 + close1):
            return no_signal("Invalid candle price")

    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    # ---------------------------------------------------------
    # INDICATORS
    # ---------------------------------------------------------

    ema20_5m = ema(close5, 20)
    ema50_5m = ema(close5, 50)

    ema9_1m = ema(close1, 9)
    ema21_1m = ema(close1, 21)

    rsi1m = rsi(close1, 14)
    atr1m = atr(c1, 14)

    i = len(c1) - 1
    j = len(c5) - 1

    required = [
        ema20_5m[j], ema50_5m[j], ema9_1m[i], ema21_1m[i],
        rsi1m[i], atr1m[i],
    ]
    if any(value is None for value in required):
        return no_signal("Indicators not ready")

    try:
        last = c1[i]
        o = float(last["open"])
        h = float(last["high"])
        l = float(last["low"])
        entry = float(last["close"])
    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    current_atr = float(atr1m[i])
    current_rsi = float(rsi1m[i])

    # ---------------------------------------------------------
    # 5M TREND FILTER (looser than before: no need for
    # close > EMA20 > EMA50 strictly, just EMA20/EMA50 order
    # and price on the right side of EMA50)
    # ---------------------------------------------------------

    trend_up = ema20_5m[j] > ema50_5m[j] and close5[j] > ema50_5m[j]
    trend_down = ema20_5m[j] < ema50_5m[j] and close5[j] < ema50_5m[j]
    trend_5m = "UP" if trend_up else "DOWN" if trend_down else "SIDEWAYS"

    # ---------------------------------------------------------
    # VOLUME (soft factor: boosts confidence, not a hard block)
    # ---------------------------------------------------------

    try:
        volumes = [float(c.get("volume", 0)) for c in c1]
    except (TypeError, ValueError):
        return no_signal("Invalid volume data")

    average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0
    volume_confirmed = average_volume > 0 and volumes[i] >= average_volume * 1.0

    indicators_out.update({
        "ema20_5m": round(float(ema20_5m[j]), 8),
        "ema50_5m": round(float(ema50_5m[j]), 8),
        "ema9_1m": round(float(ema9_1m[i]), 8),
        "ema21_1m": round(float(ema21_1m[i]), 8),
        "rsi_1m": round(current_rsi, 4),
        "atr_1m": round(current_atr, 8),
        "trend_5m": trend_5m,
        "volume_confirmed": volume_confirmed,
    })

    if entry <= 0 or current_atr <= 0:
        return no_signal("Invalid ATR or entry price")

    if trend_5m == "SIDEWAYS":
        return no_signal("5m trend is sideways")

    # Skip candles that already ran too far (chasing)
    if (h - l) > 2.5 * current_atr:
        return no_signal("Entry candle too extended")

    # ---------------------------------------------------------
    # 1M TRIGGER
    # Pullback = within the last 3 candles price touched EMA9
    # Reclaim/Reject = current candle closes back beyond EMA9
    # ---------------------------------------------------------

    recent = c1[i - 3:i]

    try:
        pulled_back_long = any(
            float(c["low"]) <= ema9_1m[i - 3 + k] for k, c in enumerate(recent)
        )
        pulled_back_short = any(
            float(c["high"]) >= ema9_1m[i - 3 + k] for k, c in enumerate(recent)
        )
    except (KeyError, TypeError, ValueError):
        return no_signal("Invalid candle format")

    long_signal = (
        trend_up
        and ema9_1m[i] > ema21_1m[i]
        and pulled_back_long
        and entry > ema9_1m[i]
        and entry > o
        and 45 <= current_rsi <= 70
    )

    short_signal = (
        trend_down
        and ema9_1m[i] < ema21_1m[i]
        and pulled_back_short
        and entry < ema9_1m[i]
        and entry < o
        and 30 <= current_rsi <= 55
    )

    if not long_signal and not short_signal:
        if trend_up:
            return no_signal("5m uptrend, waiting for 1m pullback + EMA9 reclaim")
        return no_signal("5m downtrend, waiting for 1m pullback + EMA9 rejection")

    # ---------------------------------------------------------
    # STOP LOSS / TAKE PROFIT (RR >= 1:2)
    # Stop goes beyond the recent swing, clamped to 0.8x-2.0x ATR
    # so it is neither noise-tight nor too wide.
    # ---------------------------------------------------------

    swing_window = c1[i - 4:i + 1]

    if long_signal:
        direction = "LONG"
        swing_low = min(float(c["low"]) for c in swing_window)
        raw_stop = swing_low - 0.1 * current_atr
        risk = entry - raw_stop
        risk = min(max(risk, 0.8 * current_atr), 2.0 * current_atr)
        stop_loss = entry - risk
        take_profit = entry + rr * risk
    else:
        direction = "SHORT"
        swing_high = max(float(c["high"]) for c in swing_window)
        raw_stop = swing_high + 0.1 * current_atr
        risk = raw_stop - entry
        risk = min(max(risk, 0.8 * current_atr), 2.0 * current_atr)
        stop_loss = entry + risk
        take_profit = entry - rr * risk

    if risk <= 0 or stop_loss <= 0 or take_profit <= 0:
        return no_signal("Invalid risk geometry")

    # ---------------------------------------------------------
    # POSITION SIZE + LEVERAGE
    # ---------------------------------------------------------

    risk_amount = capital * (risk_percent / 100.0)
    position_qty = risk_amount / risk

    # Leverage cap: user's max, and a liquidation-safety limit so the
    # stop is hit well before liquidation (~80% of 1/leverage).
    stop_pct = risk / entry
    safe_leverage = max(1, int(math.floor(0.8 / stop_pct)))
    effective_max_leverage = max(1.0, min(float(max_leverage), float(safe_leverage)))

    max_position_qty = (capital * effective_max_leverage) / entry
    position_qty = min(position_qty, max_position_qty)

    position_value = position_qty * entry
    estimated_loss = position_qty * risk
    leverage_used = max(1, int(math.ceil(position_value / capital)))
    leverage_used = int(min(leverage_used, effective_max_leverage))

    # ---------------------------------------------------------
    # CONFIDENCE SCORE
    # ---------------------------------------------------------

    confidence = 60

    if volume_confirmed:
        confidence += 10

    # Strong 5m trend separation
    if abs(ema20_5m[j] - ema50_5m[j]) / close5[j] >= 0.001:
        confidence += 8

    # RSI in momentum sweet spot
    if direction == "LONG" and 52 <= current_rsi <= 65:
        confidence += 7
    if direction == "SHORT" and 35 <= current_rsi <= 48:
        confidence += 7

    # Price on the right side of the 5m EMA20
    if (direction == "LONG" and close5[j] > ema20_5m[j]) or (
        direction == "SHORT" and close5[j] < ema20_5m[j]
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
        "status": direction,

        "entry": round(entry, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),

        "rr": float(rr),
        "confidence": confidence,

        "capital": round(capital, 2),
        "risk_percent": float(risk_percent),
        "risk_amount": round(risk_amount, 8),

        "position_qty": round(position_qty, 8),
        "position_value": round(position_value, 8),
        "estimated_loss": round(estimated_loss, 8),

        "max_leverage": float(max_leverage),
        "leverage": leverage_used,

        "reason": (
            "5m trend + 1m EMA9 pullback/"
            + ("reclaim" if direction == "LONG" else "rejection")
            + (" + volume confirmation" if volume_confirmed else "")
        ),

        "timeframe_entry": "1m",
        "timeframe_trend": "5m",

        "indicators": indicators_out,
    }
