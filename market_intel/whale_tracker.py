import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def inspect_whale_trades(symbol: str, trades: List[Dict[str, Any]], usd_threshold: float = 100000.0) -> Dict[str, Any]:
    try:
        buy_count = 0
        buy_usd = 0.0
        sell_count = 0
        sell_usd = 0.0
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            side = str(trade.get("side") or "").lower()
            price = float(trade.get("price", 0.0) or 0.0)
            qty = float(trade.get("qty", 0.0) or 0.0)
            if price <= 0 or qty <= 0:
                continue
            usd = price * qty
            if usd < usd_threshold:
                continue
            if side == "buy":
                buy_count += 1
                buy_usd += usd
            elif side == "sell":
                sell_count += 1
                sell_usd += usd
        logger.info(
            "%s whale trades 15m: buy_count=%d buy_usd=%.0f sell_count=%d sell_usd=%.0f",
            symbol,
            buy_count,
            buy_usd,
            sell_count,
            sell_usd,
        )
        return {
            "symbol": symbol,
            "buy_count": buy_count,
            "buy_usd": buy_usd,
            "sell_count": sell_count,
            "sell_usd": sell_usd,
        }
    except Exception:
        logger.exception("%s whale trade tracking failed", symbol)
        return {"symbol": symbol, "buy_count": 0, "buy_usd": 0.0, "sell_count": 0, "sell_usd": 0.0}
