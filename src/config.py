import json
import os
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")


def _split_csv(value: str | None, default: List[str]) -> List[str]:
    if not value:
        return default
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _load_weights() -> Dict[str, float]:
    root = Path(__file__).resolve().parents[1]
    default_weights = {
        "liquidity_sweep": 1.0,
        "funding_extreme": 1.0,
        "order_book_imbalance": 1.0,
        "cross_exchange_divergence": 1.0,
        "liquidation_heatmap": 0.8,
        "whale_wallet_tracking": 0.7,
        "basis_spread": 0.8,
        "taker_buy_sell_ratio": 0.7,
        "long_short_ratio": 0.9,
    }

    weight_file = root / "weights.json"
    if not weight_file.exists():
        return default_weights

    try:
        with weight_file.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            merged = default_weights.copy()
            merged.update({key: float(value) for key, value in loaded.items() if isinstance(value, (int, float, str))})
            return merged
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass

    return default_weights


class AppConfig:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    SYMBOLS = _split_csv(os.getenv("SYMBOLS"), ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    EXCHANGES = _split_csv(
        os.getenv("EXCHANGES"),
        ["BINANCE", "OKX", "BYBIT", "BINGX", "KUCOIN", "BITGET", "MEXC"],
    )
    POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
    THRESHOLD = float(os.getenv("THRESHOLD", "60"))
    USE_FUTURES = os.getenv("USE_FUTURES", "True").lower() in {"1", "true", "yes", "y"}
    ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "900"))
    ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "True").lower() in {"1", "true", "yes", "y"}
    LOG_PATH = Path(os.getenv("LOG_PATH", "logs/signals.jsonl"))
    WEIGHTS = _load_weights()


CONFIG = AppConfig()
