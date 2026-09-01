# Signal Aggregator Bot

Bot báo tín hiệu theo hướng quỹ/market maker: đọc dữ liệu công khai từ nhiều sàn lớn, gộp nhiều chỉ báo và gửi cảnh báo qua Telegram cho nhiều cặp coin. Bot chỉ báo tín hiệu, không tự động đặt lệnh.

## Tính năng

- Nhiều cặp coin: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, ...
- Dữ liệu public từ nhiều sàn lớn: Binance, OKX, Bybit, BingX, KuCoin, Bitget, MEXC
- Tín hiệu: liquidity sweep + funding extreme + order book imbalance + cross-exchange divergence
- Composite score cơ bản
- Telegram alert
- Log tín hiệu ra file JSONL
- WebSocket realtime + fallback REST

## Cài đặt

1. Tạo môi trường ảo Python.
2. Cài dependencies:

```bash
pip install -r requirements.txt
```

3. Sao chép file `.env.example` thành `.env` và điền:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT
EXCHANGES=BINANCE,OKX,BYBIT,BINGX,KUCOIN,BITGET,MEXC
POLL_SECONDS=30
THRESHOLD=60
USE_FUTURES=True
ALERT_COOLDOWN_SECONDS=900
ENABLE_TELEGRAM=True
LOG_PATH=logs/signals.jsonl
```

4. Chạy:

```bash
python main.py
```

## Lưu ý

- Đây là phiên bản nền tảng, không phải hệ thống giao dịch tự động.
- Bạn có thể mở rộng bằng thêm module tín hiệu riêng, WebSocket, hoặc backtest.
- Hãy dùng đúng mục đích: cảnh báo thị trường, không đẩy giá hay thao túng.
