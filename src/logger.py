import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class SignalLogger:
    def __init__(self, db_path: str | Path = "logs/signals.db"):
        self.db_path = Path(db_path)
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(":memory:") if str(self.db_path) == ":memory:" else None
        self._init_db()

    def _connect(self):
        if self._conn is not None:
            return self._conn
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    direction TEXT,
                    entry REAL,
                    sl REAL,
                    tp REAL,
                    module TEXT,
                    score REAL,
                    status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    payload TEXT
                )
                """
            )
            conn.commit()

    def save_signal(self, signal: Dict[str, Any]) -> None:
        payload = json.dumps(signal, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO signals (symbol, direction, entry, sl, tp, module, score, status, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.get("symbol"),
                    signal.get("direction"),
                    signal.get("entry"),
                    signal.get("sl"),
                    signal.get("tp"),
                    signal.get("module"),
                    signal.get("score"),
                    signal.get("status", "active"),
                    payload,
                ),
            )
            conn.commit()

    def get_latest_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY id DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        if not row:
            return None
        columns = [
            "id", "symbol", "direction", "entry", "sl", "tp", "module", "score", "status",
            "created_at", "updated_at", "payload",
        ]
        return dict(zip(columns, row))

    def summary_by_module(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT module, COUNT(*), AVG(CAST(score AS REAL)) FROM signals
                WHERE module IS NOT NULL
                GROUP BY module
                ORDER BY COUNT(*) DESC
                """
            ).fetchall()
        return [{"module": module, "count": count, "avg_score": avg_score} for module, count, avg_score in rows]


def setup_logging(log_path: str | Path | None = None) -> None:
    path = Path(log_path) if log_path else Path("logs") / "signals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(path, encoding="utf-8"),
        ],
    )


def log_signal(signal: dict, log_path: str | Path | None = None) -> None:
    path = Path(log_path) if log_path else Path("logs") / "signals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(signal, ensure_ascii=False) + "\n")

    try:
        logger = SignalLogger(db_path=Path("logs") / "signals.db")
        logger.save_signal(signal)
    except Exception:
        pass
