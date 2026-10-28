import os

# Bybit Global V5 API; override only if intentionally using another region.
BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.id").rstrip("/")

DEFAULT_CAPITAL = float(os.getenv("CAPITAL_USDT", "100"))
DEFAULT_RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "20"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "75"))

# Active Bybit Indonesia USDT spot pairs only.
WATCHLIST = [
    s.strip().upper().replace("/", "").replace(".P", "")
    for s in os.getenv("WATCHLIST", "BTCUSDT,ETHUSDT,SOLUSDT").split(",")
    if s.strip()
]
AUTO_TOP_VOLUME = os.getenv("AUTO_TOP_VOLUME", "true").lower() in ("1", "true", "yes")
TOP_PAIR_COUNT = int(os.getenv("TOP_PAIR_COUNT", "50"))
QUOTE_COIN = "USDT"
