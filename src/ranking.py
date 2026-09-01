from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _count_long_short_votes(confluence: Dict[str, Any] | None) -> Dict[str, float]:
    votes = {"long": 0.0, "short": 0.0, "neutral": 0.0}
    if not isinstance(confluence, dict):
        return votes
    for value in confluence.values():
        direction = str(value).lower()
        if direction in {"long", "short"}:
            votes[direction] += 1.0
        else:
            votes["neutral"] += 1.0
    return votes


def rank_symbol_signals(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol", "UNKNOWN"))
        score = float(candidate.get("score", 0.0) or 0.0)
        confidence = float(candidate.get("confidence", 0.0) or 0.0)
        direction = str(candidate.get("direction", "neutral")).lower()
        regime = str(candidate.get("regime", "mixed")).lower()
        confluence = candidate.get("confluence") or {}
        votes = _count_long_short_votes(confluence)

        confluence_score = max(votes["long"], votes["short"]) / max(1.0, sum(votes.values())) * 100.0
        regime_bonus = 0.0
        if regime in {"trending", "high_volatility"}:
            regime_bonus = 10.0
        elif regime == "accumulation":
            regime_bonus = 4.0

        priority = score * 0.55 + confidence * 100.0 * 0.25 + confluence_score * 0.2 + regime_bonus
        if direction == "short":
            priority *= 0.98

        ranked.append({
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "confidence": confidence,
            "confluence": confluence,
            "regime": regime,
            "priority": round(priority, 2),
        })

    ranked.sort(key=lambda item: item["priority"], reverse=True)
    return ranked


def select_top_priority_signals(candidates: Iterable[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    return rank_symbol_signals(candidates)[:limit]
