import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.strategies.scalping.futures.core.data_registry import DataRegistry


@pytest.mark.asyncio
async def test_decision_snapshot_uses_context_threshold() -> None:
    registry = DataRegistry()
    registry.configure_decision_max_age({"entry": 2.0})

    symbol = "BTC-USDT"
    await registry.update_market_data(
        symbol, {"price": 100.0, "last_price": 100.0, "source": "WEBSOCKET"}
    )
    async with registry._lock:
        registry._market_data[symbol]["updated_at"] = datetime.now() - timedelta(
            seconds=3
        )

    snapshot = await registry.get_decision_price_snapshot(
        symbol=symbol,
        client=None,
        context="entry",
        allow_rest_fallback=False,
    )

    assert snapshot is not None
    assert snapshot["stale"] is True
    assert snapshot["max_age"] == 2.0


@pytest.mark.asyncio
async def test_decision_snapshot_context_keeps_exit_critical_fresh() -> None:
    registry = DataRegistry()
    registry.configure_decision_max_age({"exit_critical": 10.0})

    symbol = "ETH-USDT"
    await registry.update_market_data(
        symbol, {"price": 2000.0, "last_price": 2000.0, "source": "WEBSOCKET"}
    )
    async with registry._lock:
        registry._market_data[symbol]["updated_at"] = datetime.now() - timedelta(
            seconds=6
        )

    snapshot = await registry.get_decision_price_snapshot(
        symbol=symbol,
        client=None,
        context="exit_critical",
        allow_rest_fallback=False,
    )

    assert snapshot is not None
    assert snapshot["stale"] is False
    assert snapshot["context"] == "exit_critical"
    assert snapshot["max_age"] == 10.0
