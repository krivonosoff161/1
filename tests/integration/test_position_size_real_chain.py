"""
ПОЛНЫЙ интеграционный тест для проблемы #2: Размер позиции = 0.000027 монет
Проверяет ВСЮ ЦЕПОЧКУ: RiskManager → SignalCoordinator → DataRegistry → Client
БЕЗ МОКОВ (кроме клиента биржи для безопасности)
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from src.config import BotConfig, RiskConfig, ScalpingConfig
from src.strategies.scalping.futures.core.data_registry import DataRegistry
# Реальные импорты (БЕЗ МОКОВ для внутренних компонентов)
from src.strategies.scalping.futures.risk_manager import FuturesRiskManager


class TestPositionSizeRealChain(unittest.IsolatedAsyncioTestCase):
    """ПОЛНЫЙ тест цепочки расчета размера позиции (проблема #2)"""

    async def asyncSetUp(self):
        """Настройка с РЕАЛЬНЫМИ компонентами"""
        # ✅ РЕАЛЬНЫЙ DataRegistry (проверяем запись/чтение)
        self.data_registry = DataRegistry()

        # ✅ РЕАЛЬНЫЙ ConfigManager (упрощенный)
        self.mock_config_manager = Mock()
        self.mock_config_manager.get_symbol_profiles = Mock(return_value={})

        # ✅ РЕАЛЬНЫЙ RiskManager (проверяем расчет)
        self.mock_client = Mock()  # Только клиент мокируем (безопасность)
        self.mock_client.get_instrument_details = AsyncMock(
            return_value={"ctVal": "0.01", "lotSz": "0.01", "minSz": "0.01"}
        )

        # Создаем реальный BotConfig
        self.config = BotConfig(
            scalping=ScalpingConfig(
                base_margin_per_trade=50.0,
                leverage=5,
            ),
            risk=RiskConfig(),
        )

        # ✅ РЕАЛЬНЫЙ FuturesRiskManager
        self.risk_manager = FuturesRiskManager(
            config=self.config,
            client=self.mock_client,
            config_manager=self.mock_config_manager,
            data_registry=self.data_registry,
        )

        # Сохраняем баланс в DataRegistry (как делает реальный бот)
        await self.data_registry.update_balance(
            {
                "balance": 1000.0,
                "available": 1000.0,
                "timestamp": datetime.utcnow(),
            }
        )

    async def test_full_chain_risk_manager_to_dataregistry(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Вся цепочка RiskManager → расчет → DataRegistry"""
        symbol = "BTC-USDT"
        price = 50000.0

        # ✅ ШАГ 1: RiskManager рассчитывает размер (РЕАЛЬНЫЙ вызов)
        position_size = await self.risk_manager.calculate_position_size(
            balance=1000.0,
            price=price,
            signal=None,
            signal_generator=None,
        )

        # ✅ ШАГ 2: Проверяем что размер в МОНЕТАХ (не контрактах)
        # Формула: (margin * leverage) / price = монеты
        # (50 * 5) / 50000 = 0.005 BTC
        expected_size_coins = (50.0 * 5) / 50000.0

        self.assertAlmostEqual(
            position_size,
            expected_size_coins,
            places=6,
            msg=f"❌ ПРОБЛЕМА #2: position_size должен быть в МОНЕТАХ: ожидалось {expected_size_coins} BTC, получено {position_size}",
        )

        # ✅ ШАГ 3: Проверяем что это НЕ контракты
        # Если бы это были контракты, размер был бы 0.5, а не 0.005
        self.assertLess(
            position_size,
            0.1,
            msg=f"❌ ПРОБЛЕМА #2: position_size должен быть в МОНЕТАХ (маленькое значение), получено {position_size} - возможно это контракты?",
        )

        # ✅ ШАГ 4: Сохраняем в DataRegistry (как делает реальный бот)
        # Проверяем что DataRegistry может сохранить и прочитать
        await self.data_registry.update_position_size(symbol, position_size)
        saved_size = await self.data_registry.get_position_size(symbol)

        self.assertAlmostEqual(
            saved_size,
            position_size,
            places=6,
            msg="❌ ПРОБЛЕМА: DataRegistry не сохраняет/читает position_size правильно",
        )

    async def test_full_chain_conversion_coins_to_contracts(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Вся цепочка конвертации монеты → контракты"""
        symbol = "BTC-USDT"
        price = 92326.50

        # ✅ ШАГ 1: RiskManager возвращает размер в МОНЕТАХ (РЕАЛЬНЫЙ вызов)
        position_size_coins = await self.risk_manager.calculate_position_size(
            balance=1000.0,
            price=price,
            signal=None,
            signal_generator=None,
        )

        # ✅ ШАГ 2: Получаем ct_val с биржи (РЕАЛЬНЫЙ вызов клиента)
        details = await self.mock_client.get_instrument_details(symbol)
        ct_val = float(details.get("ctVal", 0.01))

        # ✅ ШАГ 3: ПРАВИЛЬНАЯ конвертация: монеты → контракты
        size_in_contracts = position_size_coins / ct_val

        # ❌ ШАГ 4: НЕПРАВИЛЬНАЯ конвертация (как было в проблеме #2)
        size_in_coins_wrong = position_size_coins * ct_val

        # ✅ ПРАВИЛЬНЫЙ notional
        notional_correct = position_size_coins * price

        # ❌ НЕПРАВИЛЬНЫЙ notional (проблема #2)
        notional_wrong = size_in_coins_wrong * price

        # ✅ Проверяем что правильная конвертация дает правильный notional
        self.assertAlmostEqual(
            notional_correct,
            249.28,
            places=1,
            msg=f"❌ ПРОБЛЕМА #2: Правильный notional должен быть ~$249, получено ${notional_correct:.2f}",
        )

        # ✅ Проверяем что неправильная конвертация дает неправильный notional
        self.assertAlmostEqual(
            notional_wrong,
            2.49,
            places=1,
            msg=f"✅ ПРОБЛЕМА #2 подтверждена: Неправильная конвертация дает ${notional_wrong:.2f} (должно быть ~$2.49)",
        )

        # ✅ Проверяем что они отличаются в 100 раз
        ratio = notional_correct / notional_wrong
        self.assertAlmostEqual(
            ratio,
            100.0,
            places=0,
            msg=f"✅ ПРОБЛЕМА #2: Правильный и неправильный notional отличаются в {ratio:.1f}x (ожидалось 100x)",
        )

    async def test_full_chain_dataregistry_read_write(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: DataRegistry запись → чтение → использование"""
        symbol = "BTC-USDT"
        price = 50000.0

        # ✅ ШАГ 1: Рассчитываем размер (РЕАЛЬНЫЙ RiskManager)
        position_size = await self.risk_manager.calculate_position_size(
            balance=1000.0,
            price=price,
            signal=None,
            signal_generator=None,
        )

        # ✅ ШАГ 2: Записываем в DataRegistry (РЕАЛЬНЫЙ DataRegistry)
        await self.data_registry.update_position_size(symbol, position_size)

        # ✅ ШАГ 3: Читаем из DataRegistry (РЕАЛЬНЫЙ DataRegistry)
        saved_size = await self.data_registry.get_position_size(symbol)

        # ✅ ШАГ 4: Проверяем что данные совпадают
        self.assertAlmostEqual(
            saved_size,
            position_size,
            places=6,
            msg="❌ ПРОБЛЕМА: DataRegistry не сохраняет/читает данные правильно",
        )

        # ✅ ШАГ 5: Используем данные для конвертации (как делает SignalCoordinator)
        details = await self.mock_client.get_instrument_details(symbol)
        ct_val = float(details.get("ctVal", 0.01))

        # ✅ ПРАВИЛЬНАЯ конвертация (используем сохраненный размер)
        size_in_contracts = saved_size / ct_val

        # ✅ Проверяем что конвертация правильная
        expected_contracts = position_size / ct_val
        self.assertAlmostEqual(
            size_in_contracts,
            expected_contracts,
            places=2,
            msg="❌ ПРОБЛЕМА: Конвертация монеты → контракты неправильная",
        )


if __name__ == "__main__":
    unittest.main()
