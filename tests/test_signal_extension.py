import os
import tempfile
import time
import unittest

from src.config import CONFIG
from src.engine import SignalEngine
from src.signals import (
    basis_spread_signal,
    composite_signal,
    compute_rolling_correlation,
    estimate_market_regime,
    liquidation_heatmap_signal,
    taker_buy_sell_ratio_signal,
    whale_wallet_tracking_signal,
)


def make_klines(close_start: float, step: float, length: int = 200):
    klines = []
    price = close_start
    for i in range(length):
        open_price = price
        close_price = price + step
        high = max(open_price, close_price) + abs(step) * 0.8
        low = min(open_price, close_price) - abs(step) * 0.8
        klines.append([0, open_price, high, low, close_price, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        price = close_price
    return klines


class SignalExtensionTests(unittest.TestCase):
    def test_rolling_correlation_is_high_for_similar_series(self):
        series_a = [100 + i * 0.7 for i in range(120)]
        series_b = [101 + i * 0.7 + (0.2 if i % 2 else -0.2) for i in range(120)]
        corr = compute_rolling_correlation(series_a, series_b, window=20)
        self.assertGreater(corr, 0.8)

    def test_composite_signal_includes_multiframe_confluence(self):
        snapshot = {
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "klines": make_klines(100.0, 0.2, 200),
            "timeframe_klines": {
                "15m": make_klines(100.0, 0.2, 200),
                "1h": make_klines(100.5, 0.4, 200),
                "4h": make_klines(101.0, 0.6, 200),
            },
            "bids": [["100", "10"], ["99.9", "5"]],
            "asks": [["101", "10"], ["101.1", "5"]],
            "fundingRate": 0.0015,
            "openInterest": 1000.0,
            "exchange_prices": {"BINANCE": 100.0, "OKX": 100.2, "BYBIT": 99.9},
        }

        signal = composite_signal(snapshot)
        self.assertIn("confluence", signal)
        self.assertIn("15m", signal["confluence"])
        self.assertIn("1h", signal["confluence"])
        self.assertIn("4h", signal["confluence"])

    def test_composite_signal_has_correlated_field(self):
        snapshot = {
            "symbol": "ETHUSDT",
            "last_price": 200.0,
            "klines": make_klines(200.0, 0.3, 200),
            "timeframe_klines": {
                "15m": make_klines(200.0, 0.3, 200),
                "1h": make_klines(200.5, 0.5, 200),
                "4h": make_klines(201.0, 0.7, 200),
            },
            "bids": [["200", "10"], ["199.8", "5"]],
            "asks": [["201", "10"], ["201.2", "5"]],
            "fundingRate": -0.0010,
            "openInterest": 900.0,
            "exchange_prices": {"BINANCE": 200.0, "OKX": 200.3, "BYBIT": 199.7},
        }

        signal = composite_signal(snapshot)
        self.assertIn("correlated_with", signal)
        self.assertIsInstance(signal["correlated_with"], list)

    def test_engine_groups_highly_correlated_symbols(self):
        engine = object.__new__(SignalEngine)
        engine.last_alerts = {}
        price_map = {
            "BTCUSDT": [100 + i * 0.8 for i in range(120)],
            "ETHUSDT": [101 + i * 0.8 + (2 if i % 7 else -1) for i in range(120)],
            "SOLUSDT": [40 + ((i % 12) * 3) + (8 if i % 17 == 0 else 0) for i in range(120)],
        }

        correlated = engine._get_correlated_symbols("BTCUSDT", price_map)
        self.assertIn("ETHUSDT", correlated)
        self.assertNotIn("SOLUSDT", correlated)

    def test_estimate_market_regime_returns_regime(self):
        klines = []
        price = 100.0
        for i in range(200):
            open_price = price
            close_price = price + (0.2 if i % 5 else -0.1)
            high = max(open_price, close_price) + 0.6
            low = min(open_price, close_price) - 0.6
            klines.append([0, open_price, high, low, close_price, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
            price = close_price

        regime = estimate_market_regime({"klines": klines})
        self.assertIn(regime, {"accumulation", "trending", "high_volatility"})

        signal = composite_signal({
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "klines": klines,
            "bids": [["100", "10"], ["99.9", "5"]],
            "asks": [["101", "10"], ["101.1", "5"]],
            "fundingRate": 0.0015,
            "openInterest": 1000.0,
            "exchange_prices": {"BINANCE": 100.0, "OKX": 100.2, "BYBIT": 99.9},
        })
        self.assertIn("regime", signal)

    def test_signal_expiry_marks_expired_after_ttl(self):
        engine = object.__new__(SignalEngine)
        engine.active_signals = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry": 100.0,
                "status": "active",
                "expires_at": time.time() - 1,
            }
        }
        expired = engine._expire_active_signals(current_price=99.0)
        self.assertEqual(expired[0]["status"], "expired")
        self.assertEqual(expired[0]["symbol"], "BTCUSDT")

    def test_step_five_modules_are_available(self):
        snapshot = {
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "klines": [[0, 100, 105, 95, 100, 0, 0, 0, 0, 0] for _ in range(200)],
            "openInterest": 120000.0,
            "fundingRate": 0.0009,
            "exchange_prices": {"BINANCE": 100.0, "OKX": 100.3, "BYBIT": 99.8},
            "spot_price": 100.0,
            "futures_price": 103.0,
            "taker_buy_ratio": 1.4,
            "whale_inflow": 1.3,
            "whale_outflow": 0.2,
        }

        liquidation = liquidation_heatmap_signal(snapshot)
        whale = whale_wallet_tracking_signal(snapshot)
        basis = basis_spread_signal(snapshot)
        taker = taker_buy_sell_ratio_signal(snapshot)

        self.assertIn(liquidation[0], {"long", "short", "neutral"})
        self.assertIn(whale[0], {"long", "short", "neutral"})
        self.assertIn(basis[0], {"long", "short", "neutral"})
        self.assertIn(taker[0], {"long", "short", "neutral"})

    def test_step_six_weight_config_and_backtest_report(self):
        self.assertIn("liquidity_sweep", CONFIG.WEIGHTS)
        self.assertGreater(CONFIG.WEIGHTS["liquidity_sweep"], 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = os.path.join(tmpdir, "report.json")
            from backtest import run_backtest
            result = run_backtest(report_path=report_path)
            self.assertTrue(os.path.exists(report_path))
            self.assertIn("winrate", result)
            self.assertIn("report_path", result)

    def test_step_seven_sqlite_self_scoring_and_summary(self):
        from src.logger import SignalLogger

        logger = SignalLogger(db_path=":memory:")
        logger.save_signal({
            "symbol": "BTCUSDT",
            "direction": "long",
            "entry": 100.0,
            "sl": 95.0,
            "tp": 108.0,
            "module": "liquidity_sweep",
            "score": 80,
            "status": "active",
        })
        row = logger.get_latest_signal("BTCUSDT")
        self.assertEqual(row["symbol"], "BTCUSDT")
        self.assertEqual(row["direction"], "long")
        self.assertIn("module", row)
        summary = logger.summary_by_module()
        self.assertIsInstance(summary, list)

    def test_long_short_ratio_module_and_composite_output(self):
        from src.signals import composite_signal, long_short_ratio_signal

        snapshot = {
            "symbol": "BTCUSDT",
            "last_price": 100.0,
            "klines": make_klines(100.0, 0.2, 200),
            "bids": [["100", "10"], ["99.9", "5"]],
            "asks": [["101", "10"], ["101.1", "5"]],
            "fundingRate": 0.0015,
            "openInterest": 1000.0,
            "exchange_prices": {"BINANCE": 100.0, "OKX": 100.2, "BYBIT": 99.9},
            "long_short_ratio": {
                "BINANCE": {
                    "5m": {"global_account": 0.62, "top_trader_position": 0.55, "top_trader_account": 0.58},
                    "15m": {"global_account": 0.58, "top_trader_position": 0.52, "top_trader_account": 0.54},
                    "1h": {"global_account": 0.52, "top_trader_position": 0.49, "top_trader_account": 0.51},
                    "4h": {"global_account": 0.49, "top_trader_position": 0.46, "top_trader_account": 0.48},
                    "1d": {"global_account": 0.45, "top_trader_position": 0.43, "top_trader_account": 0.45},
                },
                "OKX": {
                    "5m": {"global_account": 0.59, "top_trader_position": 0.53, "top_trader_account": 0.57},
                    "15m": {"global_account": 0.55, "top_trader_position": 0.51, "top_trader_account": 0.54},
                    "1h": {"global_account": 0.50, "top_trader_position": 0.48, "top_trader_account": 0.49},
                    "4h": {"global_account": 0.48, "top_trader_position": 0.44, "top_trader_account": 0.47},
                    "1d": {"global_account": 0.43, "top_trader_position": 0.41, "top_trader_account": 0.44},
                },
            },
        }

        direction, score, note, details = long_short_ratio_signal(snapshot)
        self.assertIn(direction, {"long", "short", "neutral"})
        self.assertIn("aggregated_ratio", details)
        self.assertIn("by_timeframe", details)
        self.assertIn("retail_vs_smart_money_divergence", details)

        result = composite_signal(snapshot)
        self.assertIn("long_short", result)
        self.assertIn("aggregated_ratio", result["long_short"])

    def test_signal_engine_detects_tp_and_sl_hits(self):
        from src.engine import SignalEngine
        from src.telegram_bot import TelegramBot

        engine = object.__new__(SignalEngine)
        engine.active_signals = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry": 100.0,
                "sl": 95.0,
                "tp": 110.0,
                "status": "active",
            }
        }
        self.assertEqual(engine._detect_signal_hit("BTCUSDT", 94.0)["hit_type"], "sl")
        self.assertEqual(engine._detect_signal_hit("BTCUSDT", 111.0)["hit_type"], "tp")
        self.assertIsNone(engine._detect_signal_hit("BTCUSDT", 102.0))

        message = TelegramBot("token", "chat").render_hit_notice({
            "symbol": "BTCUSDT",
            "direction": "long",
            "hit_type": "sl",
            "price": 94.0,
            "entry": 100.0,
            "sl": 95.0,
            "tp": 110.0,
        })
        self.assertIn("chạm sl", message.lower())

    def test_composite_signal_includes_expanded_market_modules(self):
        snapshot = {
            "symbol": "ETHUSDT",
            "last_price": 200.0,
            "klines": make_klines(200.0, 0.5, 200),
            "bids": [["200", "20"], ["199.8", "8"]],
            "asks": [["201", "20"], ["201.2", "8"]],
            "fundingRate": 0.0012,
            "openInterest": 1500.0,
            "exchange_prices": {"BINANCE": 200.0, "OKX": 201.0, "BYBIT": 199.5},
            "volume_24h": 1200000000.0,
        }
        signal = composite_signal(snapshot)
        names = {item["name"] for item in signal["signals"]}
        self.assertTrue(any(name.endswith("signal") for name in names))

    def test_coinstrong_command_toggle_parsing(self):
        from src.telegram_bot import TelegramBot

        bot = TelegramBot("token", "chat")
        self.assertTrue(bot.parse_command("/coinstrong on")["enabled"])
        self.assertFalse(bot.parse_command("/coinstrong off")["enabled"])
        self.assertIn("toggle", bot.parse_command("/coinstrong")["action"])

    def test_symbol_ranking_prioritizes_top_coin(self):
        from src.ranking import rank_symbol_signals

        candidates = [
            {"symbol": "BTCUSDT", "score": 85, "confidence": 0.9, "direction": "long", "confluence": {"15m": "long", "1h": "long", "4h": "long"}, "regime": "trending"},
            {"symbol": "ETHUSDT", "score": 72, "confidence": 0.8, "direction": "long", "confluence": {"15m": "long", "1h": "neutral", "4h": "long"}, "regime": "trending"},
            {"symbol": "SOLUSDT", "score": 50, "confidence": 0.5, "direction": "short", "confluence": {"15m": "short", "1h": "neutral", "4h": "neutral"}, "regime": "accumulation"},
        ]
        ranked = rank_symbol_signals(candidates)
        self.assertEqual(ranked[0]["symbol"], "BTCUSDT")
        self.assertLess(ranked[-1]["symbol"], "Z")

    def test_top_coin_summary_message_format(self):
        from src.telegram_bot import TelegramBot

        bot = TelegramBot("token", "chat")
        summary = bot.render_summary_top_coins([
            {"symbol": "BTCUSDT", "direction": "long", "score": 86, "priority": 92.5},
            {"symbol": "ETHUSDT", "direction": "short", "score": 71, "priority": 78.0},
        ])
        self.assertIn("TOP COIN", summary.upper())
        self.assertIn("BTCUSDT", summary)
        self.assertIn("ETHUSDT", summary)


if __name__ == "__main__":
    unittest.main()
