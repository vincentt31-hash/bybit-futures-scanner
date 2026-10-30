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
    Scalping strategy:
    - Entry timeframe: 1 minute
    - Trend filter: 5 minutes
    - Risk reward: 1:2
    - Signal only, no order execution
    """

    symbol = str(symbol).upper().replace("/", "").replace(".P", "")

    def no_signal(reason: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "signal": "NO_SIGNAL",
            "status": "NO_SIGNAL",
            "reason": reason,
            "timeframe_entry": "1m",
            "timeframe_trend": "5m",
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

    # Exclude the latest candle if it is still forming.
    if include_latest:
        c5 = candles_5m
        c1 = candles_1m
    else:
        c5 = candles_5m[:-1]
        c1 = candles_1m[:-1]

    if len(c5) < 60 or len(c1) < 40:
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
        ema20_5m[j],
        ema50_5m[j],
        ema9_1m[i],
        ema21_1m[i],
        rsi1m[i],
        atr1m[i],
        ema9_1m[i - 1],
    ]

    if any(value is None for value in required):
        return no_signal("Indicators not ready")

    # ---------------------------------------------------------
    # CURRENT CANDLE
    # ---------------------------------------------------------

    last = c1[i]
    previous = c1[i - 1]

    entry = float(last["close"])
    current_atr = float(atr1m[i])
    current_rsi = float(rsi1m[i])

    if entry <= 0 or current_atr <= 0:
        return no_signal("Invalid ATR or entry price")

    # ---------------------------------------------------------
    # 5M TREND FILTER
    # ---------------------------------------------------------

    trend_up = (
        close5[j] > ema20_5m[j] > ema50_5m[j]
    )

    trend_down = (
        close5[j] < ema20_5m[j] < ema50_5m[j]
    )

    # ---------------------------------------------------------
    # VOLUME FILTER
    # ---------------------------------------------------------

    try:
        volumes = [
            float(c.get("volume", 0))
            for c in c1
        ]
    except (TypeError, ValueError):
        return no_signal("Invalid volume data")

    average_volume = (
        sum(volumes[-21:-1]) / 20
        if len(volumes) >= 21
        else 0
    )

    volume_confirmed = (
        average_volume > 0
        and volumes[i] >= average_volume * 1.05
    )

    # ---------------------------------------------------------
    # LONG SETUP
    # ---------------------------------------------------------

    long_signal = (
        trend_up
        and ema9_1m[i] > ema21_1m[i]

        # Pullback toward EMA9
        and float(previous["close"]) <= ema9_1m[i - 1]

        # Reclaim EMA9
        and entry > ema9_1m[i]

        # Bullish candle
        and float(last["close"]) > float(last["open"])

        # Avoid chasing overbought price
        and 50 <= current_rsi <= 68
    )

    # ---------------------------------------------------------
    # SHORT SETUP
    # ---------------------------------------------------------

    short_signal = (
        trend_down
        and ema9_1m[i] < ema21_1m[i]

        # Pullback toward EMA9
        and float(previous["close"]) >= ema9_1m[i - 1]

        # Rejection below EMA9
        and entry < ema9_1m[i]

        # Bearish candle
        and float(last["close"]) < float(last["open"])

        # Avoid chasing oversold price
        and 32 <= current_rsi <= 50
    )

    # ---------------------------------------------------------
    # FILTER VALIDATION
    # ---------------------------------------------------------

    if not volume_confirmed:
        return no_signal("Volume filter not met")

    if not long_signal and not short_signal:
        return no_signal("No aligned 1m pullback trigger")

    # ---------------------------------------------------------
    # DIRECTION AND RISK
    # ---------------------------------------------------------

    if long_signal:
        direction = "LONG"

        stop_loss = min(
            float(last["low"]),
            entry - 1.2 * current_atr,
        )

        risk = entry - stop_loss

        take_profit = entry + min_rr * risk

    else:
        direction = "SHORT"

        stop_loss = max(
            float(last["high"]),
            entry + 1.2 * current_atr,
        )

        risk = stop_loss - entry

        take_profit = entry - min_rr * risk

    if risk <= 0 or take_profit <= 0:
        return no_signal("Invalid risk geometry")

    # ---------------------------------------------------------
    # POSITION SIZE
    # ---------------------------------------------------------

    risk_amount = capital * (risk_percent / 100.0)

    # Quantity based on the risk budget and stop-loss distance.
    position_qty = risk_amount / risk

    # Cap notional exposure using the requested leverage.
    max_position_value = capital * max_leverage
    max_position_qty = max_position_value / entry

    position_qty = min(position_qty, max_position_qty)

    position_value = position_qty * entry

    estimated_loss = position_qty * risk

    # ---------------------------------------------------------
    # CONFIDENCE SCORE
    # ---------------------------------------------------------

    confidence = 78

    if volume_confirmed:
        confidence += 5

    if abs(current_rsi - 50) >= 5:
        confidence += 3

    confidence = min(confidence, 88)

    if confidence < min_confidence:
        return no_signal(
            f"Confidence {confidence} below minimum {min_confidence}"
        )

    # ---------------------------------------------------------
    # RETURN SIGNAL
    # ---------------------------------------------------------
    trend_5m = (
        "UP" if trend_up
        else "DOWN" if trend_down
        else "SIDEWAYS"
    )

    indicator_data = {
        "ema20_5m": round(float(ema20_5m[j]), 8),
        "ema50_5m": round(float(ema50_5m[j]), 8),
        "ema9_1m": round(float(ema9_1m[i]), 8),
        "ema21_1m": round(float(ema21_1m[i]), 8),
        "rsi_1m": round(float(rsi1m[i]), 4),
        "atr_1m": round(float(atr1m[i]), 8),
        "trend_5m": trend_5m,
        "volume_confirmed": volume_confirmed,
    }

    return {
        "symbol": symbol,
        "signal": direction,
        "status": direction,

        "entry": round(entry, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),

        "rr": float(min_rr),
        "confidence": confidence,

        "capital": round(capital, 2),
        "risk_percent": float(risk_percent),
        "risk_amount": round(risk_amount, 8),

        "position_qty": round(position_qty, 8),
        "position_value": round(position_value, 8),
        "estimated_loss": round(estimated_loss, 8),

        "max_leverage": float(max_leverage),

        "reason": (
            "5m trend + 1m EMA pullback/reclaim "
            "+ volume confirmation"
        ),

        "timeframe_entry": "1m",
        "timeframe_trend": "5m",

        "indicators": indicator_data,
    }