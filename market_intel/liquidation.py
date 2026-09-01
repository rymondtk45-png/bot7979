import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def normalize_side(value: Any) -> str:
    side = str(value or "").upper()
    return side if side in {"BUY", "SELL"} else "UNKNOWN"


def compute_liquidation_cluster(events: List[Dict[str, Any]], window_seconds: int = 300, price_tolerance: float = 0.01) -> Dict[str, Any]:
    """Observation-only helper: group nearby liquidation events by side within a short window."""
    if not isinstance(events, list):
        return {"side": "neutral", "count": 0, "total_usd": 0.0, "price_range": (0.0, 0.0), "clustered": False}

    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        if not isinstance(event, dict):
            continue
        side = normalize_side(event.get("side"))
        if side == "UNKNOWN":
            continue
        ts = float(event.get("timestamp", 0) or 0)
        price = float(event.get("price", 0) or 0)
        if ts <= 0 or price <= 0:
            continue
        buckets[side].append({"timestamp": ts, "price": price, "size": float(event.get("size", 0) or 0)})

    best: Dict[str, Any] = {"side": "neutral", "count": 0, "total_usd": 0.0, "price_range": (0.0, 0.0), "clustered": False}
    for side, items in buckets.items():
        items.sort(key=lambda item: item["timestamp"])
        window: List[Dict[str, Any]] = []
        for item in items:
            window.append(item)
            while window and item["timestamp"] - window[0]["timestamp"] > window_seconds:
                window.pop(0)
            if len(window) < 2:
                continue
            prices = [row["price"] for row in window]
            low = min(prices)
            high = max(prices)
            if high <= 0:
                continue
            if (high - low) <= max(price_tolerance * min(prices or [1.0]), 0.0001):
                total_usd = sum(float(row["size"]) for row in window)
                if len(window) > best["count"] or (len(window) == best["count"] and total_usd > best["total_usd"]):
                    best = {
                        "side": side,
                        "count": len(window),
                        "total_usd": total_usd,
                        "price_range": (low, high),
                        "clustered": True,
                    }
    return best


def inspect_liquidation_feed(symbol: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        cluster = compute_liquidation_cluster(events)
        if cluster.get("clustered"):
            side = cluster.get("side", "neutral")
            count = int(cluster.get("count", 0))
            total_usd = float(cluster.get("total_usd", 0.0))
            lo, hi = cluster.get("price_range", (0.0, 0.0))
            logger.info(
                "%s liquidation cluster: side=%s count=%d total_usd=%.0f price_range=%.4f-%.4f",
                symbol,
                side,
                count,
                total_usd,
                lo,
                hi,
            )
        else:
            logger.info("%s liquidation cluster: side=neutral count=0 total_usd=0 price_range=0.0000-0.0000", symbol)
        return {"symbol": symbol, "cluster": cluster}
    except Exception:
        logger.exception("%s liquidation cluster analysis failed", symbol)
        return {"symbol": symbol, "cluster": {"side": "neutral", "count": 0, "total_usd": 0.0, "price_range": (0.0, 0.0), "clustered": False}}
