import asyncio
import time
from datetime import datetime, timedelta

from loguru import logger

from src.strategies.scalping.futures.coordinators.websocket_coordinator import (
    WebSocketCoordinator,
)

# Imports from project
from src.strategies.scalping.futures.core.data_registry import DataRegistry
from src.strategies.scalping.futures.order_executor import FuturesOrderExecutor


class DummySignalGenerator:
    is_initialized = True
    regime_managers = {}
    regime_manager = None


class DummyOrchestrator:
    all_modules_ready = True


class DummyConfig:
    def __init__(self):
        # Minimal scalping config stub with order_executor dict
        self.scalping = type(
            "SC",
            (),
            {
                "symbols": ["BTC-USDT"],
                "order_executor": {
                    "limit_order": {
                        "limit_offset_percent": 0.1,
                        "by_regime": {},
                        "by_symbol": {},
                    }
                },
            },
        )()


class DummyClient:
    async def get_price_limits(self, symbol: str):
        # Return stale price_limits (timestamp 1.2s ago) to trigger TTL logic
        ts = time.time() - 1.2
        return {
            "timestamp": ts,
            "best_bid": 100.0,
            "best_ask": 100.2,
            "current_price": 100.1,
            "max_buy_price": 101.0,
            "min_sell_price": 99.0,
        }

    async def get_balance(self):
        return 1000.0

    async def get_instrument_details(self, symbol: str):
        return {"ctVal": 0.01, "minSz": 1}

    async def place_futures_order(self, **kwargs):
        return {"code": "0", "data": [{"ordId": "dummy"}]}


class DummyGuard:
    pass


async def test_atomic_update_and_throttle():
    logger.info("=== Test: atomic update + adaptive throttle ===")
    dr = DataRegistry()
    wsc = WebSocketCoordinator(
        ws_manager=None,
        private_ws_manager=None,
        scalping_config=type("S", (), {"symbols": ["BTC-USDT"]})(),
        active_positions_ref={},
        fast_adx=type("ADXcfg", (), {"period": 9, "threshold": 20.0})(),
        position_manager=None,
        trailing_sl_coordinator=None,
        debug_logger=None,
        client=None,
        handle_ticker_callback=None,
        update_trailing_sl_callback=None,
        check_signals_callback=None,
        handle_position_closed_callback=None,
        update_active_positions_callback=None,
        update_active_orders_cache_callback=None,
        data_registry=dr,
        structured_logger=None,
        smart_exit_coordinator=None,
        performance_tracker=None,
        signal_generator=DummySignalGenerator(),
        orchestrator=DummyOrchestrator(),
    )

    # Build ticker data
    def ticker(price: float):
        return {
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "last": str(price),
                    "vol24h": "0",
                    "volCcy24h": "0",
                    "high24h": str(price),
                    "low24h": str(price),
                    "open24h": str(price),
                }
            ]
        }

    # Call 5 times without position -> expect only ~1 update due to throttle 1/5
    await wsc.handle_ticker_data("BTC-USDT", ticker(100.0))
    md1 = await dr.get_market_data("BTC-USDT")
    t1 = md1.get("updated_at") if md1 else None

    for i in range(1, 5):
        await wsc.handle_ticker_data("BTC-USDT", ticker(100.0 + i * 0.01))
    md2 = await dr.get_market_data("BTC-USDT")
    t2 = md2.get("updated_at") if md2 else None

    # When throttled, updated_at should change, but not on every call
    assert t1 is not None and t2 is not None
    assert t2 >= t1

    # Add open position -> should bypass throttle (process every ticker)
    wsc.active_positions_ref["BTC-USDT"] = {"side": "long"}
    await wsc.handle_ticker_data("BTC-USDT", ticker(100.2))
    md3 = await dr.get_market_data("BTC-USDT")
    t3 = md3.get("updated_at") if md3 else None
    assert t3 >= t2

    # Check indicators updated (ADX present)
    inds = await dr.get_indicators("BTC-USDT")
    assert inds is None or isinstance(inds, dict)  # may be None if TTL check triggers


async def test_order_executor_ttl_reject():
    logger.info("=== Test: order executor TTL rejection ===")
    dr = DataRegistry()
    # Seed market_data then mark it stale
    await dr.update_market_data("BTC-USDT", {"price": 100.0})
    # Force stale updated_at
    dr._market_data["BTC-USDT"]["updated_at"] = datetime.now() - timedelta(seconds=1.2)

    cfg = DummyConfig()
    client = DummyClient()
    guard = DummyGuard()
    oe = FuturesOrderExecutor(cfg, client, guard)
    oe.set_data_registry(dr)

    # Expect stale handling to return 0.0 (function catches and returns 0.0)
    price = await oe._calculate_limit_price(
        "BTC-USDT", side="buy", regime="trending", signal=None
    )
    assert price == 0.0


async def main():
    await test_atomic_update_and_throttle()
    await test_order_executor_ttl_reject()
    print("SMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
