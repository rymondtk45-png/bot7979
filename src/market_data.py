import logging
import time
from typing import Any, Dict, Iterable, List

import requests

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"

EXCHANGE_URLS = {
    "BINANCE": {"base": "https://api.binance.com", "futures": "https://fapi.binance.com"},
    "OKX": {"base": "https://www.okx.com", "futures": "https://www.okx.com"},
    "BYBIT": {"base": "https://api.bybit.com", "futures": "https://api.bybit.com"},
    "BINGX": {"base": "https://open-api.bingx.com", "futures": "https://open-api.bingx.com"},
    "KUCOIN": {"base": "https://api.kucoin.com", "futures": "https://api-futures.kucoin.com"},
    "BITGET": {"base": "https://api.bitget.com", "futures": "https://api.bitget.com"},
    "MEXC": {"base": "https://api.mexc.com", "futures": "https://contract.mexc.com"},
}


def fetch_json(url: str, timeout: int = 10) -> Any:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace("-", "").replace("_", "")
    if cleaned.endswith("USDT"):
        return cleaned
    return cleaned


def exchange_symbol(symbol: str, exchange: str) -> str:
    value = normalize_symbol(symbol)
    exchange_name = exchange.upper()
    if exchange_name in {"OKX", "KUCOIN"}:
        if value.endswith("USDT"):
            return value[:-4] + "-USDT"
    if exchange_name in {"BYBIT", "BITGET", "BINANCE", "BINGX", "MEXC"}:
        return value
    return value


def fetch_symbol_klines(symbol: str, interval: str = "15m", limit: int = 200) -> List[List[float]]:
    url = f"{BINANCE_BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    payload = fetch_json(url)
    return payload if isinstance(payload, list) else []


def fetch_futures_klines(symbol: str, interval: str = "15m", limit: int = 200) -> List[List[float]]:
    url = f"{BINANCE_FUTURES}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    payload = fetch_json(url)
    return payload if isinstance(payload, list) else []


def fetch_order_book(symbol: str, limit: int = 20, futures: bool = True) -> Dict[str, Any]:
    base = BINANCE_FUTURES if futures else BINANCE_BASE
    url = f"{base}/fapi/v1/depth?symbol={symbol}&limit={limit}" if futures else f"{base}/api/v3/depth?symbol={symbol}&limit={limit}"
    payload = fetch_json(url)
    if not isinstance(payload, dict):
        return {"bids": [], "asks": []}
    return {"bids": payload.get("bids", []), "asks": payload.get("asks", [])}


def fetch_funding_oi(symbol: str) -> Dict[str, float]:
    url = f"{BINANCE_FUTURES}/fapi/v1/fundingRate?symbol={symbol}&limit=1"
    funding_data = fetch_json(url)
    if not isinstance(funding_data, list) or not funding_data:
        return {"fundingRate": 0.0, "nextFundingTime": 0}

    row = funding_data[0]
    return {
        "fundingRate": float(row.get("fundingRate", 0.0)),
        "nextFundingTime": int(row.get("nextFundingTime", 0)),
    }


def fetch_open_interest(symbol: str) -> Dict[str, float]:
    url = f"{BINANCE_FUTURES}/fapi/v1/openInterest?symbol={symbol}"
    payload = fetch_json(url)
    if not isinstance(payload, dict):
        return {"openInterest": 0.0, "symbol": symbol}
    return {"openInterest": float(payload.get("openInterest", 0.0)), "symbol": payload.get("symbol", symbol)}


def fetch_ticker(symbol: str) -> Dict[str, float]:
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr?symbol={symbol}"
    payload = fetch_json(url)
    if not isinstance(payload, dict):
        return {"lastPrice": 0.0, "priceChangePercent": 0.0, "quoteVolume": 0.0}
    return {
        "lastPrice": float(payload.get("lastPrice", 0.0)),
        "priceChangePercent": float(payload.get("priceChangePercent", 0.0)),
        "quoteVolume": float(payload.get("quoteVolume", 0.0)),
    }


def fetch_exchange_ticker(exchange: str, symbol: str) -> Dict[str, Any]:
    exchange_name = exchange.upper()
    req_symbol = exchange_symbol(symbol, exchange_name)
    cfg = EXCHANGE_URLS.get(exchange_name, {"base": "", "futures": ""})
    base = cfg.get("base", "")

    try:
        if exchange_name == "BINANCE":
            payload = fetch_json(f"{base}/api/v3/ticker/24hr?symbol={req_symbol}")
            if not isinstance(payload, dict):
                return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(payload.get("lastPrice", 0.0))}

        if exchange_name == "OKX":
            payload = fetch_json(f"{base}/api/v5/market/ticker?instId={req_symbol}")
            if not isinstance(payload, dict):
                return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}
            data = payload.get("data") or []
            if isinstance(data, list) and data:
                last_price = safe_float(data[0].get("last"), 0.0)
                return {"exchange": exchange_name, "symbol": symbol, "last_price": last_price}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}

        if exchange_name == "BYBIT":
            payload = fetch_json(f"{base}/v5/market/tickers?category=spot&symbol={req_symbol}")
            if not isinstance(payload, dict):
                return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}
            data = payload.get("result", {}).get("list", [])
            if data:
                item = data[0]
                return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(item.get("lastPrice", 0.0))}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}

        if exchange_name == "BINGX":
            payload = fetch_json(f"{base}/openApi/spot/v1/ticker/24hr?symbol={req_symbol}")
            if isinstance(payload, dict):
                data = payload.get("data") or {}
                if isinstance(data, dict):
                    return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(data.get("lastPrice", 0.0))}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}

        if exchange_name == "KUCOIN":
            payload = fetch_json(f"{base}/api/v1/market/stats?symbol={req_symbol}")
            if isinstance(payload, dict):
                data = payload.get("data") or {}
                return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(data.get("last") or data.get("lastPrice"), 0.0)}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}

        if exchange_name == "BITGET":
            payload = fetch_json(f"{base}/api/v2/spot/market/tickers?symbol={req_symbol}")
            if isinstance(payload, dict):
                data = payload.get("data") or []
                if isinstance(data, list) and data:
                    return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(data[0].get("lastPr", data[0].get("lastPrice", 0.0))) }
            return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}

        if exchange_name == "MEXC":
            payload = fetch_json(f"{base}/api/v3/ticker/24hr?symbol={req_symbol}")
            if not isinstance(payload, dict):
                return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}
            return {"exchange": exchange_name, "symbol": symbol, "last_price": safe_float(payload.get("lastPrice", 0.0))}
    except Exception as exc:  # pragma: no cover - network failure fallback
        logger.warning("Ticker fetch failed for %s/%s: %s", exchange_name, symbol, exc)

    return {"exchange": exchange_name, "symbol": symbol, "last_price": 0.0}


def aggregate_exchange_prices(symbol: str, exchanges: Iterable[str] | None = None) -> Dict[str, Any]:
    exchange_names = list(exchanges) if exchanges else ["BINANCE", "OKX", "BYBIT", "BINGX", "KUCOIN", "BITGET", "MEXC"]
    prices = {}
    for exchange in exchange_names:
        item = fetch_exchange_ticker(exchange, symbol)
        price = safe_float(item.get("last_price"), 0.0)
        if price > 0:
            prices[exchange] = price

    if not prices:
        return {"symbol": symbol, "exchange_prices": {}, "avg_price": 0.0, "max_price": 0.0, "min_price": 0.0, "spread_pct": 0.0}

    price_values = list(prices.values())
    avg_price = sum(price_values) / len(price_values)
    max_price = max(price_values)
    min_price = min(price_values)
    spread_pct = ((max_price - min_price) / avg_price) * 100.0 if avg_price else 0.0
    return {
        "symbol": symbol,
        "exchange_prices": prices,
        "avg_price": avg_price,
        "max_price": max_price,
        "min_price": min_price,
        "spread_pct": spread_pct,
    }


def fetch_market_snapshot(symbol: str, futures: bool = True, exchanges: Iterable[str] | None = None) -> Dict[str, Any]:
    snapshot = {
        "symbol": symbol,
        "last_price": 0.0,
        "change_24h": 0.0,
        "volume_24h": 0.0,
        "klines": [],
        "bids": [],
        "asks": [],
        "fundingRate": 0.0,
        "nextFundingTime": 0,
        "openInterest": 0.0,
        "exchange_prices": {},
        "exchange_aggregate": {"symbol": symbol, "exchange_prices": {}, "avg_price": 0.0, "spread_pct": 0.0},
    }

    try:
        klines = fetch_futures_klines(symbol) if futures else fetch_symbol_klines(symbol)
        snapshot["klines"] = klines
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: klines fetch failed for %s", symbol, exc_info=exc)

    try:
        order_book = fetch_order_book(symbol, limit=20, futures=futures)
        snapshot["bids"] = order_book.get("bids", [])
        snapshot["asks"] = order_book.get("asks", [])
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: order book fetch failed for %s", symbol, exc_info=exc)

    try:
        ticker = fetch_ticker(symbol)
        snapshot["last_price"] = float(ticker.get("lastPrice", 0.0))
        snapshot["change_24h"] = float(ticker.get("priceChangePercent", 0.0))
        snapshot["volume_24h"] = float(ticker.get("quoteVolume", 0.0))
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: 24hr ticker fetch failed for %s", symbol, exc_info=exc)

    try:
        funding = fetch_funding_oi(symbol)
        snapshot["fundingRate"] = funding.get("fundingRate", 0.0)
        snapshot["nextFundingTime"] = funding.get("nextFundingTime", 0)
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: fundingRate fetch failed for %s", symbol, exc_info=exc)

    try:
        oi = fetch_open_interest(symbol)
        snapshot["openInterest"] = oi.get("openInterest", 0.0)
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: openInterest fetch failed for %s", symbol, exc_info=exc)

    try:
        exchange_data = aggregate_exchange_prices(symbol, exchanges=exchanges)
        snapshot["exchange_prices"] = exchange_data.get("exchange_prices", {})
        snapshot["exchange_aggregate"] = exchange_data
    except Exception as exc:  # pragma: no cover - network issue path
        logger.exception("REST: cross-exchange price fetch failed for %s", symbol, exc_info=exc)

    return snapshot


def rate_limited_request(function, *args, **kwargs):
    time.sleep(0.15)
    return function(*args, **kwargs)
