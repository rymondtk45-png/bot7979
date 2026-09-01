import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def detect_spoofing(events: List[Dict[str, Any]], vanish_seconds: float = 5.0) -> List[Dict[str, Any]]:
    """Skeleton: compare order book depth snapshots over time and flag transient large levels."""
    if not isinstance(events, list):
        return []
    suspects: List[Dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("size") and event.get("appeared_at") and event.get("vanished_at"):
            duration = float(event.get("vanished_at", 0.0) or 0.0) - float(event.get("appeared_at", 0.0) or 0.0)
            if duration <= vanish_seconds:
                suspects.append({
                    "price": float(event.get("price", 0.0) or 0.0),
                    "size": float(event.get("size", 0.0) or 0.0),
                    "appeared_at": event.get("appeared_at"),
                    "vanished_at": event.get("vanished_at"),
                    "duration_s": duration,
                })
    return suspects


def inspect_spoofing(symbol: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        suspects = detect_spoofing(events)
        if suspects:
            first = suspects[0]
            logger.info(
                "%s spoofing suspect: price=%.4f size=%.0f appeared_at=%s vanished_at=%s duration_s=%.1f",
                symbol,
                float(first.get("price", 0.0) or 0.0),
                float(first.get("size", 0.0) or 0.0),
                first.get("appeared_at"),
                first.get("vanished_at"),
                float(first.get("duration_s", 0.0) or 0.0),
            )
        else:
            logger.info("%s spoofing suspect: none detected in current window", symbol)
        return {"symbol": symbol, "suspects": suspects}
    except Exception:
        logger.exception("%s spoofing detection failed", symbol)
        return {"symbol": symbol, "suspects": []}
