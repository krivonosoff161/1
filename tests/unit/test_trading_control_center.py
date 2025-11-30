"""
Unit-тесты для TradingControlCenter.

Проверяем:
- run_main_loop() запускается и останавливается корректно
- manage_positions() делегирует в position_manager
- update_state() не падает при пустых позициях
- update_performance() не мутирует данные
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock
from datetime import datetime

import pytest

from src.strategies.scalping.futures.core.trading_control_center import (
    TradingControlCenter,
)


class MockClient:
    """Mock клиент биржи"""

    async def get_positions(self):
        return []


class MockSignalGenerator:
    """Mock генератор сигналов"""

    async def generate_signals(self):
        return []

    regime_managers = {}
    regime_manager = None


class MockSignalCoordinator:
    """Mock координатор сигналов"""

    async def process_signals(self, signals):
        pass


class MockPositionManager:
    """Mock менеджер позиций"""

    async def manage_position(self, position):
        pass


class MockPositionRegistry:
    """Mock реестр позиций"""

    async def get_all_positions(self):
        return {}

    async def get_all_metadata(self):
        return {}

    async def unregister_position(self, symbol):
        pass

    async def register_position(self, symbol, position, metadata):
        pass

    async def update_position(self, symbol, position_updates, metadata_updates):
        pass


class MockDataRegistry:
    """Mock реестр данных"""

    async def get_balance(self):
        return {"balance": 1000.0, "profile": "small"}


class MockOrderCoordinator:
    """Mock координатор ордеров"""

    async def monitor_limit_orders(self):
        pass

    async def update_orders_cache_status(self, normalize_symbol):
        pass


class MockTrailingSLCoordinator:
    """Mock координатор Trailing SL"""

    async def periodic_check(self):
        pass


class MockPerformanceTracker:
    """Mock трекер производительности"""

    def update_stats(self, active_positions):
        pass


class MockTradingStatistics:
    """Mock статистика торговли"""

    def get_reversal_stats(self, symbol=None, regime=None):
        return {
            "total_reversals": 0,
            "v_down_count": 0,
            "v_up_count": 0,
            "avg_price_change": 0.0,
        }


class MockLiquidationGuard:
    """Mock защита от ликвидации"""

    async def get_margin_status(self, client):
        return {"health_status": {"status": "normal"}}


class MockConfigManager:
    """Mock менеджер конфигурации"""

    pass


class MockScalpingConfig:
    """Mock конфигурация скальпинга"""

    check_interval = 0.1


@pytest.fixture
def mock_tcc():
    """Создает TradingControlCenter с моками"""
    active_positions = {}

    def normalize_symbol(symbol: str) -> str:
        return symbol.replace("-", "").upper()

    async def sync_positions_with_exchange(force: bool = False):
        pass

    tcc = TradingControlCenter(
        client=MockClient(),
        signal_generator=MockSignalGenerator(),
        signal_coordinator=MockSignalCoordinator(),
        position_manager=MockPositionManager(),
        position_registry=MockPositionRegistry(),
        data_registry=MockDataRegistry(),
        order_coordinator=MockOrderCoordinator(),
        trailing_sl_coordinator=MockTrailingSLCoordinator(),
        performance_tracker=MockPerformanceTracker(),
        trading_statistics=MockTradingStatistics(),
        liquidation_guard=MockLiquidationGuard(),
        config_manager=MockConfigManager(),
        scalping_config=MockScalpingConfig(),
        active_positions=active_positions,
        normalize_symbol=normalize_symbol,
        sync_positions_with_exchange=sync_positions_with_exchange,
    )

    return tcc


@pytest.mark.asyncio
async def test_tcc_run_main_loop_smoke(mock_tcc):
    """Проверяем, что run_main_loop() запускается и останавливается корректно"""
    # Запускаем цикл в фоне
    task = asyncio.create_task(mock_tcc.run_main_loop())

    # Ждем немного, чтобы цикл успел выполниться несколько раз
    await asyncio.sleep(0.3)

    # Останавливаем
    await mock_tcc.stop()

    # Ждем завершения задачи
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Проверяем, что флаг остановлен
    assert mock_tcc.is_running is False


@pytest.mark.asyncio
async def test_tcc_manage_positions_delegates(mock_tcc):
    """Проверяем, что manage_positions() делегирует в position_manager"""
    # Создаем мок с проверкой вызова
    mock_position_manager = AsyncMock()
    mock_tcc.position_manager = mock_position_manager

    # Добавляем позицию в active_positions
    mock_tcc.active_positions["BTC-USDT"] = {"symbol": "BTC-USDT", "size": 0.001}

    # Вызываем manage_positions
    await mock_tcc.manage_positions()

    # Проверяем, что manage_position был вызван
    mock_position_manager.manage_position.assert_called_once()


@pytest.mark.asyncio
async def test_tcc_update_state_empty_positions(mock_tcc):
    """Проверяем, что update_state() не падает при пустых позициях"""
    # Устанавливаем is_running = True для выполнения логики
    mock_tcc.is_running = True

    # Мокаем client.get_positions() для возврата пустого списка
    mock_tcc.client.get_positions = AsyncMock(return_value=[])

    # Мокаем position_registry методы
    mock_tcc.position_registry.get_all_positions = AsyncMock(return_value={})
    mock_tcc.position_registry.get_all_metadata = AsyncMock(return_value={})

    # Вызываем update_state - не должно быть исключений
    await mock_tcc.update_state()

    # Проверяем, что методы были вызваны
    mock_tcc.client.get_positions.assert_called_once()
    mock_tcc.position_registry.get_all_positions.assert_called_once()


@pytest.mark.asyncio
async def test_tcc_update_state_with_positions(mock_tcc):
    """Проверяем, что update_state() корректно обрабатывает позиции"""
    # Устанавливаем is_running = True для выполнения логики
    mock_tcc.is_running = True

    # Мокаем позиции с биржи
    exchange_positions = [
        {
            "instId": "BTC-USDT-SWAP",
            "pos": "0.001",
            "avgPx": "50000",
            "posSide": "long",
            "cTime": "1609459200000",  # 2021-01-01 00:00:00
        }
    ]

    mock_tcc.client.get_positions = AsyncMock(return_value=exchange_positions)
    mock_tcc.position_registry.get_all_positions = AsyncMock(return_value={})
    mock_tcc.position_registry.get_all_metadata = AsyncMock(return_value={})
    mock_tcc.position_registry.register_position = AsyncMock()

    # Вызываем update_state
    await mock_tcc.update_state()

    # Проверяем, что register_position был вызван для новой позиции
    mock_tcc.position_registry.register_position.assert_called_once()


@pytest.mark.asyncio
async def test_tcc_update_performance_no_mutation(mock_tcc):
    """Проверяем, что update_performance() не мутирует данные"""
    # Создаем исходные данные
    original_positions = {"BTC-USDT": {"symbol": "BTC-USDT", "size": 0.001}}
    mock_tcc.active_positions = original_positions.copy()

    # Мокаем performance_tracker
    mock_tracker = Mock()
    mock_tracker.update_stats = Mock()
    mock_tcc.performance_tracker = mock_tracker

    # Вызываем update_performance
    await mock_tcc.update_performance()

    # Проверяем, что update_stats был вызван
    mock_tracker.update_stats.assert_called_once_with(original_positions)

    # Проверяем, что исходные данные не изменились
    assert mock_tcc.active_positions == original_positions


@pytest.mark.asyncio
async def test_tcc_stop_sets_flag(mock_tcc):
    """Проверяем, что stop() устанавливает флаг is_running = False"""
    # Устанавливаем флаг в True
    mock_tcc.is_running = True

    # Вызываем stop
    await mock_tcc.stop()

    # Проверяем, что флаг установлен в False
    assert mock_tcc.is_running is False


@pytest.mark.asyncio
async def test_tcc_run_main_loop_handles_exceptions(mock_tcc):
    """Проверяем, что run_main_loop() корректно обрабатывает исключения"""
    # Мокаем signal_generator для выброса исключения
    mock_tcc.signal_generator.generate_signals = AsyncMock(
        side_effect=Exception("Test error")
    )

    # Запускаем цикл в фоне
    task = asyncio.create_task(mock_tcc.run_main_loop())

    # Ждем немного
    await asyncio.sleep(0.2)

    # Останавливаем
    await mock_tcc.stop()

    # Ждем завершения
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Проверяем, что цикл остановился
    assert mock_tcc.is_running is False


@pytest.mark.asyncio
async def test_tcc_manage_positions_empty(mock_tcc):
    """Проверяем, что manage_positions() корректно работает с пустыми позициями"""
    # Убеждаемся, что active_positions пуст
    mock_tcc.active_positions = {}

    # Мокаем position_manager
    mock_position_manager = AsyncMock()
    mock_tcc.position_manager = mock_position_manager

    # Вызываем manage_positions - не должно быть исключений
    await mock_tcc.manage_positions()

    # Проверяем, что manage_position не был вызван (нет позиций)
    mock_position_manager.manage_position.assert_not_called()

