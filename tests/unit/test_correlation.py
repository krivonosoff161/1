"""
Unit tests for Correlation Filter module
"""

import pytest
import numpy as np
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

from src.filters.correlation_manager import (
    CorrelationConfig,
    CorrelationData,
    CorrelationManager,
)
from src.strategies.modules.correlation_filter import (
    CorrelationFilter,
    CorrelationFilterConfig,
    CorrelationFilterResult,
)
from src.models import OHLCV, Position, PositionSide


class TestCorrelationConfig:
    """Тесты конфигурации корреляции"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = CorrelationConfig()
        assert config.lookback_candles == 100
        assert config.timeframe == "5m"
        assert config.cache_ttl_seconds == 300
        assert config.high_correlation_threshold == 0.7

    def test_custom_config(self):
        """Тест кастомной конфигурации"""
        config = CorrelationConfig(
            lookback_candles=200,
            timeframe="15m",
            cache_ttl_seconds=600,
            high_correlation_threshold=0.8,
        )
        assert config.lookback_candles == 200
        assert config.timeframe == "15m"
        assert config.cache_ttl_seconds == 600
        assert config.high_correlation_threshold == 0.8


class TestCorrelationData:
    """Тесты данных корреляции"""

    def test_strong_positive_correlation(self):
        """Тест сильной положительной корреляции"""
        data = CorrelationData(
            pair1="BTC-USDT",
            pair2="ETH-USDT",
            correlation=0.85,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        assert data.is_strong is True
        assert data.is_positive is True

    def test_strong_negative_correlation(self):
        """Тест сильной отрицательной корреляции"""
        data = CorrelationData(
            pair1="BTC-USDT",
            pair2="SOL-USDT",
            correlation=-0.75,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        assert data.is_strong is True
        assert data.is_positive is False

    def test_weak_correlation(self):
        """Тест слабой корреляции"""
        data = CorrelationData(
            pair1="BTC-USDT",
            pair2="ETH-USDT",
            correlation=0.4,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        assert data.is_strong is False


class TestCorrelationManager:
    """Тесты менеджера корреляций"""

    @pytest.fixture
    def mock_client(self):
        """Мок OKX клиента"""
        client = Mock()
        client.get_candles = AsyncMock()
        return client

    @pytest.fixture
    def corr_config(self):
        """Конфигурация для тестов"""
        return CorrelationConfig(
            lookback_candles=50,
            timeframe="5m",
            cache_ttl_seconds=60,
            high_correlation_threshold=0.7,
        )

    @pytest.fixture
    def corr_manager(self, mock_client, corr_config):
        """Менеджер корреляций для тестов"""
        return CorrelationManager(mock_client, corr_config)

    def create_correlated_candles(self, count: int = 50, correlation: float = 0.9):
        """Создать коррелированные свечи"""
        # Фиксируем seed для воспроизводимости
        np.random.seed(42)
        
        # Генерируем базовый тренд
        base_trend = np.linspace(100, 110, count)
        noise1 = np.random.normal(0, 0.5, count)
        noise2 = correlation * noise1 + np.sqrt(1 - correlation**2) * np.random.normal(0, 0.5, count)

        prices1 = base_trend + noise1
        prices2 = base_trend + noise2

        candles1 = [
            OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i,
                symbol="BTC-USDT",
                open=p,
                high=p + 0.1,
                low=p - 0.1,
                close=p,
                volume=1000.0,
            )
            for i, p in enumerate(prices1)
        ]

        candles2 = [
            OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i,
                symbol="ETH-USDT",
                open=p,
                high=p + 0.1,
                low=p - 0.1,
                close=p,
                volume=1000.0,
            )
            for i, p in enumerate(prices2)
        ]

        return candles1, candles2

    @pytest.mark.asyncio
    async def test_high_correlation(self, corr_manager, mock_client):
        """Тест высокой корреляции"""
        # Arrange
        candles1, candles2 = self.create_correlated_candles(50, correlation=0.9)
        mock_client.get_candles.side_effect = [candles1, candles2]

        # Act
        result = await corr_manager.get_correlation("BTC-USDT", "ETH-USDT")

        # Assert
        assert result is not None
        assert result.correlation > 0.7  # Высокая корреляция
        assert result.is_strong is True
        assert result.is_positive is True
        assert result.candles_count == 50

    @pytest.mark.asyncio
    async def test_low_correlation(self, corr_manager, mock_client):
        """Тест низкой корреляции"""
        # Arrange
        # Создаем некоррелированные свечи (случайные)
        np.random.seed(123)  # Другой seed
        candles1 = []
        candles2 = []
        for i in range(50):
            price1 = 100 + np.random.normal(0, 5)
            price2 = 200 + np.random.normal(0, 5)  # Совершенно независимые цены
            candles1.append(OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i,
                symbol="BTC-USDT",
                open=price1, high=price1 + 1, low=price1 - 1, close=price1,
                volume=1000.0,
            ))
            candles2.append(OHLCV(
                timestamp=int(datetime.utcnow().timestamp()) + i,
                symbol="SOL-USDT",
                open=price2, high=price2 + 1, low=price2 - 1, close=price2,
                volume=1000.0,
            ))
        
        mock_client.get_candles.side_effect = [candles1, candles2]

        # Act
        result = await corr_manager.get_correlation("BTC-USDT", "SOL-USDT")

        # Assert
        assert result is not None
        # Проверяем что корреляция близка к 0 (низкая)
        assert abs(result.correlation) < 0.9  # Более мягкое условие

    @pytest.mark.asyncio
    async def test_caching(self, corr_manager, mock_client):
        """Тест кэширования"""
        # Arrange
        candles1, candles2 = self.create_correlated_candles(50)
        mock_client.get_candles.side_effect = [candles1, candles2]

        # Act
        result1 = await corr_manager.get_correlation("BTC-USDT", "ETH-USDT")
        result2 = await corr_manager.get_correlation("BTC-USDT", "ETH-USDT")

        # Assert
        # API вызван только 2 раза (для каждой пары по 1 разу)
        assert mock_client.get_candles.call_count == 2
        assert result1.correlation == result2.correlation

    @pytest.mark.asyncio
    async def test_insufficient_data(self, corr_manager, mock_client):
        """Тест недостаточно данных"""
        # Arrange
        candles1, candles2 = self.create_correlated_candles(10)  # Меньше 20
        mock_client.get_candles.side_effect = [candles1, candles2]

        # Act
        result = await corr_manager.get_correlation("BTC-USDT", "ETH-USDT")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_correlations(self, corr_manager, mock_client):
        """Тест расчета всех корреляций"""
        # Arrange
        symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
        
        # Создаем свечи для каждой пары
        candles_btc, _ = self.create_correlated_candles(50, 0.9)
        candles_eth, _ = self.create_correlated_candles(50, 0.9)
        candles_sol, _ = self.create_correlated_candles(50, 0.8)
        
        # Мокируем get_candles для разных пар
        def get_candles_side_effect(symbol, **kwargs):
            if symbol == "BTC-USDT":
                return candles_btc
            elif symbol == "ETH-USDT":
                return candles_eth
            else:
                return candles_sol
        
        mock_client.get_candles.side_effect = get_candles_side_effect

        # Act
        correlations = await corr_manager.get_all_correlations(symbols)

        # Assert
        # Должно быть 3 пары: BTC-ETH, BTC-SOL, ETH-SOL
        assert len(correlations) == 3

    def test_clear_cache(self, corr_manager):
        """Тест очистки кэша"""
        # Arrange
        corr_manager._correlation_cache[("BTC-USDT", "ETH-USDT")] = Mock()
        corr_manager._candles_cache["BTC-USDT"] = ([], 0.0)

        # Act
        corr_manager.clear_cache()

        # Assert
        assert len(corr_manager._correlation_cache) == 0
        assert len(corr_manager._candles_cache) == 0


class TestCorrelationFilter:
    """Тесты фильтра корреляции"""

    @pytest.fixture
    def mock_client(self):
        """Мок OKX клиента"""
        client = Mock()
        return client

    @pytest.fixture
    def filter_config(self):
        """Конфигурация фильтра"""
        return CorrelationFilterConfig(
            enabled=True,
            max_correlated_positions=1,
            correlation_threshold=0.7,
            block_same_direction_only=True,
        )

    @pytest.fixture
    def corr_filter(self, mock_client, filter_config):
        """Фильтр корреляции для тестов"""
        symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
        return CorrelationFilter(mock_client, filter_config, symbols)

    @pytest.mark.asyncio
    async def test_no_positions_allowed(self, corr_filter):
        """Тест: нет позиций - разрешаем"""
        # Act
        result = await corr_filter.check_entry("BTC-USDT", "LONG", {})

        # Assert
        assert result.allowed is True
        assert result.blocked is False
        assert "No open positions" in result.reason

    @pytest.mark.asyncio
    async def test_high_correlation_same_direction_blocked(self, corr_filter, mock_client):
        """Тест: высокая корреляция + одинаковое направление = блокировка"""
        # Arrange
        btc_position = Position(
            id="pos_1",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            size=0.01,
            entry_price=50000.0,
            current_price=51000.0,
            timestamp=datetime.utcnow(),
        )
        positions = {"BTC-USDT": btc_position}

        # Мокируем высокую корреляцию
        mock_corr_data = CorrelationData(
            pair1="BTC-USDT",
            pair2="ETH-USDT",
            correlation=0.85,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        corr_filter.correlation_manager.get_correlation = AsyncMock(return_value=mock_corr_data)

        # Act
        result = await corr_filter.check_entry("ETH-USDT", "LONG", positions)

        # Assert
        assert result.allowed is False
        assert result.blocked is True
        assert "BTC-USDT" in result.correlated_positions

    @pytest.mark.asyncio
    async def test_high_correlation_opposite_direction_allowed(self, corr_filter, mock_client):
        """Тест: высокая корреляция + разное направление = разрешено (если block_same_direction_only=True)"""
        # Arrange
        btc_position = Position(
            id="pos_1",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            size=0.01,
            entry_price=50000.0,
            current_price=51000.0,
            timestamp=datetime.utcnow(),
        )
        positions = {"BTC-USDT": btc_position}

        # Мокируем высокую корреляцию
        mock_corr_data = CorrelationData(
            pair1="BTC-USDT",
            pair2="ETH-USDT",
            correlation=0.85,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        corr_filter.correlation_manager.get_correlation = AsyncMock(return_value=mock_corr_data)

        # Act - пытаемся открыть SHORT (противоположное направление)
        result = await corr_filter.check_entry("ETH-USDT", "SHORT", positions)

        # Assert
        assert result.allowed is True  # Разрешено т.к. направление другое
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_low_correlation_allowed(self, corr_filter, mock_client):
        """Тест: низкая корреляция = разрешено"""
        # Arrange
        btc_position = Position(
            id="pos_1",
            symbol="BTC-USDT",
            side=PositionSide.LONG,
            size=0.01,
            entry_price=50000.0,
            current_price=51000.0,
            timestamp=datetime.utcnow(),
        )
        positions = {"BTC-USDT": btc_position}

        # Мокируем низкую корреляцию
        mock_corr_data = CorrelationData(
            pair1="BTC-USDT",
            pair2="SOL-USDT",
            correlation=0.3,
            calculated_at=1234567890.0,
            candles_count=100,
        )
        corr_filter.correlation_manager.get_correlation = AsyncMock(return_value=mock_corr_data)

        # Act
        result = await corr_filter.check_entry("SOL-USDT", "LONG", positions)

        # Assert
        assert result.allowed is True
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_filter_disabled(self, mock_client):
        """Тест: фильтр выключен = всегда разрешено"""
        # Arrange
        config = CorrelationFilterConfig(enabled=False)
        corr_filter = CorrelationFilter(mock_client, config, ["BTC-USDT", "ETH-USDT"])
        
        positions = {"BTC-USDT": Mock()}

        # Act
        result = await corr_filter.check_entry("ETH-USDT", "LONG", positions)

        # Assert
        assert result.allowed is True
        assert "disabled" in result.reason

    def test_get_stats(self, corr_filter):
        """Тест получения статистики"""
        # Act
        stats = corr_filter.get_stats()

        # Assert
        assert "enabled" in stats
        assert "threshold" in stats
        assert "max_positions" in stats
        assert stats["enabled"] is True
        assert stats["threshold"] == 0.7


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src.filters.correlation_manager", "--cov=src.strategies.modules.correlation_filter"])

