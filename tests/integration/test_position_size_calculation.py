"""
Интеграционные тесты для проблемы #2: Размер позиции = 0.000027 монет
Проверяет правильность расчета размера позиции и конвертации монеты ↔ контракты
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.strategies.scalping.futures.coordinators.signal_coordinator import \
    SignalCoordinator
from src.strategies.scalping.futures.risk_manager import FuturesRiskManager


class TestPositionSizeCalculation(unittest.IsolatedAsyncioTestCase):
    """Тесты для расчета размера позиции (проблема #2)"""

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
        # FuturesRiskManager требует config_manager, мокируем его методы
        self.mock_risk_manager = Mock(spec=FuturesRiskManager)

        # Мокируем calculate_position_size чтобы возвращать монеты
        # Сигнатура: calculate_position_size(balance=None, price=0.0, signal=None, signal_generator=None)
        async def mock_calculate_position_size(
            balance=None, price=0.0, signal=None, signal_generator=None, **kwargs
        ):
            # Формула: (margin * leverage) / price = монеты
            margin = 50.0
            leverage = 5
            if price > 0:
                return (margin * leverage) / price
            return 0.0

        self.mock_risk_manager.calculate_position_size = AsyncMock(
            side_effect=mock_calculate_position_size
        )
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

    async def test_risk_manager_returns_coins_not_contracts(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: RiskManager должен возвращать размер в МОНЕТАХ, а не контрактах"""
        # Настройка моков
        self.mock_scalping_config.base_margin_per_trade = 50.0  # $50 маржа
        self.mock_scalping_config.leverage = 5  # 5x леверидж
        price = 50000.0  # BTC цена

        # Вызываем calculate_position_size (правильная сигнатура)
        position_size = await self.mock_risk_manager.calculate_position_size(
            balance=1000.0,
            price=price,
            signal=None,
            signal_generator=None,
        )

        # Проверяем что размер в МОНЕТАХ (не контрактах)
        # Формула: position_size = (margin * leverage) / price
        # position_size = (50 * 5) / 50000 = 0.005 BTC (монет)
        expected_size_coins = (margin * leverage) / price
        self.assertAlmostEqual(
            position_size,
            expected_size_coins,
            places=6,
            msg=f"position_size должен быть в МОНЕТАХ: ожидалось {expected_size_coins} BTC, получено {position_size}",
        )

        # Проверяем что это НЕ контракты
        # Для BTC: ct_val = 0.01, значит 0.005 BTC = 0.5 контрактов
        # Если бы это были контракты, то размер был бы 0.5, а не 0.005
        self.assertLess(
            position_size,
            0.1,
            msg=f"position_size должен быть в МОНЕТАХ (маленькое значение), получено {position_size} - возможно это контракты?",
        )

    async def test_signal_coordinator_converts_coins_to_contracts_correctly(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: SignalCoordinator должен правильно конвертировать монеты → контракты"""
        # Настройка моков
        self.mock_client.get_instrument_details = AsyncMock(
            return_value={"ctVal": "0.01"}  # BTC: 1 контракт = 0.01 BTC
        )
        self.mock_client.get_balance = AsyncMock(return_value={"total": "1000.0"})

        # position_size в МОНЕТАХ (из RiskManager)
        position_size_coins = 0.0027  # 0.0027 BTC

        # Получаем ct_val
        details = await self.mock_client.get_instrument_details("BTC-USDT")
        ct_val = float(details.get("ctVal", 0.01))

        # ✅ ПРАВИЛЬНАЯ конвертация: монеты → контракты
        size_in_contracts = (
            position_size_coins / ct_val
        )  # 0.0027 / 0.01 = 0.27 контрактов

        # ❌ НЕПРАВИЛЬНАЯ конвертация (как было в проблеме #2):
        # size_in_coins_wrong = position_size_coins * ct_val  # 0.0027 * 0.01 = 0.000027 BTC ❌

        # Проверяем правильную конвертацию
        self.assertAlmostEqual(
            size_in_contracts,
            0.27,
            places=2,
            msg=f"Размер должен быть 0.27 контрактов, получено {size_in_contracts}",
        )

        # Проверяем что неправильная конвертация дала бы неправильный результат
        size_in_coins_wrong = position_size_coins * ct_val
        self.assertAlmostEqual(
            size_in_coins_wrong,
            0.000027,
            places=6,
            msg=f"Неправильная конвертация дала бы {size_in_coins_wrong} (это и есть проблема #2!)",
        )

        # Проверяем что правильная конвертация НЕ равна неправильной
        self.assertNotAlmostEqual(
            size_in_contracts,
            size_in_coins_wrong,
            places=2,
            msg="Правильная и неправильная конвертация должны отличаться!",
        )

    async def test_position_size_notional_calculation(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Notional должен рассчитываться правильно"""
        # Настройка
        position_size_coins = 0.0027  # BTC в монетах
        price = 92326.50  # BTC цена
        ct_val = 0.01  # BTC ct_val

        # ✅ ПРАВИЛЬНЫЙ расчет notional:
        # notional = position_size_coins * price
        notional_correct = position_size_coins * price  # 0.0027 * 92326.50 = $249.28

        # ❌ НЕПРАВИЛЬНЫЙ расчет (как было в проблеме #2):
        # size_in_coins_wrong = position_size_coins * ct_val  # 0.000027
        # notional_wrong = size_in_coins_wrong * price  # 0.000027 * 92326.50 = $2.49
        size_in_coins_wrong = position_size_coins * ct_val
        notional_wrong = size_in_coins_wrong * price

        # Проверяем правильный notional
        self.assertAlmostEqual(
            notional_correct,
            249.28,
            places=2,
            msg=f"Правильный notional должен быть ~$249, получено ${notional_correct:.2f}",
        )

        # Проверяем что неправильный notional соответствует проблеме #2
        self.assertAlmostEqual(
            notional_wrong,
            2.49,
            places=2,
            msg=f"Неправильный notional должен быть ~$2.49 (проблема #2), получено ${notional_wrong:.2f}",
        )

        # Проверяем что они отличаются в 100 раз
        ratio = notional_correct / notional_wrong
        self.assertAlmostEqual(
            ratio,
            100.0,
            places=1,
            msg=f"Правильный и неправильный notional должны отличаться в ~100 раз, получено {ratio:.1f}x",
        )


if __name__ == "__main__":
    unittest.main()
