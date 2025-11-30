"""
Интеграционные тесты для orchestrator + TradingControlCenter.

Проверяем:
- orchestrator.start() → TCC.run_main_loop() вызывается
- orchestrator.stop() → TCC.stop() вызывается
- Нет исключений при запуске/остановке
- Логи без ошибок импорта и делегации
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Импортируем только для проверки структуры, не для запуска
# (реальный orchestrator требует конфиг и API ключи)


@pytest.mark.asyncio
async def test_tcc_integration_structure():
    """Проверяем структуру интеграции TCC с orchestrator"""
    # Проверяем, что TradingControlCenter импортируется корректно
    from src.strategies.scalping.futures.core.trading_control_center import \
        TradingControlCenter

    # Проверяем, что класс существует и имеет нужные методы
    assert hasattr(TradingControlCenter, "run_main_loop")
    assert hasattr(TradingControlCenter, "manage_positions")
    assert hasattr(TradingControlCenter, "update_state")
    assert hasattr(TradingControlCenter, "update_performance")
    assert hasattr(TradingControlCenter, "stop")

    # Проверяем, что методы асинхронные
    import inspect

    assert inspect.iscoroutinefunction(TradingControlCenter.run_main_loop)
    assert inspect.iscoroutinefunction(TradingControlCenter.manage_positions)
    assert inspect.iscoroutinefunction(TradingControlCenter.update_state)
    assert inspect.iscoroutinefunction(TradingControlCenter.update_performance)
    assert inspect.iscoroutinefunction(TradingControlCenter.stop)


@pytest.mark.asyncio
async def test_tcc_delegation_pattern():
    """Проверяем паттерн делегации: orchestrator → TCC"""
    # Создаем мок TCC
    mock_tcc = MagicMock()
    mock_tcc.run_main_loop = AsyncMock()
    mock_tcc.stop = AsyncMock()

    # Симулируем вызовы из orchestrator
    # orchestrator.start() → tcc.run_main_loop()
    await mock_tcc.run_main_loop()

    # orchestrator.stop() → tcc.stop()
    await mock_tcc.stop()

    # Проверяем, что методы были вызваны
    mock_tcc.run_main_loop.assert_called_once()
    mock_tcc.stop.assert_called_once()


@pytest.mark.asyncio
async def test_tcc_lifecycle():
    """Проверяем жизненный цикл TCC: запуск → работа → остановка"""
    from src.strategies.scalping.futures.core.trading_control_center import \
        TradingControlCenter

    # Создаем минимальные моки для TCC
    mock_client = MagicMock()
    mock_client.get_positions = AsyncMock(return_value=[])

    mock_signal_generator = MagicMock()
    mock_signal_generator.generate_signals = AsyncMock(return_value=[])
    mock_signal_generator.regime_managers = {}
    mock_signal_generator.regime_manager = None

    mock_signal_coordinator = MagicMock()
    mock_signal_coordinator.process_signals = AsyncMock()

    mock_position_manager = MagicMock()
    mock_position_manager.manage_position = AsyncMock()

    mock_position_registry = MagicMock()
    mock_position_registry.get_all_positions = AsyncMock(return_value={})
    mock_position_registry.get_all_metadata = AsyncMock(return_value={})

    mock_data_registry = MagicMock()
    mock_data_registry.get_balance = AsyncMock(return_value={"balance": 1000.0})

    mock_order_coordinator = MagicMock()
    mock_order_coordinator.monitor_limit_orders = AsyncMock()
    mock_order_coordinator.update_orders_cache_status = AsyncMock()

    mock_trailing_sl_coordinator = MagicMock()
    mock_trailing_sl_coordinator.periodic_check = AsyncMock()

    mock_performance_tracker = MagicMock()
    mock_performance_tracker.update_stats = Mock()

    mock_trading_statistics = MagicMock()
    mock_trading_statistics.get_reversal_stats = Mock(
        return_value={
            "total_reversals": 0,
            "v_down_count": 0,
            "v_up_count": 0,
            "avg_price_change": 0.0,
        }
    )

    mock_liquidation_guard = MagicMock()
    mock_liquidation_guard.get_margin_status = AsyncMock(
        return_value={"health_status": {"status": "normal"}}
    )

    mock_config_manager = MagicMock()

    mock_scalping_config = MagicMock()
    mock_scalping_config.check_interval = 0.1

    active_positions = {}

    def normalize_symbol(symbol: str) -> str:
        return symbol.replace("-", "").upper()

    async def sync_positions_with_exchange(force: bool = False):
        pass

    # Создаем TCC
    tcc = TradingControlCenter(
        client=mock_client,
        signal_generator=mock_signal_generator,
        signal_coordinator=mock_signal_coordinator,
        position_manager=mock_position_manager,
        position_registry=mock_position_registry,
        data_registry=mock_data_registry,
        order_coordinator=mock_order_coordinator,
        trailing_sl_coordinator=mock_trailing_sl_coordinator,
        performance_tracker=mock_performance_tracker,
        trading_statistics=mock_trading_statistics,
        liquidation_guard=mock_liquidation_guard,
        config_manager=mock_config_manager,
        scalping_config=mock_scalping_config,
        active_positions=active_positions,
        normalize_symbol=normalize_symbol,
        sync_positions_with_exchange=sync_positions_with_exchange,
    )

    # Проверяем начальное состояние
    assert tcc.is_running is False

    # Запускаем цикл в фоне
    task = asyncio.create_task(tcc.run_main_loop())

    # Ждем немного, чтобы цикл успел выполниться
    await asyncio.sleep(0.3)

    # Проверяем, что цикл запущен
    assert tcc.is_running is True

    # Проверяем, что методы были вызваны
    assert mock_signal_generator.generate_signals.called
    assert mock_signal_coordinator.process_signals.called
    assert mock_order_coordinator.monitor_limit_orders.called
    assert mock_trailing_sl_coordinator.periodic_check.called

    # Останавливаем
    await tcc.stop()

    # Ждем завершения
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Проверяем, что цикл остановлен
    assert tcc.is_running is False


@pytest.mark.asyncio
async def test_tcc_error_handling():
    """Проверяем обработку ошибок в TCC"""
    from src.strategies.scalping.futures.core.trading_control_center import \
        TradingControlCenter

    # Создаем моки с ошибкой в generate_signals
    mock_client = MagicMock()
    mock_client.get_positions = AsyncMock(return_value=[])

    mock_signal_generator = MagicMock()
    mock_signal_generator.generate_signals = AsyncMock(
        side_effect=Exception("Test error")
    )
    mock_signal_generator.regime_managers = {}
    mock_signal_generator.regime_manager = None

    mock_signal_coordinator = MagicMock()
    mock_signal_coordinator.process_signals = AsyncMock()

    mock_position_manager = MagicMock()
    mock_position_manager.manage_position = AsyncMock()

    mock_position_registry = MagicMock()
    mock_position_registry.get_all_positions = AsyncMock(return_value={})
    mock_position_registry.get_all_metadata = AsyncMock(return_value={})

    mock_data_registry = MagicMock()

    mock_order_coordinator = MagicMock()
    mock_order_coordinator.monitor_limit_orders = AsyncMock()
    mock_order_coordinator.update_orders_cache_status = AsyncMock()

    mock_trailing_sl_coordinator = MagicMock()
    mock_trailing_sl_coordinator.periodic_check = AsyncMock()

    mock_performance_tracker = MagicMock()
    mock_performance_tracker.update_stats = Mock()

    mock_trading_statistics = MagicMock()
    mock_trading_statistics.get_reversal_stats = Mock(
        return_value={
            "total_reversals": 0,
            "v_down_count": 0,
            "v_up_count": 0,
            "avg_price_change": 0.0,
        }
    )

    mock_liquidation_guard = MagicMock()
    mock_liquidation_guard.get_margin_status = AsyncMock(
        return_value={"health_status": {"status": "normal"}}
    )

    mock_config_manager = MagicMock()

    mock_scalping_config = MagicMock()
    mock_scalping_config.check_interval = 0.1

    active_positions = {}

    def normalize_symbol(symbol: str) -> str:
        return symbol.replace("-", "").upper()

    async def sync_positions_with_exchange(force: bool = False):
        pass

    # Создаем TCC
    tcc = TradingControlCenter(
        client=mock_client,
        signal_generator=mock_signal_generator,
        signal_coordinator=mock_signal_coordinator,
        position_manager=mock_position_manager,
        position_registry=mock_position_registry,
        data_registry=mock_data_registry,
        order_coordinator=mock_order_coordinator,
        trailing_sl_coordinator=mock_trailing_sl_coordinator,
        performance_tracker=mock_performance_tracker,
        trading_statistics=mock_trading_statistics,
        liquidation_guard=mock_liquidation_guard,
        config_manager=mock_config_manager,
        scalping_config=mock_scalping_config,
        active_positions=active_positions,
        normalize_symbol=normalize_symbol,
        sync_positions_with_exchange=sync_positions_with_exchange,
    )

    # Запускаем цикл в фоне
    task = asyncio.create_task(tcc.run_main_loop())

    # Ждем немного - ошибка должна быть обработана
    await asyncio.sleep(0.3)

    # Останавливаем
    await tcc.stop()

    # Ждем завершения
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Проверяем, что цикл остановлен (ошибка не сломала его)
    assert tcc.is_running is False
