import math
from typing import Any, Dict, List, Tuple


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rolling_percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(0, min(len(sorted_values) - 1, int(round((percentile / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[rank]


def estimate_market_regime(snapshot: Dict[str, Any]) -> str:
    klines = snapshot.get("klines", [])
    if len(klines) < 30:
        return "accumulation"

    closes = get_recent_closes(klines)
    if len(closes) < 20:
        return "accumulation"

    last_price = closes[-1]
    recent_window = closes[-20:]
    recent_high = max(recent_window)
    recent_low = min(recent_window)
    atr = atr_from_klines(klines, period=14)
    price = price_from_klines(klines)
    if price <= 0:
        return "accumulation"

    vol_ratio = atr / price
    trend_strength = abs(recent_window[-1] - recent_window[0]) / max(abs(recent_window[0]), 1e-8)
    bb_width = (recent_high - recent_low) / max(last_price, 1e-8)

    if vol_ratio > 0.012 or bb_width > 0.02:
        return "high_volatility"
    if trend_strength > 0.015:
        return "trending"
    return "accumulation"


def adaptive_threshold(snapshot: Dict[str, Any], metric: str) -> float:
    regime = estimate_market_regime(snapshot)
    base = {
        "funding": {"accumulation": 0.00045, "trending": 0.0007, "high_volatility": 0.0011},
        "imbalance": {"accumulation": 0.14, "trending": 0.18, "high_volatility": 0.22},
    }.get(metric, {}).get(regime, 0.0007)

    if metric == "funding":
        history = snapshot.get("funding_history") or [snapshot.get("fundingRate", 0.0)]
        if history:
            p90 = rolling_percentile([safe_float(item) for item in history], 90)
            base = max(base, abs(p90) * 1.2)
    elif metric == "imbalance":
        history = snapshot.get("imbalance_history") or [order_book_imbalance(snapshot.get("bids", []), snapshot.get("asks", []), depth=15)]
        if history:
            p90 = rolling_percentile([safe_float(item) for item in history], 90)
            base = max(base, abs(p90) * 1.2)
    return base


def liquidation_heatmap_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    price = safe_float(snapshot.get("last_price", 0.0))
    oi = safe_float(snapshot.get("openInterest", 0.0))
    if price <= 0 or oi <= 0:
        return "neutral", 0.0, "No liquidation data"

    klines = snapshot.get("klines", [])
    closes = get_recent_closes(klines)
    if len(closes) < 20:
        return "neutral", 0.0, "Insufficient kline history"

    recent = closes[-20:]
    recent_high = max(recent)
    recent_low = min(recent)
    leverage_zone = (oi / 1000.0) * 0.15
    if price >= recent_high * 0.995 and leverage_zone > 0:
        return "short", 70.0, f"Liquidation heatmap suggests heavy long-side leverage near recent highs (OI proxy {oi:.0f})"
    if price <= recent_low * 1.005 and leverage_zone > 0:
        return "long", 70.0, f"Liquidation heatmap suggests heavy short-side leverage near recent lows (OI proxy {oi:.0f})"
    return "neutral", 0.0, "No strong liquidation concentration"


def whale_wallet_tracking_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    whale_inflow = safe_float(snapshot.get("whale_inflow", 0.0))
    whale_outflow = safe_float(snapshot.get("whale_outflow", 0.0))
    if whale_inflow > 0.75 and whale_inflow > whale_outflow:
        return "long", 68.0, "Whale wallet tracking shows large inflows to exchanges; bullish positioning is building"
    if whale_outflow > 0.75 and whale_outflow > whale_inflow:
        return "short", 68.0, "Whale wallet tracking shows large outflows from exchanges; bearish positioning is building"
    return "neutral", 0.0, "Whale flow is balanced"


def basis_spread_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    spot_price = safe_float(snapshot.get("spot_price", 0.0))
    futures_price = safe_float(snapshot.get("futures_price", 0.0))
    if spot_price <= 0 or futures_price <= 0:
        return "neutral", 0.0, "Basis data unavailable"

    basis = ((futures_price - spot_price) / spot_price) * 100.0
    if basis > 0.7:
        return "short", 60.0, f"Basis spread is elevated at {basis:.3f}% — futures premium suggests local top risk"
    if basis < -0.7:
        return "long", 60.0, f"Basis spread is compressed at {basis:.3f}% — futures discount suggests local bottom risk"
    return "neutral", 0.0, "Basis spread is normal"


def taker_buy_sell_ratio_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    ratio = safe_float(snapshot.get("taker_buy_ratio", 0.0))
    if ratio <= 0:
        return "neutral", 0.0, "Taker ratio unavailable"
    if ratio > 1.2:
        return "long", 55.0, f"Taker buy/sell ratio is {ratio:.2f}, indicating aggressive buying"
    if ratio < 0.8:
        return "short", 55.0, f"Taker buy/sell ratio is {ratio:.2f}, indicating aggressive selling"
    return "neutral", 0.0, "Taker ratio is balanced"


def compute_rolling_correlation(series_a: List[float], series_b: List[float], window: int = 100) -> float:
    if len(series_a) < 2 or len(series_b) < 2:
        return 0.0

    recent_a = [safe_float(value) for value in series_a[-window:]]
    recent_b = [safe_float(value) for value in series_b[-window:]]
    if len(recent_a) != len(recent_b) or len(recent_a) < 2:
        min_len = min(len(recent_a), len(recent_b))
        recent_a = recent_a[-min_len:]
        recent_b = recent_b[-min_len:]

    if len(recent_a) < 2 or len(recent_b) < 2:
        return 0.0

    mean_a = sum(recent_a) / len(recent_a)
    mean_b = sum(recent_b) / len(recent_b)
    covariance = 0.0
    variance_a = 0.0
    variance_b = 0.0

    for left, right in zip(recent_a, recent_b):
        diff_a = left - mean_a
        diff_b = right - mean_b
        covariance += diff_a * diff_b
        variance_a += diff_a * diff_a
        variance_b += diff_b * diff_b

    if variance_a <= 0 or variance_b <= 0:
        return 0.0

    corr = covariance / math.sqrt(variance_a * variance_b)
    return max(-1.0, min(1.0, corr))


def get_timeframe_signal(snapshot: Dict[str, Any], module_fn, timeframe: str) -> Tuple[str, float, str]:
    timeframe_klines = (snapshot.get("timeframe_klines") or {}).get(timeframe)
    if not timeframe_klines:
        timeframe_klines = snapshot.get("klines", [])

    tf_snapshot = dict(snapshot)
    tf_snapshot["klines"] = timeframe_klines
    return module_fn(tf_snapshot)


def aggregate_timeframe_confluence(snapshot: Dict[str, Any], module_fn) -> Tuple[str, float, str, Dict[str, str]]:
    timeframes = ["15m", "1h", "4h"]
    votes: Dict[str, int] = {"long": 0, "short": 0, "neutral": 0}
    confluence: Dict[str, str] = {}
    scores: Dict[str, float] = {}

    for timeframe in timeframes:
        direction, score, note = get_timeframe_signal(snapshot, module_fn, timeframe)
        confluence[timeframe] = direction if direction else "neutral"
        scores[timeframe] = score
        if direction and direction != "neutral":
            votes[direction] += 1
        else:
            votes["neutral"] += 1

    long_count = votes.get("long", 0)
    short_count = votes.get("short", 0)
    threshold_met = long_count >= 2 or short_count >= 2
    chosen_direction = "long" if long_count >= 2 else "short" if short_count >= 2 else "neutral"
    __import__("logging").getLogger(__name__).info(
        "%s confluence vote: 15m=%s 1h=%s 4h=%s -> direction=%s (threshold_met=%s)",
        snapshot.get("symbol", "UNKNOWN"),
        confluence.get("15m", "neutral"),
        confluence.get("1h", "neutral"),
        confluence.get("4h", "neutral"),
        chosen_direction,
        threshold_met,
    )
    if long_count >= 2:
        signal_score = max(scores.values()) if scores else 0.0
        multiplier = 1.15 if long_count == 2 else 1.3
        return "long", min(100.0, signal_score * multiplier), "Multi-timeframe long confluence", confluence
    if short_count >= 2:
        signal_score = max(scores.values()) if scores else 0.0
        multiplier = 1.15 if short_count == 2 else 1.3
        return "short", min(100.0, signal_score * multiplier), "Multi-timeframe short confluence", confluence
    return "neutral", 0.0, "No sufficient multi-timeframe confluence", confluence


def price_from_klines(klines: List[List[float]]) -> float:
    if not klines:
        return 0.0
    last = klines[-1]
    if len(last) < 6:
        return 0.0
    return safe_float(last[4])


def get_recent_closes(klines: List[List[float]]) -> List[float]:
    return [safe_float(candle[4]) for candle in klines if len(candle) >= 6]


def atr_from_klines(klines: List[List[float]], period: int = 14) -> float:
    if len(klines) < period + 1:
        return 0.0
    values = []
    for i in range(1, len(klines)):
        prev_close = safe_float(klines[i - 1][4])
        curr_high = safe_float(klines[i][2])
        curr_low = safe_float(klines[i][3])
        tr = max(curr_high - curr_low, abs(curr_high - prev_close), abs(curr_low - prev_close))
        values.append(tr)
    if not values:
        return 0.0
    return sum(values[-period:]) / period


def order_book_imbalance(bids: List[List[str]], asks: List[List[str]], depth: int = 20) -> float:
    bid_total = 0.0
    ask_total = 0.0

    for item in bids[:depth]:
        bid_total += safe_float(item[1])
    for item in asks[:depth]:
        ask_total += safe_float(item[1])

    total = bid_total + ask_total
    if total == 0:
        return 0.0
    return (bid_total - ask_total) / total


def build_risk_levels(price: float, atr: float) -> Tuple[float, float]:
    if price <= 0:
        return 0.0, 0.0
    stop_buffer = max(atr * 0.8, price * 0.005)
    target_buffer = max(atr * 1.5, price * 0.01)
    return stop_buffer, target_buffer


def liquidity_sweep_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    klines = snapshot.get("klines", [])
    closes = get_recent_closes(klines)
    if len(closes) < 20:
        return "neutral", 0.0, "Insufficient data"

    last_price = price_from_klines(klines)
    recent_high = max(closes[-20:])
    recent_low = min(closes[-20:])
    spread = recent_high - recent_low
    if spread <= 0:
        return "neutral", 0.0, "No clear range"

    distance_to_high = (recent_high - last_price) / spread
    distance_to_low = (last_price - recent_low) / spread
    imbalance = order_book_imbalance(snapshot.get("bids", []), snapshot.get("asks", []), depth=10)

    if distance_to_high < 0.12 and imbalance > 0.15:
        return "short", 72.0, "Price near recent highs with weak bids and order-book imbalance; risk of liquidity sweep down"
    if distance_to_low < 0.12 and imbalance < -0.15:
        return "long", 72.0, "Price near recent lows with weak asks and order-book imbalance; risk of liquidity sweep up"
    if distance_to_high < 0.22:
        return "short", 54.0, "Near resistance zone, watch for liquidity sweep"
    if distance_to_low < 0.22:
        return "long", 54.0, "Near support zone, watch for liquidity sweep"
    return "neutral", 0.0, "No clear liquidity sweep condition"


def funding_extreme_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    funding_rate = safe_float(snapshot.get("fundingRate", 0.0))
    oi = safe_float(snapshot.get("openInterest", 0.0))
    if oi <= 0:
        return "neutral", 0.0, "Open interest unavailable"
    if funding_rate > 0.0008:
        return "short", 66.0, f"Funding +{funding_rate:.6%} is elevated; crowd is long-heavy"
    if funding_rate < -0.0008:
        return "long", 66.0, f"Funding {funding_rate:.6%} is depressed; crowd is short-heavy"
    return "neutral", 0.0, "Funding not extreme"


def order_book_imbalance_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    imbalance = order_book_imbalance(snapshot.get("bids", []), snapshot.get("asks", []), depth=15)
    if imbalance > 0.18:
        return "long", 58.0, "Top-of-book shows strong bid-side pressure and buy-side dominance"
    if imbalance < -0.18:
        return "short", 58.0, "Top-of-book shows strong ask-side pressure and sell-side dominance"
    return "neutral", 0.0, "Order book imbalance is balanced"


def cross_exchange_divergence_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    exchange_prices = snapshot.get("exchange_prices") or snapshot.get("exchange_aggregate", {}).get("exchange_prices", {})
    if not exchange_prices or len(exchange_prices) < 2:
        return "neutral", 0.0, "Insufficient cross-exchange data"

    values = list(exchange_prices.values())
    avg = sum(values) / len(values)
    spread_pct = ((max(values) - min(values)) / avg) * 100 if avg else 0.0
    if spread_pct < 0.2:
        return "neutral", 0.0, "Cross-exchange prices are aligned"

    dominant = max(exchange_prices.items(), key=lambda item: item[1])
    leading_exchange, leading_price = dominant
    if leading_price > avg * 1.002:
        return "short", 60.0, f"{leading_exchange} is leading price higher than the basket by {spread_pct:.3f}% — watch for local top / sell pressure"
    if leading_price < avg * 0.998:
        return "long", 60.0, f"{leading_exchange} is lagging price lower than the basket by {spread_pct:.3f}% — watch for local bottom / buy pressure"
    return "neutral", 0.0, "Cross-exchange divergence is weak"


def volatility_regime_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    klines = snapshot.get("klines", [])
    atr = atr_from_klines(klines, period=14)
    price = price_from_klines(klines)
    if price <= 0 or atr <= 0:
        return "neutral", 0.0, "No valid volatility data"
    atr_pct = atr / price
    if atr_pct > 0.01:
        return "neutral", 42.0, "High-volatility regime: wider SL, confirm with secondary signal"
    return "neutral", 24.0, "Low-volatility regime: calmer market, tighter risk"


def market_breadth_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    change_24h = safe_float(snapshot.get("change_24h", 0.0))
    volume_24h = safe_float(snapshot.get("volume_24h", 0.0))
    if volume_24h <= 0:
        return "neutral", 0.0, "Volume breadth is unavailable"
    if change_24h > 2.5:
        return "long", 58.0, f"Broad market momentum is strong (+{change_24h:.2f}% 24h) with healthy turnover"
    if change_24h < -2.5:
        return "short", 58.0, f"Broad market momentum is weak ({change_24h:.2f}% 24h) and risk is skewing lower"
    return "neutral", 0.0, "Market breadth is balanced"


def trend_strength_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    klines = snapshot.get("klines", [])
    if len(klines) < 20:
        return "neutral", 0.0, "Insufficient trend data"
    closes = get_recent_closes(klines)
    if len(closes) < 20:
        return "neutral", 0.0, "Insufficient close series"
    recent = closes[-20:]
    price = recent[-1]
    start = recent[0]
    momentum = (price - start) / max(abs(start), 1e-8)
    if momentum > 0.018:
        return "long", 62.0, f"Trend strength is positive at {momentum:.3%} across the recent range"
    if momentum < -0.018:
        return "short", 62.0, f"Trend strength is negative at {momentum:.3%} across the recent range"
    return "neutral", 0.0, "Trend strength is weak or mixed"


def volatility_squeeze_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str]:
    klines = snapshot.get("klines", [])
    if len(klines) < 40:
        return "neutral", 0.0, "Insufficient volatility structure"
    closes = get_recent_closes(klines)
    if len(closes) < 40:
        return "neutral", 0.0, "Not enough closes for squeeze scan"
    recent = closes[-40:]
    price = recent[-1]
    avg_range = sum(abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))) / max(len(recent) - 1, 1)
    if avg_range <= 0:
        return "neutral", 0.0, "Range is too flat for a squeeze read"
    if price > recent[0] * 1.01 and abs(recent[-1] - recent[0]) > avg_range * 2:
        return "long", 56.0, "Volatility squeeze is resolving upward with directional expansion"
    if price < recent[0] * 0.99 and abs(recent[-1] - recent[0]) > avg_range * 2:
        return "short", 56.0, "Volatility squeeze is resolving downward with directional expansion"
    return "neutral", 0.0, "Compression remains indecisive"


def _extract_exchange_weight(snapshot: Dict[str, Any], default_weight: float = 1.0) -> Dict[str, float]:
    exchange_metrics = snapshot.get("exchange_metrics") or {}
    weights: Dict[str, float] = {}
    for exchange in ("BINANCE", "OKX", "BYBIT"):
        metrics = exchange_metrics.get(exchange, {}) if isinstance(exchange_metrics, dict) else {}
        oi = safe_float(metrics.get("open_interest"), 0.0)
        volume = safe_float(metrics.get("volume_24h"), 0.0)
        weight = safe_float(metrics.get("weight"), 0.0)
        if weight <= 0:
            weight = max(oi, volume, 0.0)
        if weight <= 0:
            weight = default_weight
        weights[exchange] = max(weight, default_weight)
    return weights


def _aggregate_long_short_ratio(snapshot: Dict[str, Any], timeframe: str) -> Dict[str, float]:
    ratio_data = snapshot.get("long_short_ratio") or {}
    if not isinstance(ratio_data, dict):
        return {"global_account": 0.5, "top_trader_position": 0.5, "top_trader_account": 0.5}

    weights = _extract_exchange_weight(snapshot, default_weight=1.0)
    totals = {"global_account": [], "top_trader_position": [], "top_trader_account": []}

    for exchange, tf_map in ratio_data.items():
        if not isinstance(tf_map, dict):
            continue
        fresh = tf_map.get(timeframe, {}) if isinstance(tf_map, dict) else {}
        if not isinstance(fresh, dict):
            continue
        for field in ("global_account", "top_trader_position", "top_trader_account"):
            value = safe_float(fresh.get(field), 0.5)
            if value > 0:
                totals[field].append(value * weights.get(exchange.upper(), 1.0))

    def aggregate(field: str) -> float:
        bucket = totals.get(field, [])
        if not bucket:
            return 0.5
        return sum(bucket) / len(bucket)

    return {
        "global_account": aggregate("global_account"),
        "top_trader_position": aggregate("top_trader_position"),
        "top_trader_account": aggregate("top_trader_account"),
    }


def _rolling_long_short_threshold(values: List[float]) -> float:
    if not values:
        return 0.12
    threshold = rolling_percentile(values, 90) - 0.1
    return max(0.12, threshold)


def _long_short_ratio_details(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    ratio_data = snapshot.get("long_short_ratio") or {}
    if not isinstance(ratio_data, dict) or not ratio_data:
        return {
            "aggregated_ratio": 0.5,
            "by_timeframe": {"5m": 0.5, "15m": 0.5, "1h": 0.5, "4h": 0.5, "1d": 0.5},
            "retail_vs_smart_money_divergence": False,
            "score_contribution": 0.0,
        }

    timeframes = ["5m", "15m", "1h", "4h", "1d"]
    by_timeframe: Dict[str, float] = {}
    retail_values: List[float] = []
    smart_values: List[float] = []

    for timeframe in timeframes:
        aggregated = _aggregate_long_short_ratio(snapshot, timeframe)
        retail = aggregated.get("global_account", 0.5)
        smart = (aggregated.get("top_trader_position", 0.5) + aggregated.get("top_trader_account", 0.5)) / 2.0
        by_timeframe[timeframe] = retail
        retail_values.append(retail)
        smart_values.append(smart)

    current_retail = by_timeframe.get("1h", 0.5)
    current_smart = (by_timeframe.get("1h", 0.5) + by_timeframe.get("4h", 0.5)) / 2.0
    if current_retail > 0.5:
        current_smart = sum(smart_values[-3:]) / max(len(smart_values[-3:]), 1)

    momentum_delta = by_timeframe.get("1d", 0.5) - by_timeframe.get("5m", 0.5)
    retail_divergence = abs(current_retail - current_smart)
    threshold = _rolling_long_short_threshold(retail_values + smart_values)
    divergence = (
        current_retail > 0.5 and current_smart < 0.5 and retail_divergence >= threshold
    ) or (
        current_retail < 0.5 and current_smart > 0.5 and retail_divergence >= threshold
    )

    if current_retail > 0.56 and momentum_delta >= 0.02:
        score_contribution = min(100.0, 55.0 + (current_retail - 0.5) * 120.0 + max(0.0, momentum_delta) * 80.0)
    elif current_retail < 0.44 and momentum_delta <= -0.02:
        score_contribution = min(100.0, 55.0 + (0.5 - current_retail) * 120.0 + max(0.0, -momentum_delta) * 80.0)
    else:
        score_contribution = 0.0

    if divergence:
        score_contribution = min(100.0, score_contribution + 20.0)

    return {
        "aggregated_ratio": round(sum(by_timeframe.values()) / max(len(by_timeframe), 1), 4),
        "by_timeframe": {tf: round(value, 4) for tf, value in by_timeframe.items()},
        "retail_vs_smart_money_divergence": divergence,
        "score_contribution": round(score_contribution, 2),
    }


def long_short_ratio_signal(snapshot: Dict[str, Any]) -> Tuple[str, float, str, Dict[str, Any]]:
    details = _long_short_ratio_details(snapshot)
    current_retail = details["by_timeframe"].get("1h", 0.5)
    momentum_delta = details["by_timeframe"].get("1d", 0.5) - details["by_timeframe"].get("5m", 0.5)

    if current_retail > 0.56 and momentum_delta >= 0.02:
        direction = "long"
        score = details["score_contribution"]
    elif current_retail < 0.44 and momentum_delta <= -0.02:
        direction = "short"
        score = details["score_contribution"]
    else:
        direction = "neutral"
        score = 0.0

    if details["retail_vs_smart_money_divergence"]:
        direction = "long" if current_retail > 0.5 else "short"
        score = max(score, details["score_contribution"])

    note = (
        "Strong retail/smart-money divergence suggests contrarian setup"
        if details["retail_vs_smart_money_divergence"]
        else "Retail long/short ratio is trending with smart-money confirmation" if direction != "neutral" else "Long/short ratio remains balanced across timeframes"
    )
    return direction, round(score, 2), note, details


def _reason_matches_direction(reason: str, direction: str) -> bool:
    text = (reason or "").lower()
    if not text:
        return False

    if direction == "long":
        positive_tokens = {
            "long", "bullish", "buy", "upward", "positive", "strong", "higher",
            "support", "bottom", "breakout", "rise", "rising", "lift", "uptrend",
            "buy-side", "aggressive buying", "long-heavy", "short-heavy"
        }
        return any(token in text for token in positive_tokens)

    negative_tokens = {
        "short", "bearish", "sell", "downward", "negative", "weak", "lower",
        "resistance", "top", "downtrend", "sweep down", "sell-side", "aggressive selling",
        "long-heavy", "crowd is long-heavy", "weak bids", "weak asks"
    }
    return any(token in text for token in negative_tokens)


def _select_direction_and_reasons(module_signals: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    if not module_signals:
        return "neutral", ["No module signal triggered"]

    votes = {"long": 0.0, "short": 0.0}
    for mod in module_signals:
        direction = str(mod.get("direction", "neutral")).lower()
        if direction in votes:
            votes[direction] += float(mod.get("score", 0.0) or 0.0)

    direction = "long" if votes["long"] >= votes["short"] else "short"
    reasons = [
        mod.get("note")
        for mod in module_signals
        if mod.get("note") and _reason_matches_direction(str(mod.get("note")), direction)
    ]
    return direction, reasons


def composite_signal(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    module_signals = []
    confluence_map: Dict[str, Dict[str, str]] = {}

    for func in (
        market_breadth_signal,
        trend_strength_signal,
        volatility_squeeze_signal,
        liquidity_sweep_signal,
        funding_extreme_signal,
        order_book_imbalance_signal,
        cross_exchange_divergence_signal,
    ):
        direction, score, note, confluence = aggregate_timeframe_confluence(snapshot, func)
        if direction != "neutral":
            module_signals.append({
                "name": func.__name__,
                "direction": direction,
                "score": score,
                "note": note,
                "confluence": confluence,
            })
        confluence_map[func.__name__] = confluence

    long_short_direction, long_short_score, long_short_note, long_short_details = long_short_ratio_signal(snapshot)
    if long_short_direction != "neutral":
        module_signals.append({
            "name": "long_short_ratio_signal",
            "direction": long_short_direction,
            "score": long_short_score,
            "note": long_short_note,
            "confluence": {
                "5m": long_short_direction,
                "15m": long_short_direction,
                "1h": long_short_direction,
                "4h": long_short_direction,
                "1d": long_short_direction,
            },
            "details": long_short_details,
        })
    confluence_map["long_short_ratio_signal"] = {
        "5m": long_short_direction,
        "15m": long_short_direction,
        "1h": long_short_direction,
        "4h": long_short_direction,
        "1d": long_short_direction,
    }

    if not module_signals:
        return {
            "symbol": snapshot.get("symbol", "UNKNOWN"),
            "direction": "neutral",
            "score": 0.0,
            "confidence": 0.0,
            "signals": [],
            "entry": 0.0,
            "sl": 0.0,
            "tp": 0.0,
            "reasons": ["No module signal triggered"],
            "correlated_with": snapshot.get("correlated_with", []),
            "confluence": {"15m": "neutral", "1h": "neutral", "4h": "neutral"},
        }

    direction, selected_reasons = _select_direction_and_reasons(module_signals)
    votes = {"long": 0.0, "short": 0.0}
    for mod in module_signals:
        direction_name = str(mod["direction"]).lower()
        if direction_name in votes:
            votes[direction_name] += mod["score"]

    final_score = min(100.0, (max(votes["long"], votes["short"]) / max(len(module_signals), 1)) * 1.15)

    if any(module.get("confluence") for module in module_signals):
        final_score = min(100.0, final_score + 10.0)

    price = safe_float(snapshot.get("last_price", 0.0))
    atr = atr_from_klines(snapshot.get("klines", []), period=14)
    stop_buffer, target_buffer = build_risk_levels(price, atr)

    if direction == "long":
        entry = price
        sl = max(price - stop_buffer, 0.0)
        tp = price + target_buffer
    else:
        entry = price
        sl = price + stop_buffer
        tp = max(price - target_buffer, 0.0)

    confluence = {
        "15m": "neutral",
        "1h": "neutral",
        "4h": "neutral",
    }
    for mod in module_signals:
        for timeframe, value in mod.get("confluence", {}).items():
            if value in {"long", "short"}:
                confluence[timeframe] = value

    regime = estimate_market_regime(snapshot)
    long_count = sum(1 for value in confluence.values() if value == "long")
    short_count = sum(1 for value in confluence.values() if value == "short")
    if long_count and short_count:
        logger = __import__("logging").getLogger(__name__)
        logger.error(
            "Signal mismatch detected: chosen_direction=%s, multi_timeframe_confluence=%s, module_signals=%s",
            direction,
            confluence,
            module_signals,
        )
        direction = "short" if short_count >= long_count else "long"
        selected_reasons = [mod.get("note") for mod in module_signals if str(mod.get("direction", "neutral")).lower() == direction and mod.get("note")]

    result = {
        "symbol": snapshot.get("symbol", "UNKNOWN"),
        "direction": direction,
        "score": round(final_score, 2),
        "confidence": round(final_score / 100.0, 2),
        "signals": module_signals,
        "entry": round(entry, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "reasons": selected_reasons,
        "correlated_with": snapshot.get("correlated_with", []),
        "confluence": confluence,
        "regime": regime,
        "long_short": long_short_details,
    }
    return result
