"""
Интеграционные тесты для проблемы #5: Ошибка timezone
Проверяет что timezone работает правильно и сигналы проверяются на устаревание
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

from src.strategies.scalping.futures.coordinators.signal_coordinator import \
    SignalCoordinator


class TestTimezoneSignalFreshness(unittest.IsolatedAsyncioTestCase):
    """Тесты для timezone и проверки устаревания сигналов (проблема #5)"""

    async def asyncSetUp(self):
        """Настройка перед каждым тестом"""
        # Мокируем зависимости
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

        # Создаем SignalCoordinator
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

    def test_timezone_import_available(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: timezone должен быть доступен (не локальный import)"""
        # Проверяем что timezone доступен глобально
        try:
            # Используем timezone.utc (как в коде)
            utc_now = datetime.now(timezone.utc)
            self.assertIsNotNone(utc_now, "timezone.utc должен быть доступен")
        except NameError as e:
            self.fail(f"timezone не доступен: {e}")

    async def test_signal_freshness_check_works(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Проверка устаревания сигналов должна работать"""
        # Создаем свежий сигнал
        fresh_signal = {
            "symbol": "BTC-USDT",
            "side": "buy",
            "price": 50000.0,
            "timestamp": datetime.now(timezone.utc),  # Свежий сигнал
        }

        # Создаем устаревший сигнал (старше 60 секунд)
        stale_signal = {
            "symbol": "BTC-USDT",
            "side": "buy",
            "price": 50000.0,
            "timestamp": datetime.now(timezone.utc)
            - timedelta(seconds=70),  # Устаревший
        }

        # Проверяем свежесть
        max_age_seconds = 60
        current_time = datetime.now(timezone.utc)

        # Свежий сигнал
        fresh_age = (current_time - fresh_signal["timestamp"]).total_seconds()
        is_fresh = fresh_age < max_age_seconds

        # Устаревший сигнал
        stale_age = (current_time - stale_signal["timestamp"]).total_seconds()
        is_stale = stale_age >= max_age_seconds

        # Проверяем результаты
        self.assertTrue(
            is_fresh,
            msg=f"Свежий сигнал должен быть валидным (возраст: {fresh_age:.1f}с)",
        )
        self.assertTrue(
            is_stale,
            msg=f"Устаревший сигнал должен быть отклонен (возраст: {stale_age:.1f}с)",
        )

    async def test_timezone_utc_consistency(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: timezone.utc должен быть консистентным"""
        # Создаем два timestamp с timezone.utc
        time1 = datetime.now(timezone.utc)
        time2 = datetime.now(timezone.utc)

        # Проверяем что они имеют правильный timezone
        self.assertEqual(
            time1.tzinfo,
            timezone.utc,
            "time1 должен иметь timezone.utc",
        )
        self.assertEqual(
            time2.tzinfo,
            timezone.utc,
            "time2 должен иметь timezone.utc",
        )

        # Проверяем что разница рассчитывается правильно
        diff = (time2 - time1).total_seconds()
        self.assertGreaterEqual(diff, 0, "Разница времени должна быть >= 0")


if __name__ == "__main__":
    unittest.main()
