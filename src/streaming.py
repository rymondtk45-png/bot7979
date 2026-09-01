import json
import threading
import time
from typing import Any, Dict, Iterable, Optional

import websocket


class BinanceWebSocketManager:
    """Minimal Binance WebSocket manager with REST fallback.

    This keeps a small in-memory cache of the latest live market snapshot for each symbol.
    It subscribes to bookTicker/ticker streams and exposes the cache so other modules can
    consume near-real-time data without a dedicated polling loop.
    """

    def __init__(self, symbols: Iterable[str], futures: bool = True, on_update: Optional[Any] = None):
        self.symbols = [symbol.upper() for symbol in symbols]
        self.futures = futures
        self.on_update = on_update
        self._lock = threading.Lock()
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[websocket.WebSocketApp] = None

    def _build_streams(self) -> str:
        streams = []
        for symbol in self.symbols:
            s = symbol.lower()
            streams.append(f"{s}@ticker")
            streams.append(f"{s}@bookTicker")
            if self.futures:
                streams.append(f"{s}@markPrice")
        return "/".join(streams)

    def _endpoint(self) -> str:
        if self.futures:
            return "wss://fstream.binance.com/stream?streams=" + self._build_streams()
        return "wss://stream.binance.com/stream?streams=" + self._build_streams()

    def _handle_message(self, ws, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return

        stream_data = payload.get("data")
        if not isinstance(stream_data, dict):
            return

        symbol = (stream_data.get("s") or stream_data.get("symbol") or "").upper()
        if not symbol:
            return

        item = self._latest.setdefault(symbol, {})
        item["symbol"] = symbol

        if "b" in stream_data and "B" in stream_data:
            item["bestBid"] = float(stream_data.get("b", 0.0))
            item["bestAsk"] = float(stream_data.get("a", 0.0))
            item["bidQty"] = float(stream_data.get("B", 0.0))
            item["askQty"] = float(stream_data.get("A", 0.0))

        if "c" in stream_data:
            item["last_price"] = float(stream_data.get("c", 0.0))
        if "P" in stream_data:
            item["last_price"] = float(stream_data.get("p", 0.0))
        if "p" in stream_data and "P" not in stream_data:
            item["change_24h"] = float(stream_data.get("p", 0.0))
        if "u" in stream_data:
            item["last_price"] = float(stream_data.get("c", item.get("last_price", 0.0)))

        if "e" in stream_data and stream_data.get("e") == "bookTicker":
            item["bestBid"] = float(stream_data.get("b", item.get("bestBid", 0.0)))
            item["bestAsk"] = float(stream_data.get("a", item.get("bestAsk", 0.0)))

        if "markPrice" in stream_data:
            item["last_price"] = float(stream_data.get("markPrice", item.get("last_price", 0.0)))

        if self.on_update is not None:
            self.on_update(symbol, item)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    url=self._endpoint(),
                    on_message=self._handle_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                pass
            if not self._stop_event.is_set():
                time.sleep(5)

    def _on_error(self, ws, error: Any) -> None:
        if error is not None:
            time.sleep(1)

    def _on_close(self, ws, close_status_code: Any, close_msg: Any) -> None:
        pass

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass

    def get_snapshot(self, symbol: str) -> Dict[str, Any]:
        key = symbol.upper()
        with self._lock:
            return dict(self._latest.get(key, {}))

    def snapshot_for(self, symbol: str) -> Dict[str, Any]:
        return self.get_snapshot(symbol)
