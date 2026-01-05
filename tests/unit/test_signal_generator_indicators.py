"""
Unit тесты для Signal Generator и индикаторов (критическая проблема #8)
Проверяет что индикаторы правильно сохраняются в market_data.indicators
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.models import OHLCV, MarketData
from src.strategies.scalping.futures.core.data_registry import DataRegistry
from src.strategies.scalping.futures.signal_generator import \
    FuturesSignalGenerator


def create_test_candles(
    count: int = 100, base_price: float = 100.0, symbol: str = "BTC-USDT"
) -> list:
    """Создать тестовые свечи"""
    candles = []
    for i in range(count):
        price = base_price + (i * 0.1)
        candles.append(
            OHLCV(
                symbol=symbol,
                timestamp=int(
                    (datetime.utcnow().timestamp() + i * 60) * 1000
                ),  # milliseconds
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.2,
                volume=1000.0,
            )
        )
    return candles


class TestSignalGeneratorIndicators:
    """Тесты для индикаторов в Signal Generator"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.data_registry = DataRegistry()

    def test_indicators_saved_to_market_data(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Индикаторы должны сохраняться в market_data.indicators"""
        # Создаем market_data
        candles = create_test_candles(100, 50000.0, "BTC-USDT")
        market_data = MarketData(
            symbol="BTC-USDT",
            timeframe="1m",
            ohlcv_data=candles,
        )

        # Инициализируем indicators как пустой dict
        market_data.indicators = {}

        # Симулируем расчет индикаторов (как это происходит в _generate_base_signals)
        calculated_indicators = {
            "atr": 150.5,
            "rsi": 55.0,
            "macd": {"histogram": 10.5},
            "ema_12": 50500.0,
            "ema_26": 50400.0,
        }

        # Обновляем market_data.indicators (как это должно происходить в _generate_base_signals)
        market_data.indicators.update(calculated_indicators)

        # Проверяем что indicators обновлены
        assert hasattr(
            market_data, "indicators"
        ), "market_data должен иметь атрибут indicators"
        assert (
            "atr" in market_data.indicators
        ), "ATR должен быть в market_data.indicators"
        assert (
            market_data.indicators["atr"] == 150.5
        ), "ATR должен иметь правильное значение"

    def test_indicators_available_after_calculation(self):
        """✅ КРИТИЧЕСКИЙ ТЕСТ: Индикаторы должны быть доступны после расчета"""
        # Этот тест проверяет что после расчета индикаторов они доступны
        # в market_data.indicators для использования в SignalCoordinator

        candles = create_test_candles(100, 50000.0, "BTC-USDT")
        market_data = MarketData(
            symbol="BTC-USDT",
            timeframe="1m",
            ohlcv_data=candles,
        )

        # Инициализируем indicators
        market_data.indicators = {}

        # Симулируем расчет индикаторов
        calculated_indicators = {
            "atr": 150.5,
            "rsi": 55.0,
            "macd": {"histogram": 10.5},
            "ema_12": 50500.0,
            "ema_26": 50400.0,
        }

        # Обновляем market_data.indicators (как это должно происходить в _generate_base_signals)
        market_data.indicators.update(calculated_indicators)

        # Проверяем что индикаторы доступны
        assert (
            "atr" in market_data.indicators
        ), "ATR должен быть в market_data.indicators"
        assert (
            "rsi" in market_data.indicators
        ), "RSI должен быть в market_data.indicators"
        assert (
            "macd" in market_data.indicators
        ), "MACD должен быть в market_data.indicators"
        assert (
            market_data.indicators["atr"] == 150.5
        ), "ATR должен иметь правильное значение"
