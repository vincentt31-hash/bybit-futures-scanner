import os

# Bybit V5 market-data API. Override with BYBIT_BASE_URL if needed.
BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.id").rstrip("/")
DEFAULT_CAPITAL = float(os.getenv("CAPITAL_USDT", "100"))
DEFAULT_RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "20"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "75"))
WATCHLIST = [
    s.strip().upper()
    for s in os.getenv(
        "WATCHLIST",
        "BTCUSDT,BNBUSDT,SOLUSDT,ETHUSDT,SUIUSDT,HBARUSDT,ADAUSDT,INJUSDT"
    ).split(",")
    if s.strip()
]

# Dynamic Bybit USDT perpetual universe
AUTO_TOP_VOLUME = os.getenv("AUTO_TOP_VOLUME", "true").lower() in ("1", "true", "yes")
TOP_PAIR_COUNT = int(os.getenv("TOP_PAIR_COUNT", "50"))
