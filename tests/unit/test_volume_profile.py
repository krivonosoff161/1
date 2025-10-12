"""
Unit tests for Volume Profile module
"""

import pytest
import numpy as np
from typing import List
from unittest.mock import AsyncMock, Mock
from datetime import datetime

from src.indicators.advanced.volume_profile import (
    VolumeProfileCalculator,
    VolumeProfileData,
)
from src.strategies.modules.volume_profile_filter import (
    VolumeProfileConfig,
    VolumeProfileFilter,
    VolumeProfileResult,
)
from src.models import OHLCV


class TestVolumeProfileData:
    """Тесты данных Volume Profile"""

    def test_is_in_value_area_true(self):
        """Тест: цена в Value Area"""
        data = VolumeProfileData(
            poc=100.0,
            vah=105.0,
            val=95.0,
            total_volume=1000000.0,
            price_levels=50,
        )

        assert data.is_in_value_area(100.0) is True
        assert data.is_in_value_area(95.0) is True
        assert data.is_in_value_area(105.0) is True

    def test_is_in_value_area_false(self):
        """Тест: цена вне Value Area"""
        data = VolumeProfileData(
            poc=100.0,
            vah=105.0,
            val=95.0,
            total_volume=1000000.0,
            price_levels=50,
        )

        assert data.is_in_value_area(94.0) is False
        assert data.is_in_value_area(106.0) is False

    def test_get_distance_from_poc(self):
        """Тест расстояния от POC"""
        data = VolumeProfileData(
            poc=100.0,
            vah=105.0,
            val=95.0,
            total_volume=1000000.0,
            price_levels=50,
        )

        distance = data.get_distance_from_poc(102.0)
        assert abs(distance - 0.02) < 0.0001  # 2%


class TestVolumeProfileCalculator:
    """Тесты калькулятора Volume Profile"""

    @pytest.fixture
    def calculator(self):
        """Калькулятор для тестов"""
        return VolumeProfileCalculator(price_buckets=20)

    def create_candles_with_volume_at_level(
        self, target_price: float, candles_count: int = 50
    ) -> List[OHLCV]:
        """Создать свечи с концентрацией объема на определенном уровне"""
        candles = []
        np.random.seed(42)

        for i in range(candles_count):
            # Большинство свечей около target_price
            if i < candles_count * 0.7:  # 70% около target
                low = target_price - 2
                high = target_price + 2
                close = target_price + np.random.uniform(-1, 1)
                volume = 10000  # Высокий объем
            else:
                low = target_price - 10
                high = target_price + 10
                close = target_price + np.random.uniform(-5, 5)
                volume = 1000  # Низкий объем

            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i * 3600,
                symbol="BTC-USDT",
                open=(low + high) / 2,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
            candles.append(candle)

        return candles

    def test_calculate_profile(self, calculator):
        """Тест расчета Volume Profile"""
        # Arrange: создаем свечи с концентрацией объема около 100
        candles = self.create_candles_with_volume_at_level(100.0, 50)

        # Act
        profile = calculator.calculate(candles)

        # Assert
        assert profile is not None
        assert profile.poc is not None
        assert profile.vah > profile.val
        assert profile.total_volume > 0
        # POC должен быть около 100 (где концентрация объема)
        assert 90 < profile.poc < 110

    def test_insufficient_data(self, calculator):
        """Тест недостаточно данных"""
        candles = []
        profile = calculator.calculate(candles)
        assert profile is None

    def test_value_area_contains_poc(self, calculator):
        """Тест: Value Area содержит POC"""
        candles = self.create_candles_with_volume_at_level(100.0, 50)
        profile = calculator.calculate(candles)

        assert profile is not None
        # POC должен быть внутри Value Area
        assert profile.val <= profile.poc <= profile.vah


class TestVolumeProfileFilter:
    """Тесты фильтра Volume Profile"""

    @pytest.fixture
    def mock_client(self):
        """Мок OKX клиента"""
        client = Mock()
        client.get_candles = AsyncMock()
        return client

    @pytest.fixture
    def vp_config(self):
        """Конфигурация для тестов"""
        return VolumeProfileConfig(
            enabled=True,
            lookback_timeframe="1H",
            lookback_candles=50,
            price_buckets=20,
            score_bonus_in_value_area=1,
            score_bonus_near_poc=1,
            poc_tolerance_percent=0.005,
        )

    @pytest.fixture
    def vp_filter(self, mock_client, vp_config):
        """Фильтр для тестов"""
        return VolumeProfileFilter(mock_client, vp_config)

    def create_test_candles(self):
        """Создать тестовые свечи"""
        candles = []
        np.random.seed(42)

        for i in range(50):
            # Концентрация объема около 100
            if i < 35:  # 70%
                price = 100 + np.random.uniform(-2, 2)
                volume = 10000
            else:
                price = 100 + np.random.uniform(-10, 10)
                volume = 1000

            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i * 3600,
                symbol="BTC-USDT",
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                volume=volume,
            )
            candles.append(candle)

        return candles

    @pytest.mark.asyncio
    async def test_in_value_area_bonus(self, vp_filter, mock_client):
        """Тест: цена в Value Area = бонус"""
        # Arrange
        candles = self.create_test_candles()
        mock_client.get_candles.return_value = candles

        # Act: цена 100 (в Value Area)
        result = await vp_filter.check_entry("BTC-USDT", 100.0)

        # Assert
        assert result.in_value_area is True
        assert result.bonus >= 1  # Минимум бонус за Value Area

    @pytest.mark.asyncio
    async def test_near_poc_bonus(self, vp_filter, mock_client):
        """Тест: цена около POC = бонус"""
        # Arrange
        candles = self.create_test_candles()
        mock_client.get_candles.return_value = candles

        # Сначала узнаем где POC
        result_temp = await vp_filter.check_entry("BTC-USDT", 100.0)
        poc_value = result_temp.poc_value

        # Act: цена точно на POC
        result = await vp_filter.check_entry("BTC-USDT", poc_value)

        # Assert
        assert result.near_poc is True
        assert result.bonus >= 1

    @pytest.mark.asyncio
    async def test_outside_value_area_no_bonus(self, vp_filter, mock_client):
        """Тест: цена вне Value Area = нет бонуса"""
        # Arrange
        candles = self.create_test_candles()
        mock_client.get_candles.return_value = candles

        # Act: цена далеко (120)
        result = await vp_filter.check_entry("BTC-USDT", 120.0)

        # Assert
        assert result.in_value_area is False
        assert result.near_poc is False
        assert result.bonus == 0

    @pytest.mark.asyncio
    async def test_disabled_filter(self, mock_client):
        """Тест: выключенный фильтр"""
        config = VolumeProfileConfig(enabled=False)
        vp_filter = VolumeProfileFilter(mock_client, config)

        result = await vp_filter.check_entry("BTC-USDT", 100.0)

        assert result.in_value_area is False
        assert result.bonus == 0
        assert "disabled" in result.reason

    @pytest.mark.asyncio
    async def test_caching(self, vp_filter, mock_client):
        """Тест кэширования профиля"""
        # Arrange
        candles = self.create_test_candles()
        mock_client.get_candles.return_value = candles

        # Act
        result1 = await vp_filter.check_entry("BTC-USDT", 100.0)
        result2 = await vp_filter.check_entry("BTC-USDT", 102.0)

        # Assert
        # API вызван только 1 раз (кэш работает)
        assert mock_client.get_candles.call_count == 1

    def test_clear_cache(self, vp_filter):
        """Тест очистки кэша"""
        # Arrange
        vp_filter._profile_cache["BTC-USDT"] = (Mock(), 0.0)

        # Act
        vp_filter.clear_cache("BTC-USDT")

        # Assert
        assert "BTC-USDT" not in vp_filter._profile_cache

    def test_get_stats(self, vp_filter):
        """Тест получения статистики"""
        stats = vp_filter.get_stats()

        assert "enabled" in stats
        assert "cached_symbols" in stats
        assert "lookback_timeframe" in stats
        assert stats["enabled"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

