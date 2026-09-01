import logging
import threading
import time
from typing import Dict, Iterable, List

from .config import CONFIG
from .logger import log_signal
from .market_data import fetch_market_snapshot, rate_limited_request
from .ranking import select_top_priority_signals
from .signals import composite_signal, compute_rolling_correlation, safe_float
from .streaming import BinanceWebSocketManager
from .telegram_bot import TelegramBot

logger = logging.getLogger(__name__)


class SignalEngine:
    def __init__(self):
        self.bot = TelegramBot(CONFIG.TELEGRAM_BOT_TOKEN, CONFIG.TELEGRAM_CHAT_ID)
        self.last_alerts = {}
        self.hit_alerts = {}
        self.active_signals = {}
        self._coinstrong_lock = threading.Lock()
        self.coin_strong_enabled = self.bot.coin_strong_enabled
        self.ws = BinanceWebSocketManager(CONFIG.SYMBOLS, futures=CONFIG.USE_FUTURES)
        self.ws.start()
        self.telegram_thread = threading.Thread(
            target=self._telegram_poll_loop,
            name="telegram-poll-thread",
            daemon=True,
        )
        self.telegram_thread.start()

    def set_coinstrong_enabled(self, enabled: bool) -> bool:
        with self._coinstrong_lock:
            self.coin_strong_enabled = bool(enabled)
            self.bot.coin_strong_enabled = self.coin_strong_enabled
            return self.coin_strong_enabled

    def _telegram_poll_loop(self) -> None:
        while True:
            try:
                self.poll_telegram_commands()
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.warning("Telegram poll loop crashed unexpectedly: %s", exc)
            time.sleep(2)

    def _get_snapshot(self, symbol: str) -> Dict[str, object]:
        snapshot = self.ws.get_snapshot(symbol)
        if snapshot:
            last_update_ts = safe_float(snapshot.get("_last_update_ts"), 0.0)
            age_seconds = (time.time() - last_update_ts) if last_update_ts else None
            logger.debug(
                "WS snapshot for %s: age_seconds=%s last_price=%s bestBid=%s bestAsk=%s volume_24h=%s change_24h=%s fundingRate=%s openInterest=%s klines=%s",
                symbol,
                round(age_seconds, 2) if age_seconds is not None else "unknown",
                snapshot.get("last_price"),
                snapshot.get("bestBid"),
                snapshot.get("bestAsk"),
                snapshot.get("volume_24h"),
                snapshot.get("change_24h"),
                snapshot.get("fundingRate"),
                snapshot.get("openInterest"),
                len(snapshot.get("klines") or []),
            )
            return snapshot

        logger.warning("WebSocket snapshot empty for %s; falling back to REST market snapshot", symbol)
        snapshot = rate_limited_request(fetch_market_snapshot, symbol, CONFIG.USE_FUTURES)
        logger.debug(
            "REST snapshot for %s: last_price=%s volume_24h=%s change_24h=%s fundingRate=%s openInterest=%s klines=%s",
            symbol,
            snapshot.get("last_price") if isinstance(snapshot, dict) else None,
            snapshot.get("volume_24h") if isinstance(snapshot, dict) else None,
            snapshot.get("change_24h") if isinstance(snapshot, dict) else None,
            snapshot.get("fundingRate") if isinstance(snapshot, dict) else None,
            snapshot.get("openInterest") if isinstance(snapshot, dict) else None,
            len((snapshot or {}).get("klines") or []) if isinstance(snapshot, dict) else 0,
        )
        return snapshot

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

    def _detect_signal_hit(self, symbol: str, current_price: float | None = None) -> Dict[str, object] | None:
        signal = self.active_signals.get(symbol)
        if not signal:
            return None
        if current_price is None:
            current_price = safe_float(signal.get("current_price"), 0.0)
        if current_price <= 0:
            return None

        direction = str(signal.get("direction", "")).lower()
        sl = float(signal.get("sl", 0.0) or 0.0)
        tp = float(signal.get("tp", 0.0) or 0.0)
        if not sl and not tp:
            return None

        if direction == "long":
            if sl and current_price <= sl:
                return {"symbol": symbol, "direction": direction, "hit_type": "sl", "price": current_price}
            if tp and current_price >= tp:
                return {"symbol": symbol, "direction": direction, "hit_type": "tp", "price": current_price}
        elif direction == "short":
            if sl and current_price >= sl:
                return {"symbol": symbol, "direction": direction, "hit_type": "sl", "price": current_price}
            if tp and current_price <= tp:
                return {"symbol": symbol, "direction": direction, "hit_type": "tp", "price": current_price}
        return None

    def _handle_hit(self, symbol: str, current_price: float | None = None) -> Dict[str, object] | None:
        signal = self.active_signals.get(symbol)
        if not signal:
            return None
        hit = self._detect_signal_hit(symbol, current_price)
        if not hit:
            return None

        signal.update(hit)
        signal["status"] = "hit"
        signal["hit_price"] = hit.get("price")
        signal["current_price"] = current_price
        self.active_signals.pop(symbol, None)
        log_signal(signal)

        if CONFIG.ENABLE_TELEGRAM:
            logger.info("Sending alert for %s to chat_id=%s", symbol, self.bot.chat_id)
            try:
                self.bot.send_hit_notice(signal)
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.exception("Failed to send hit notice for %s: %s", symbol, exc)

        self.hit_alerts[symbol] = time.time()
        return signal

    def poll_telegram_commands(self) -> None:
        for update in self.bot.poll_commands():
            text = update.get("text", "")
            parsed = self.bot.parse_command(text)
            if parsed.get("action") == "unknown":
                continue

            logger.info(
                "Received Telegram command: action=%s chat_id=%s text=%s",
                parsed.get("action"),
                update.get("chat_id"),
                text,
            )

            enabled = bool(parsed.get("enabled", self.coin_strong_enabled))
            self.set_coinstrong_enabled(enabled)
            logger.info("CoinStrong state updated to %s by Telegram command", self.coin_strong_enabled)
            try:
                self.bot.send_message(
                    f"<b>CoinStrong</b> {'ON' if self.coin_strong_enabled else 'OFF'}"
                )
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.exception("Failed to send CoinStrong state message to Telegram: %s", exc)

    def evaluate_symbol(self, symbol: str) -> Dict[str, object]:
        snapshot = self._get_snapshot(symbol)
        logger.info(
            "evaluate_symbol input for %s: last_price=%s bestBid=%s bestAsk=%s bidQty=%s askQty=%s volume_24h=%s change_24h=%s fundingRate=%s openInterest=%s klines=%s exchange_prices=%s",
            symbol,
            snapshot.get("last_price"),
            snapshot.get("bestBid"),
            snapshot.get("bestAsk"),
            snapshot.get("bidQty"),
            snapshot.get("askQty"),
            snapshot.get("volume_24h"),
            snapshot.get("change_24h"),
            snapshot.get("fundingRate"),
            snapshot.get("openInterest"),
            len(snapshot.get("klines") or []),
            bool(snapshot.get("exchange_prices")) if isinstance(snapshot, dict) else False,
        )
        signal = composite_signal(snapshot)

        enabled_state = self.coin_strong_enabled
        if not enabled_state:
            logger.info("Evaluated %s: score=%s signal=%s (disabled by CoinStrong)", symbol, signal.get("score", 0.0), False)
            return {"symbol": symbol, "status": "disabled"}

        should_signal = signal.get("direction") != "neutral" and signal.get("score", 0.0) >= CONFIG.THRESHOLD
        if not should_signal:
            logger.info("Evaluated %s: score=%s signal=%s", symbol, signal.get("score", 0.0), False)
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
            logger.info("Evaluated %s: score=%s signal=%s (cooldown)", symbol, signal.get("score", 0.0), True)
            return {"symbol": symbol, "status": "cooldown", "group_key": group_key}

        signal["symbol"] = symbol
        signal["status"] = "active"
        signal["alert_ts"] = now
        signal["expires_at"] = now + (25 * 60)
        self.active_signals[symbol] = signal
        log_signal(signal)

        if CONFIG.ENABLE_TELEGRAM:
            logger.info("Sending alert for %s to chat_id=%s", symbol, self.bot.chat_id)
            try:
                self.bot.send_signal(signal)
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.exception("Telegram alert send failed for %s: %s", symbol, exc)

        self.last_alerts[group_key] = now
        logger.info("Evaluated %s: score=%s signal=%s", symbol, signal.get("score", 0.0), True)
        return signal

    def rank_active_signals(self) -> List[Dict[str, object]]:
        candidates = []
        for symbol, signal in self.active_signals.items():
            candidate = {
                "symbol": signal.get("symbol", symbol),
                "score": float(signal.get("score", 0.0) or 0.0),
                "confidence": float(signal.get("confidence", 0.0) or 0.0),
                "direction": signal.get("direction", "neutral"),
                "confluence": signal.get("confluence", {}),
                "regime": signal.get("regime", "mixed"),
            }
            candidates.append(candidate)
        return select_top_priority_signals(candidates, limit=5)

    def _build_symbol_price_map(self) -> Dict[str, List[float]]:
        price_map: Dict[str, List[float]] = {}
        for candidate in CONFIG.SYMBOLS:
            try:
                snap = self._get_snapshot(candidate)
            except Exception as exc:  # pragma: no cover - runtime guard
                logger.warning("Failed to build price map for %s: %s", candidate, exc)
                continue
            klines = snap.get("klines") or []
            closes = [float(candle[4]) for candle in klines if len(candle) >= 6]
            if closes:
                price_map[candidate] = closes
        return price_map

    def run(self) -> None:
        while True:
            logger.info("Starting scan cycle for %s symbols", len(CONFIG.SYMBOLS))
            for symbol in CONFIG.SYMBOLS:
                try:
                    snapshot = self._get_snapshot(symbol)
                    current_price = safe_float(snapshot.get("last_price"), 0.0)
                    if symbol in self.active_signals:
                        hit = self._handle_hit(symbol, current_price)
                        if hit:
                            logger.info("Signal hit for %s: %s at %s", symbol, hit["hit_type"].upper(), current_price)
                            continue
                    self.evaluate_symbol(symbol)
                except Exception as exc:  # pragma: no cover - runtime guard
                    logger.warning("Symbol evaluation failed for %s: %s", symbol, exc)

            ranked = self.rank_active_signals()
            if ranked:
                top = ranked[0]
                logger.info("Top ranked signal: %s (%s, priority=%s)", top["symbol"], top["direction"], top["priority"])
                if len(ranked) >= 2 and time.time() % 120 < CONFIG.POLL_SECONDS:
                    try:
                        self.bot.send_summary_top_coins(ranked[:5])
                    except Exception as exc:  # pragma: no cover - runtime guard
                        logger.exception("Failed to send summary top-coins alert: %s", exc)
            time.sleep(CONFIG.POLL_SECONDS)
