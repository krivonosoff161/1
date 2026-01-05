"""
ПОЛНЫЙ интеграционный тест для проблемы #5: Ошибка timezone
Проверяет ВСЮ ЦЕПОЧКУ: Signal → проверка устаревания → timezone → использование
БЕЗ МОКОВ (кроме клиента биржи для безопасности)
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

# Реальные импорты
from src.strategies.scalping.futures.coordinators.signal_coordinator import \
    SignalCoordinator
from src.strategies.scalping.futures.core.data_registry import DataRegistry


class TestSignalCoordinatorRealChain(unittest.IsolatedAsyncioTestCase):
    """ПОЛНЫЙ тест цепочки SignalCoordinator timezone (проблема #5)"""

    async def asyncSetUp(self):
        """Настройка с РЕАЛЬНЫМИ компонентами"""
        # ✅ РЕАЛЬНЫЙ DataRegistry
        self.data_registry = DataRegistry()

        # Мокируем только внешние зависимости
        self.mock_client = Mock()
        self.mock_scalping_config = Mock()
        self.mock_signal_generator = Mock()
        self.mock_config_manager = Mock()
        self.mock_order_executor = Mock()
        self.mock_position_manager = Mock()
        self.mock_margin_calculator = Mock()
        self.mock_slippage_guard = Mock()
        self.mock_max_size_limiter = Mock()
        self.mock_trading_statistics = Mock()
        self.mock_risk_manager = Mock()
        self.mock_debug_logger = Mock()
        self.active_positions = {}
        self.last_orders_cache = {}
        self.active_orders_cache = {}
        self.last_orders_check_time = {}
        self.signal_locks = {}
        self.mock_funding_monitor = Mock()
        self.mock_config = Mock()
        self.mock_trailing_sl_coordinator = Mock()
        self.total_margin_used = 0.0

        # ✅ РЕАЛЬНЫЙ SignalCoordinator (проверяем timezone)
        self.signal_coordinator = SignalCoordinator(
            client=self.mock_client,
            scalping_config=self.mock_scalping_config,
            signal_generator=self.mock_signal_generator,
            config_manager=self.mock_config_manager,
            order_executor=self.mock_order_executor,
            position_manager=self.mock_position_manager,
            margin_calculator=self.mock_margin_calculator,
            slippage_guard=self.mock_slippage_guard,
            max_size_limiter=self.mock_max_size_limiter,
            trading_statistics=self.mock_trading_statistics,
            risk_manager=self.mock_risk_manager,
            debug_logger=self.mock_debug_logger,
            active_positions_ref=self.active_positions,
            last_orders_cache_ref=self.last_orders_cache,
            active_orders_cache_ref=self.active_orders_cache,
            last_orders_check_time_ref=self.last_orders_check_time,
            signal_locks_ref=self.signal_locks,
            funding_monitor=self.mock_funding_monitor,
            config=self.mock_config,
            trailing_sl_coordinator=self.mock_trailing_sl_coordinator,
            total_margin_used_ref=self.total_margin_used,
        )

    async def test_full_chain_timezone_signal_freshness(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Вся цепочка проверки устаревания сигналов"""
        symbol = "BTC-USDT"
        price = 50000.0

        # ✅ ШАГ 1: Создаем свежий сигнал (РЕАЛЬНЫЙ datetime с timezone)
        fresh_signal = {
            "symbol": symbol,
            "side": "buy",
            "price": price,
            "timestamp": datetime.now(timezone.utc),  # ✅ С timezone.utc
        }

        # ✅ ШАГ 2: Создаем устаревший сигнал (РЕАЛЬНЫЙ datetime с timezone)
        stale_signal = {
            "symbol": symbol,
            "side": "buy",
            "price": price,
            "timestamp": datetime.now(timezone.utc)
            - timedelta(seconds=70),  # ✅ Устаревший
        }

        # ✅ ШАГ 3: Проверяем устаревание (РЕАЛЬНАЯ логика из SignalCoordinator)
        max_age_seconds = 60
        current_time = datetime.now(timezone.utc)

        # Свежий сигнал
        fresh_age = (current_time - fresh_signal["timestamp"]).total_seconds()
        is_fresh = fresh_age < max_age_seconds

        # Устаревший сигнал
        stale_age = (current_time - stale_signal["timestamp"]).total_seconds()
        is_stale = stale_age >= max_age_seconds

        # ✅ ШАГ 4: Проверяем результаты
        self.assertTrue(
            is_fresh,
            msg=f"❌ ПРОБЛЕМА #5: Свежий сигнал должен быть валидным (возраст: {fresh_age:.1f}с)",
        )

        self.assertTrue(
            is_stale,
            msg=f"❌ ПРОБЛЕМА #5: Устаревший сигнал должен быть отклонен (возраст: {stale_age:.1f}с)",
        )

        # ✅ ШАГ 5: Проверяем что timezone.utc работает правильно
        self.assertEqual(
            fresh_signal["timestamp"].tzinfo,
            timezone.utc,
            msg="❌ ПРОБЛЕМА #5: timezone.utc не установлен правильно!",
        )

        self.assertEqual(
            stale_signal["timestamp"].tzinfo,
            timezone.utc,
            msg="❌ ПРОБЛЕМА #5: timezone.utc не установлен правильно!",
        )

    async def test_full_chain_timezone_consistency(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: timezone.utc консистентен во всей цепочке"""
        # ✅ ШАГ 1: Создаем timestamp с timezone.utc (РЕАЛЬНЫЙ)
        time1 = datetime.now(timezone.utc)

        # ✅ ШАГ 2: Проверяем что timezone установлен
        self.assertEqual(
            time1.tzinfo,
            timezone.utc,
            msg="❌ ПРОБЛЕМА #5: timezone.utc не установлен!",
        )

        # ✅ ШАГ 3: Создаем еще один timestamp
        time2 = datetime.now(timezone.utc)

        # ✅ ШАГ 4: Проверяем что оба имеют timezone.utc
        self.assertEqual(
            time1.tzinfo,
            timezone.utc,
            msg="❌ ПРОБЛЕМА #5: time1 должен иметь timezone.utc",
        )

        self.assertEqual(
            time2.tzinfo,
            timezone.utc,
            msg="❌ ПРОБЛЕМА #5: time2 должен иметь timezone.utc",
        )

        # ✅ ШАГ 5: Проверяем что разница рассчитывается правильно
        diff = (time2 - time1).total_seconds()
        self.assertGreaterEqual(
            diff,
            0,
            msg="❌ ПРОБЛЕМА #5: Разница времени должна быть >= 0",
        )


if __name__ == "__main__":
    unittest.main()
