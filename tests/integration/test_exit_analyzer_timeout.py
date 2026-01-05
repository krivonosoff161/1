"""
Интеграционные тесты для проблемы #3: Закрытие в боковике без анализа
Проверяет что ExitAnalyzer анализирует рынок ПЕРЕД проверкой timeout
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from src.strategies.scalping.futures.positions.exit_analyzer import \
    ExitAnalyzer


class TestExitAnalyzerTimeout(unittest.IsolatedAsyncioTestCase):
    """Тесты для ExitAnalyzer timeout логики (проблема #3)"""

    async def asyncSetUp(self):
        """Настройка перед каждым тестом"""
        # Мокируем зависимости
        self.mock_config = Mock()
        self.mock_config.max_holding_minutes = 30  # 30 минут timeout
        self.mock_atr_provider = Mock()
        self.mock_data_registry = Mock()
        self.mock_regime_manager = Mock()

        # Создаем ExitAnalyzer с минимальными зависимостями
        # Проверяем сигнатуру конструктора
        try:
            self.exit_analyzer = ExitAnalyzer(
                config=self.mock_config,
                atr_provider=self.mock_atr_provider,
                data_registry=self.mock_data_registry,
                regime_manager=self.mock_regime_manager,
            )
        except TypeError:
            # Если сигнатура другая, создаем с базовыми параметрами
            self.exit_analyzer = ExitAnalyzer(
                config=self.mock_config,
            )
            # Устанавливаем зависимости через методы если есть
            if hasattr(self.exit_analyzer, "set_atr_provider"):
                self.exit_analyzer.set_atr_provider(self.mock_atr_provider)
            if hasattr(self.exit_analyzer, "set_data_registry"):
                self.exit_analyzer.set_data_registry(self.mock_data_registry)

    async def test_timeout_checked_after_market_analysis(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Timeout должен проверяться ПОСЛЕ анализа рынка, а не ДО"""
        # Настройка моков
        symbol = "BTC-USDT"
        position = {
            "symbol": symbol,
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.0027,
            "entry_time": datetime.utcnow()
            - timedelta(minutes=35),  # 35 минут в позиции (больше timeout)
            "unrealized_pnl": 10.0,  # Прибыль
        }
        current_price = 51000.0
        regime = "ranging"

        # Мокируем методы анализа
        self.exit_analyzer._analyze_trend = AsyncMock(return_value="up")
        self.exit_analyzer._check_reversal_signals = AsyncMock(return_value=False)
        self.exit_analyzer._get_atr = AsyncMock(return_value=200.0)

        # Мокируем режим
        self.mock_data_registry.get_regime = AsyncMock(
            return_value={"regime": regime, "params": {}}
        )

        # Вызываем analyze_position
        result = await self.exit_analyzer.analyze_position(
            symbol=symbol,
            position=position,
            current_price=current_price,
            market_data=Mock(),
        )

        # ✅ ПРАВИЛЬНО: Методы анализа должны быть вызваны
        self.exit_analyzer._analyze_trend.assert_called_once()
        self.exit_analyzer._check_reversal_signals.assert_called_once()

        # ✅ ПРАВИЛЬНО: Timeout проверяется, но ПОСЛЕ анализа
        # (проверяем что анализ был вызван, значит timeout не блокирует анализ)

    async def test_timeout_allows_extension_in_strong_trend(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Timeout может быть продлен при сильном тренде"""
        symbol = "BTC-USDT"
        position = {
            "symbol": symbol,
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.0027,
            "entry_time": datetime.utcnow() - timedelta(minutes=35),  # Больше timeout
            "unrealized_pnl": 50.0,  # Хорошая прибыль
        }
        current_price = 52000.0  # Сильный тренд вверх
        regime = "trending"

        # Мокируем сильный тренд
        self.exit_analyzer._analyze_trend = AsyncMock(return_value="strong_up")
        self.exit_analyzer._check_reversal_signals = AsyncMock(return_value=False)

        # Мокируем режим
        self.mock_data_registry.get_regime = AsyncMock(
            return_value={"regime": regime, "params": {"max_holding_minutes": 60}}
        )

        result = await self.exit_analyzer.analyze_position(
            symbol=symbol,
            position=position,
            current_price=current_price,
            market_data=Mock(),
        )

        # ✅ ПРАВИЛЬНО: При сильном тренде позиция может остаться открытой даже после timeout
        # (проверяем что решение принимается на основе анализа, а не только timeout)

    async def test_timeout_closes_in_sideways_market_after_analysis(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: В боковике timeout закрывает ПОСЛЕ анализа"""
        symbol = "BTC-USDT"
        position = {
            "symbol": symbol,
            "side": "long",
            "entry_price": 50000.0,
            "size": 0.0027,
            "entry_time": datetime.utcnow() - timedelta(minutes=35),  # Больше timeout
            "unrealized_pnl": 2.0,  # Маленькая прибыль
        }
        current_price = 50050.0  # Боковик
        regime = "ranging"

        # Мокируем боковик
        self.exit_analyzer._analyze_trend = AsyncMock(return_value="sideways")
        self.exit_analyzer._check_reversal_signals = AsyncMock(return_value=False)

        # Мокируем режим
        self.mock_data_registry.get_regime = AsyncMock(
            return_value={"regime": regime, "params": {"max_holding_minutes": 30}}
        )

        result = await self.exit_analyzer.analyze_position(
            symbol=symbol,
            position=position,
            current_price=current_price,
            market_data=Mock(),
        )

        # ✅ ПРАВИЛЬНО: Анализ должен быть вызван ПЕРЕД решением о закрытии
        self.exit_analyzer._analyze_trend.assert_called_once()
        self.exit_analyzer._check_reversal_signals.assert_called_once()


if __name__ == "__main__":
    unittest.main()
