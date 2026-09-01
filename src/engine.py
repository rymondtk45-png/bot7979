import logging
import time
from typing import Dict, Iterable, List

from .config import CONFIG
from .logger import log_signal
from .market_data import fetch_market_snapshot, rate_limited_request
from .signals import composite_signal, compute_rolling_correlation
from .streaming import BinanceWebSocketManager
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class SignalEngine:
    def __init__(self):
        self.bot = TelegramBot(CONFIG.TELEGRAM_BOT_TOKEN, CONFIG.TELEGRAM_CHAT_ID)
        self.last_alerts = {}
        self.active_signals = {}
        self.ws = BinanceWebSocketManager(CONFIG.SYMBOLS, futures=CONFIG.USE_FUTURES)
        self.ws.start()

    def _get_snapshot(self, symbol: str) -> Dict[str, object]:
        snapshot = self.ws.get_snapshot(symbol)
        if snapshot:
            return snapshot
        return rate_limited_request(fetch_market_snapshot, symbol, CONFIG.USE_FUTURES)

    def _get_correlated_symbols(self, symbol: str, price_map: Dict[str, List[float]]) -> List[str]:
        base_series = price_map.get(symbol, [])
        if not base_series or len(base_series) < 20:
            return []

        correlated: List[str] = []
        for candidate, series in price_map.items():
            if candidate == symbol or len(series) < 20:
                continue
            corr = compute_rolling_correlation(base_series, series, window=100)
            if corr > 0.8:
                correlated.append(candidate)
        return correlated

    def _expire_active_signals(self, current_price: float | None = None) -> List[Dict[str, object]]:
        expired = []
        for symbol, signal in list(self.active_signals.items()):
            ttl_seconds = 25 * 60
            if signal.get("expires_at", 0) <= time.time():
                signal["status"] = "expired"
                signal["current_price"] = current_price
                signal["expired_reason"] = "TTL exceeded"
                expired.append(signal)
                self.active_signals.pop(symbol, None)
                log_signal(signal)
        return expired

    def evaluate_symbol(self, symbol: str) -> Dict[str, object]:
        snapshot = self._get_snapshot(symbol)
        signal = composite_signal(snapshot)

        if signal.get("direction") == "neutral" or signal.get("score", 0.0) < CONFIG.THRESHOLD:
            return {"symbol": symbol, "status": "neutral"}

        correlated_symbols = self._get_correlated_symbols(symbol, self._build_symbol_price_map())
        if correlated_symbols:
            signal["correlated_with"] = correlated_symbols
            signal["group_key"] = ",".join(sorted([symbol] + correlated_symbols))
        else:
            signal["correlated_with"] = []
            signal["group_key"] = symbol

        group_key = signal.get("group_key", symbol)
        now = time.time()
        last_ts = self.last_alerts.get(group_key, 0)
        if now - last_ts < CONFIG.ALERT_COOLDOWN_SECONDS:
            return {"symbol": symbol, "status": "cooldown", "group_key": group_key}

        signal["symbol"] = symbol
        signal["status"] = "active"
        signal["alert_ts"] = now
        signal["expires_at"] = now + (25 * 60)
        self.active_signals[symbol] = signal
        log_signal(signal)

        if CONFIG.ENABLE_TELEGRAM:
            self.bot.send_signal(signal)

        self.last_alerts[group_key] = now
        return signal

    def _build_symbol_price_map(self) -> Dict[str, List[float]]:
        price_map: Dict[str, List[float]] = {}
        for candidate in CONFIG.SYMBOLS:
            try:
                snap = self._get_snapshot(candidate)
            except Exception:
                continue
            klines = snap.get("klines") or []
            closes = [float(candle[4]) for candle in klines if len(candle) >= 6]
            if closes:
                price_map[candidate] = closes
        return price_map

    def run(self) -> None:
        while True:
            for symbol in CONFIG.SYMBOLS:
                try:
                    self.evaluate_symbol(symbol)
                except Exception as exc:  # pragma: no cover - runtime guard
                    logger.warning("Symbol evaluation failed for %s: %s", symbol, exc)
            time.sleep(CONFIG.POLL_SECONDS)
