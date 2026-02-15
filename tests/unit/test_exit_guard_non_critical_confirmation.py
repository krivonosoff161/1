import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.strategies.scalping.futures.core.exit_guard import ExitGuard


def _base_payload() -> dict:
    return {
        "price": 100.0,
        "price_age": 0.2,
        "time_in_pos": 300.0,
        "min_holding_minutes": 0.1,
        "pnl_pct": 1.5,
        "net_pnl_pct": 1.2,
        "position_data": {
            "position_side": "long",
            "size": 1.0,
            "entry_price": 99.0,
        },
    }


@pytest.mark.asyncio
async def test_non_critical_exit_requires_second_confirmation() -> None:
    guard = ExitGuard(
        config=None, data_registry=None, position_registry=None, client=None
    )
    payload = _base_payload()

    allowed_first, reason_first = await guard.check(
        symbol="BTC-USDT", reason="tp_reached", payload=dict(payload)
    )
    allowed_second, reason_second = await guard.check(
        symbol="BTC-USDT", reason="tp_reached", payload=dict(payload)
    )

    assert allowed_first is False
    assert reason_first == "non_critical_confirm_1/2"
    assert allowed_second is True
    assert reason_second is None


@pytest.mark.asyncio
async def test_protective_exit_bypasses_non_critical_confirmation() -> None:
    guard = ExitGuard(
        config=None, data_registry=None, position_registry=None, client=None
    )
    payload = _base_payload()

    allowed, reason = await guard.check(
        symbol="BTC-USDT", reason="sl_reached", payload=dict(payload)
    )

    assert allowed is True
    assert reason is None
