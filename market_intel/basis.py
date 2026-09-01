import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def compute_basis(futures_price: float, spot_price: float) -> float:
    if spot_price <= 0:
        return 0.0
    return ((futures_price - spot_price) / spot_price) * 100.0


def inspect_basis(symbol: str, futures_price: float, spot_price: float, avg_basis_7d: float = 0.0) -> Dict[str, Any]:
    try:
        basis = compute_basis(futures_price, spot_price)
        extreme = "normal"
        if abs(basis - avg_basis_7d) > max(0.5, abs(avg_basis_7d) * 1.5):
            extreme = "extreme"
        logger.info(
            "%s basis=%.3f%% (avg_7d=%.3f%%) extreme=%s",
            symbol,
            basis,
            avg_basis_7d,
            extreme,
        )
        return {"symbol": symbol, "basis": basis, "avg_basis_7d": avg_basis_7d, "extreme": extreme}
    except Exception:
        logger.exception("%s basis analysis failed", symbol)
        return {"symbol": symbol, "basis": 0.0, "avg_basis_7d": 0.0, "extreme": "normal"}
