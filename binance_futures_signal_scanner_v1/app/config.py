import os

BASE_URL = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai/api/v1").rstrip("/")
DEFAULT_CAPITAL = float(os.getenv("CAPITAL_USDT", "100"))
DEFAULT_RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1"))
MAX_LEVERAGE = float(os.getenv("MAX_LEVERAGE", "20"))
MIN_CONFIDENCE = int(os.getenv("MIN_CONFIDENCE", "75"))
AUTO_TOP_VOLUME = os.getenv("AUTO_TOP_VOLUME", "true").lower() in ("1", "true", "yes")
TOP_PAIR_COUNT = int(os.getenv("TOP_PAIR_COUNT", "50"))

# Optional comma-separated Lighter market names or IDs. Empty means dynamic markets.
WATCHLIST = [s.strip() for s in os.getenv("WATCHLIST", "").split(",") if s.strip()]
