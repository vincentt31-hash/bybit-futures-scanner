from math import isfinite


def ema(values, period):
    if not values or period <= 0:
        return []
    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def sma(values, period):
    out = []
    for i in range(len(values)):
        start = max(0, i - period + 1)
        window = values[start:i + 1]
        out.append(sum(window) / len(window))
    return out


def rsi(values, period=14):
    if len(values) < period + 1:
        return [50.0] * len(values)
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out = [50.0] * period
    def calc(g, l):
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - (100 / (1 + g / l))
    out.append(calc(avg_gain, avg_loss))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out.append(calc(avg_gain, avg_loss))
    # align to values length
    return ([50.0] + out)[:len(values)]


def macd_histogram(values, fast=12, slow=26, signal=9):
    fast_ema, slow_ema = ema(values, fast), ema(values, slow)
    line = [a - b for a, b in zip(fast_ema, slow_ema)]
    signal_line = ema(line, signal)
    return [a - b for a, b in zip(line, signal_line)]


def atr(candles, period=14):
    if not candles:
        return []
    trs = []
    prev_close = candles[0]["close"]
    for c in candles:
        tr = max(
            c["high"] - c["low"],
            abs(c["high"] - prev_close),
            abs(c["low"] - prev_close),
        )
        trs.append(tr)
        prev_close = c["close"]
    return sma(trs, period)


def valid_number(value):
    return isinstance(value, (int, float)) and isfinite(value)
