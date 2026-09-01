import json
import os
from typing import Any, Dict, List

from src.config import CONFIG


def _simulate_history() -> List[Dict[str, Any]]:
    return [
        {"market_regime": "sideway", "score": 62, "result": 1.2},
        {"market_regime": "trending", "score": 74, "result": 1.8},
        {"market_regime": "crash", "score": 58, "result": -1.1},
        {"market_regime": "sideway", "score": 67, "result": 1.4},
        {"market_regime": "trending", "score": 81, "result": 2.4},
        {"market_regime": "crash", "score": 60, "result": -1.5},
    ]


def run_backtest(report_path: str = "reports/backtest_report.json") -> Dict[str, Any]:
    history = _simulate_history()
    wins = sum(1 for item in history if item["result"] > 0)
    losses = sum(1 for item in history if item["result"] <= 0)
    avg_rr = sum(item["result"] for item in history) / max(len(history), 1)
    report = {
        "weights": CONFIG.WEIGHTS,
        "sample_size": len(history),
        "winrate": round((wins / max(len(history), 1)) * 100.0, 2),
        "avg_rr": round(avg_rr, 3),
        "wins": wins,
        "losses": losses,
    }

    folder = os.path.dirname(report_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    return {"winrate": report["winrate"], "avg_rr": report["avg_rr"], "report_path": report_path}


if __name__ == "__main__":
    print(run_backtest())
