import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def calculate_cvd_from_trades(trades: List[Dict[str, Any]], window_minutes: int = 60) -> Dict[str, Any]:
    """Observation-only helper for rolling CVD using taker volume deltas."""
    if not isinstance(trades, list):
        return {"cvd_1h": 0.0, "cvd_4h": 0.0, "price_change_pct": 0.0, "divergence": "none"}

    values: List[float] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        side = str(trade.get("side") or "").lower()
        qty = float(trade.get("qty", 0.0) or 0.0)
        price = float(trade.get("price", 0.0) or 0.0)
        if price <= 0 or qty <= 0:
            continue
        delta = qty if side == "buy" else -qty
        values.append(delta)
    rolling_1h = sum(values[-max(1, window_minutes):])
    rolling_4h = sum(values[-max(1, window_minutes * 4):])
    return {"cvd_1h": rolling_1h, "cvd_4h": rolling_4h, "price_change_pct": 0.0, "divergence": "none"}


def inspect_cvd(symbol: str, trades: List[Dict[str, Any]], price_change_pct: float = 0.0) -> Dict[str, Any]:
    try:
        cvd = calculate_cvd_from_trades(trades, window_minutes=60)
        cvd["price_change_pct"] = float(price_change_pct)
        divergence = "none"
        if price_change_pct > 0 and cvd["cvd_1h"] < 0:
            divergence = "bearish_divergence"
        elif price_change_pct < 0 and cvd["cvd_1h"] > 0:
            divergence = "bullish_divergence"
        cvd["divergence"] = divergence
        logger.info(
            "%s CVD 1h=%.0f 4h=%.0f price_change=%.2f%% divergence=%s",
            symbol,
            cvd["cvd_1h"],
            cvd["cvd_4h"],
            price_change_pct,
            divergence,
        )
        return {"symbol": symbol, "cvd": cvd}
    except Exception:
        logger.exception("%s CVD analysis failed", symbol)
        return {"symbol": symbol, "cvd": {"cvd_1h": 0.0, "cvd_4h": 0.0, "price_change_pct": 0.0, "divergence": "none"}}
