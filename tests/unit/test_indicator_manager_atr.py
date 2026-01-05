"""
Unit тесты для IndicatorManager.calculate_all() с TALibATR (критическая проблема ATR=0.0)
Проверяет что TALibATR правильно рассчитывается через IndicatorManager
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import unittest
from datetime import datetime

from src.indicators import IndicatorManager, TALibATR
from src.models import OHLCV, MarketData


class TestIndicatorManagerATR(unittest.TestCase):
    """Тесты для IndicatorManager.calculate_all() с TALibATR"""

    def setUp(self):
        """Настройка перед каждым тестом"""
        self.indicator_manager = IndicatorManager()
        self.indicator_manager.add_indicator("ATR", TALibATR(period=14))

    def test_atr_calculated_correctly(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: ATR должен рассчитываться правильно (не 0.0)"""
        # Создаем тестовые данные с реальной волатильностью
        candles = [
            OHLCV(
                symbol="BTC-USDT",
                timestamp=int(datetime.utcnow().timestamp() * 1000) + i * 60000,
                open=50000.0 + i * 10,
                high=50100.0 + i * 10 + 50,  # Разница high-low = 150
                low=49900.0 + i * 10 - 50,  # Разница high-low = 150
                close=50050.0 + i * 10,
                volume=1000.0,
            )
            for i in range(50)
        ]

        market_data = MarketData(symbol="BTC-USDT", timeframe="1m", ohlcv_data=candles)

        # Рассчитываем индикаторы
        results = self.indicator_manager.calculate_all(market_data)

        # Проверяем что ATR есть в результатах
        self.assertIn("ATR", results, "ATR должен быть в результатах")

        # Проверяем что ATR не равен 0.0
        atr_result = results["ATR"]
        self.assertIsNotNone(atr_result, "ATR результат не должен быть None")

        # Проверяем что это IndicatorResult
        from src.indicators.base import IndicatorResult

        self.assertIsInstance(
            atr_result, IndicatorResult, "ATR результат должен быть IndicatorResult"
        )

        # Проверяем что значение ATR > 0
        atr_value = atr_result.value
        self.assertIsNotNone(atr_value, "ATR value не должен быть None")
        self.assertGreater(
            atr_value, 0.0, f"ATR должен быть > 0.0, получено {atr_value}"
        )

        # Проверяем что ATR имеет разумное значение (для наших тестовых данных ~150)
        # Допускаем разброс от 50 до 300
        self.assertGreaterEqual(
            atr_value,
            50.0,
            f"ATR должен быть >= 50.0 для наших тестовых данных, получено {atr_value}",
        )
        self.assertLessEqual(
            atr_value,
            300.0,
            f"ATR должен быть <= 300.0 для наших тестовых данных, получено {atr_value}",
        )

    def test_atr_called_with_correct_parameters(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: TALibATR должен вызываться с highs, lows, closes (не только closes)"""
        # Создаем тестовые данные с разной волатильностью
        candles = [
            OHLCV(
                symbol="BTC-USDT",
                timestamp=int(datetime.utcnow().timestamp() * 1000) + i * 60000,
                open=50000.0,
                high=50100.0 + i * 5,  # Высокая волатильность
                low=49900.0 - i * 5,  # Высокая волатильность
                close=50000.0,
                volume=1000.0,
            )
            for i in range(50)
        ]

        market_data = MarketData(symbol="BTC-USDT", timeframe="1m", ohlcv_data=candles)

        # Рассчитываем индикаторы
        results = self.indicator_manager.calculate_all(market_data)

        # Проверяем что ATR рассчитан
        atr_result = results.get("ATR")
        self.assertIsNotNone(atr_result, "ATR должен быть рассчитан")

        # Если ATR вызывался только с closes (неправильно), то значение будет ~0
        # Если ATR вызывался с highs, lows, closes (правильно), то значение будет > 0
        atr_value = atr_result.value
        self.assertGreater(
            atr_value,
            0.0,
            f"ATR должен быть > 0.0 (должен использовать highs/lows), получено {atr_value}",
        )

    def test_indicator_class_name_check(self):
        """Проверяем что TALibATR определяется правильно по имени класса"""
        from src.indicators import TALibATR

        atr_indicator = TALibATR(period=14)
        indicator_class_name = atr_indicator.__class__.__name__

        self.assertEqual(
            indicator_class_name, "TALibATR", "Имя класса должно быть TALibATR"
        )

        # Проверяем что это НЕ является подклассом ATR (из base.py)
        from src.indicators.base import ATR

        self.assertFalse(
            isinstance(atr_indicator, ATR),
            "TALibATR не должен быть подклассом ATR (это и есть проблема!)",
        )


if __name__ == "__main__":
    unittest.main()
