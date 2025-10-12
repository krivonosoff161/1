"""
Unit tests for Pivot Points module
"""

import pytest
from unittest.mock import AsyncMock, Mock
from datetime import datetime

from src.indicators.advanced.pivot_calculator import PivotCalculator, PivotLevels
from src.strategies.modules.pivot_points import (
    PivotPointsConfig,
    PivotPointsFilter,
    PivotPointsResult,
)
from src.models import OHLCV


class TestPivotLevels:
    """Тесты уровней Pivot Points"""

    def test_get_all_levels(self):
        """Тест получения всех уровней"""
        levels = PivotLevels(
            pivot_point=100.0,
            resistance_1=102.0,
            resistance_2=104.0,
            resistance_3=106.0,
            support_1=98.0,
            support_2=96.0,
            support_3=94.0,
            calculated_at=1234567890.0,
            source_date="2025-10-12",
        )

        all_levels = levels.get_all_levels()
        assert len(all_levels) == 7
        assert all_levels[0] == 94.0  # S3
        assert all_levels[3] == 100.0  # PP
        assert all_levels[6] == 106.0  # R3

    def test_get_nearest_level_near_pp(self):
        """Тест поиска ближайшего уровня (около PP)"""
        levels = PivotLevels(
            pivot_point=100.0,
            resistance_1=102.0,
            resistance_2=104.0,
            resistance_3=106.0,
            support_1=98.0,
            support_2=96.0,
            support_3=94.0,
            calculated_at=1234567890.0,
            source_date="2025-10-12",
        )

        name, value, distance = levels.get_nearest_level(100.5)
        assert name == "PP"
        assert value == 100.0
        assert distance == 0.5

    def test_get_nearest_level_near_r1(self):
        """Тест поиска ближайшего уровня (около R1)"""
        levels = PivotLevels(
            pivot_point=100.0,
            resistance_1=102.0,
            resistance_2=104.0,
            resistance_3=106.0,
            support_1=98.0,
            support_2=96.0,
            support_3=94.0,
            calculated_at=1234567890.0,
            source_date="2025-10-12",
        )

        name, value, distance = levels.get_nearest_level(101.8)
        assert name == "R1"
        assert value == 102.0
        assert abs(distance - 0.2) < 0.0001  # Floating point tolerance


class TestPivotCalculator:
    """Тесты калькулятора Pivot Points"""

    @pytest.fixture
    def calculator(self):
        """Калькулятор для тестов"""
        return PivotCalculator()

    def create_daily_candles(self, high: float, low: float, close: float) -> list[OHLCV]:
        """Создать дневные свечи"""
        candle = OHLCV(
            timestamp=int(datetime.utcnow().timestamp()),
            symbol="BTC-USDT",
            open=low + (high - low) / 2,
            high=high,
            low=low,
            close=close,
            volume=1000000.0,
            timeframe="1D",
        )
        return [candle]

    def test_calculate_pivots_standard(self, calculator):
        """Тест расчета стандартных Pivot Points"""
        # Arrange: H=110, L=90, C=100
        candles = self.create_daily_candles(high=110, low=90, close=100)

        # Act
        levels = calculator.calculate_pivots(candles)

        # Assert
        assert levels is not None
        # PP = (110 + 90 + 100) / 3 = 100
        assert levels.pivot_point == 100.0
        # R1 = 2*100 - 90 = 110
        assert levels.resistance_1 == 110.0
        # S1 = 2*100 - 110 = 90
        assert levels.support_1 == 90.0

    def test_is_near_level_true(self, calculator):
        """Тест: цена около уровня"""
        # Цена 100.1, уровень 100, допуск 0.2%
        is_near = calculator.is_near_level(100.1, 100.0, 0.002)
        assert is_near is True

    def test_is_near_level_false(self, calculator):
        """Тест: цена далеко от уровня"""
        # Цена 101, уровень 100, допуск 0.2%
        is_near = calculator.is_near_level(101.0, 100.0, 0.002)
        assert is_near is False

    def test_get_level_type_above_pp(self, calculator):
        """Тест определения типа уровня"""
        levels = PivotLevels(
            pivot_point=100.0,
            resistance_1=102.0,
            resistance_2=104.0,
            resistance_3=106.0,
            support_1=98.0,
            support_2=96.0,
            support_3=94.0,
            calculated_at=1234567890.0,
            source_date="2025-10-12",
        )

        # Цена между PP и R1
        level_type = calculator.get_level_type(101.0, levels)
        assert level_type == "BETWEEN_PP_R1"

    def test_insufficient_data(self, calculator):
        """Тест недостаточно данных"""
        candles = []
        levels = calculator.calculate_pivots(candles)
        assert levels is None


class TestPivotPointsFilter:
    """Тесты фильтра Pivot Points"""

    @pytest.fixture
    def mock_client(self):
        """Мок OKX клиента"""
        client = Mock()
        client.get_candles = AsyncMock()
        return client

    @pytest.fixture
    def pivot_config(self):
        """Конфигурация для тестов"""
        return PivotPointsConfig(
            enabled=True,
            level_tolerance_percent=0.003,
            score_bonus_near_level=1,
        )

    @pytest.fixture
    def pivot_filter(self, mock_client, pivot_config):
        """Фильтр для тестов"""
        return PivotPointsFilter(mock_client, pivot_config)

    def create_daily_candles(self, high: float, low: float, close: float):
        """Создать дневные свечи для мока"""
        return [
            OHLCV(
                timestamp=int(datetime.utcnow().timestamp()),
                symbol="BTC-USDT",
                open=low + (high - low) / 2,
                high=high,
                low=low,
                close=close,
                volume=1000000.0,
                timeframe="1D",
            )
        ]

    @pytest.mark.asyncio
    async def test_long_near_support_bonus(self, pivot_filter, mock_client):
        """Тест: LONG около Support = бонус"""
        # Arrange: H=110, L=90, C=100 -> S1=90
        daily_candles = self.create_daily_candles(110, 90, 100)
        mock_client.get_candles.return_value = daily_candles

        # Act: цена 90.1 (около S1)
        result = await pivot_filter.check_entry("BTC-USDT", 90.1, "LONG")

        # Assert
        assert result.near_level is True
        assert result.level_name == "S1"
        assert result.bonus == 1

    @pytest.mark.asyncio
    async def test_short_near_resistance_bonus(self, pivot_filter, mock_client):
        """Тест: SHORT около Resistance = бонус"""
        # Arrange: H=110, L=90, C=100 -> R1=110
        daily_candles = self.create_daily_candles(110, 90, 100)
        mock_client.get_candles.return_value = daily_candles

        # Act: цена 109.9 (около R1)
        result = await pivot_filter.check_entry("BTC-USDT", 109.9, "SHORT")

        # Assert
        assert result.near_level is True
        assert result.level_name == "R1"
        assert result.bonus == 1

    @pytest.mark.asyncio
    async def test_long_near_resistance_no_bonus(self, pivot_filter, mock_client):
        """Тест: LONG около Resistance = нет бонуса"""
        # Arrange
        daily_candles = self.create_daily_candles(110, 90, 100)
        mock_client.get_candles.return_value = daily_candles

        # Act: цена 109.9 (около R1, но сигнал LONG)
        result = await pivot_filter.check_entry("BTC-USDT", 109.9, "LONG")

        # Assert
        assert result.near_level is True
        assert result.level_name == "R1"
        assert result.bonus == 0  # Нет бонуса (LONG около сопротивления)

    @pytest.mark.asyncio
    async def test_not_near_any_level(self, pivot_filter, mock_client):
        """Тест: цена далеко от уровней"""
        # Arrange
        daily_candles = self.create_daily_candles(110, 90, 100)
        mock_client.get_candles.return_value = daily_candles

        # Act: цена 95 (между S2 и S1, не около уровня)
        result = await pivot_filter.check_entry("BTC-USDT", 95.0, "LONG")

        # Assert
        assert result.near_level is False
        assert result.bonus == 0

    @pytest.mark.asyncio
    async def test_disabled_filter(self, mock_client):
        """Тест: выключенный фильтр"""
        config = PivotPointsConfig(enabled=False)
        pivot_filter = PivotPointsFilter(mock_client, config)

        result = await pivot_filter.check_entry("BTC-USDT", 100.0, "LONG")

        assert result.near_level is False
        assert result.bonus == 0
        assert "disabled" in result.reason

    @pytest.mark.asyncio
    async def test_caching(self, pivot_filter, mock_client):
        """Тест кэширования уровней"""
        # Arrange
        daily_candles = self.create_daily_candles(110, 90, 100)
        mock_client.get_candles.return_value = daily_candles

        # Act
        result1 = await pivot_filter.check_entry("BTC-USDT", 90.1, "LONG")
        result2 = await pivot_filter.check_entry("BTC-USDT", 109.9, "SHORT")

        # Assert
        # API вызван только 1 раз (кэш работает)
        assert mock_client.get_candles.call_count == 1

    def test_clear_cache(self, pivot_filter):
        """Тест очистки кэша"""
        # Arrange
        pivot_filter._levels_cache["BTC-USDT"] = (Mock(), 0.0)

        # Act
        pivot_filter.clear_cache("BTC-USDT")

        # Assert
        assert "BTC-USDT" not in pivot_filter._levels_cache

    def test_get_stats(self, pivot_filter):
        """Тест получения статистики"""
        stats = pivot_filter.get_stats()

        assert "enabled" in stats
        assert "cached_symbols" in stats
        assert stats["enabled"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

