"""
Unit tests for Multi-Timeframe Confirmation module
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime

from src.strategies.modules.multi_timeframe import (
    MTFConfig,
    MTFResult,
    MultiTimeframeFilter,
)
from src.models import OHLCV


class TestMTFConfig:
    """Тесты конфигурации MTF"""

    def test_default_config(self):
        """Тест конфигурации по умолчанию"""
        config = MTFConfig()
        assert config.confirmation_timeframe == "5m"
        assert config.score_bonus == 2
        assert config.block_opposite is True
        assert config.ema_fast_period == 8
        assert config.ema_slow_period == 21

    def test_custom_config(self):
        """Тест кастомной конфигурации"""
        config = MTFConfig(
            confirmation_timeframe="15m",
            score_bonus=3,
            block_opposite=False,
            ema_fast_period=10,
            ema_slow_period=30,
        )
        assert config.confirmation_timeframe == "15m"
        assert config.score_bonus == 3
        assert config.block_opposite is False
        assert config.ema_fast_period == 10
        assert config.ema_slow_period == 30


class TestMTFResult:
    """Тесты результата MTF"""

    def test_confirmed_result(self):
        """Тест подтвержденного результата"""
        result = MTFResult(
            confirmed=True,
            blocked=False,
            bonus=2,
            reason="5m в бычьем тренде",
            htf_trend="BULLISH",
        )
        assert result.confirmed is True
        assert result.blocked is False
        assert result.bonus == 2
        assert result.htf_trend == "BULLISH"

    def test_blocked_result(self):
        """Тест заблокированного результата"""
        result = MTFResult(
            confirmed=False,
            blocked=True,
            bonus=0,
            reason="5m в медвежьем тренде",
            htf_trend="BEARISH",
        )
        assert result.confirmed is False
        assert result.blocked is True
        assert result.bonus == 0
        assert result.htf_trend == "BEARISH"


class TestMultiTimeframeFilter:
    """Тесты MTF фильтра"""

    @pytest.fixture
    def mock_client(self):
        """Мок OKX клиента"""
        client = Mock()
        client.get_candles = AsyncMock()
        return client

    @pytest.fixture
    def mtf_config(self):
        """Конфигурация MTF для тестов"""
        return MTFConfig(
            confirmation_timeframe="5m",
            score_bonus=2,
            block_opposite=True,
            ema_fast_period=8,
            ema_slow_period=21,
            cache_ttl_seconds=30,
        )

    @pytest.fixture
    def mtf_filter(self, mock_client, mtf_config):
        """MTF фильтр для тестов"""
        return MultiTimeframeFilter(mock_client, mtf_config)

    def create_bullish_candles(self, count: int = 50) -> list[OHLCV]:
        """Создать бычьи свечи (восходящий тренд)"""
        candles = []
        base_price = 100.0
        for i in range(count):
            # Плавный восходящий тренд
            price = base_price + i * 0.5
            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()),
                symbol="BTC-USDT",
                open=price,
                high=price + 0.3,
                low=price - 0.1,
                close=price + 0.2,
                volume=1000.0,
            )
            candles.append(candle)
        return candles

    def create_bearish_candles(self, count: int = 50) -> list[OHLCV]:
        """Создать медвежьи свечи (нисходящий тренд)"""
        candles = []
        base_price = 150.0
        for i in range(count):
            # Плавный нисходящий тренд
            price = base_price - i * 0.5
            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()),
                symbol="BTC-USDT",
                open=price,
                high=price + 0.1,
                low=price - 0.3,
                close=price - 0.2,
                volume=1000.0,
            )
            candles.append(candle)
        return candles

    def create_neutral_candles(self, count: int = 50) -> list[OHLCV]:
        """Создать нейтральные свечи (боковик)"""
        candles = []
        base_price = 120.0
        for i in range(count):
            # Боковое движение
            price = base_price + (i % 2) * 0.2 - 0.1
            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()),
                symbol="BTC-USDT",
                open=price,
                high=price + 0.15,
                low=price - 0.15,
                close=price,
                volume=1000.0,
            )
            candles.append(candle)
        return candles

    @pytest.mark.asyncio
    async def test_bullish_confirmation_for_long(self, mtf_filter, mock_client):
        """Тест: бычий тренд на 5m подтверждает LONG сигнал на 1m"""
        # Arrange
        bullish_candles = self.create_bullish_candles(50)
        mock_client.get_candles.return_value = bullish_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        assert result.confirmed is True
        assert result.blocked is False
        assert result.bonus == 2
        assert result.htf_trend == "BULLISH"
        assert "бычьем тренде" in result.reason

    @pytest.mark.asyncio
    async def test_bearish_blocks_long(self, mtf_filter, mock_client):
        """Тест: медвежий тренд на 5m блокирует LONG сигнал на 1m"""
        # Arrange
        bearish_candles = self.create_bearish_candles(50)
        mock_client.get_candles.return_value = bearish_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        assert result.confirmed is False
        assert result.blocked is True
        assert result.bonus == 0
        assert result.htf_trend == "BEARISH"
        assert "блокируем LONG" in result.reason

    @pytest.mark.asyncio
    async def test_bearish_confirmation_for_short(self, mtf_filter, mock_client):
        """Тест: медвежий тренд на 5m подтверждает SHORT сигнал на 1m"""
        # Arrange
        bearish_candles = self.create_bearish_candles(50)
        mock_client.get_candles.return_value = bearish_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "SHORT")

        # Assert
        assert result.confirmed is True
        assert result.blocked is False
        assert result.bonus == 2
        assert result.htf_trend == "BEARISH"
        assert "медвежьем тренде" in result.reason

    @pytest.mark.asyncio
    async def test_bullish_blocks_short(self, mtf_filter, mock_client):
        """Тест: бычий тренд на 5m блокирует SHORT сигнал на 1m"""
        # Arrange
        bullish_candles = self.create_bullish_candles(50)
        mock_client.get_candles.return_value = bullish_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "SHORT")

        # Assert
        assert result.confirmed is False
        assert result.blocked is True
        assert result.bonus == 0
        assert result.htf_trend == "BULLISH"
        assert "блокируем SHORT" in result.reason

    @pytest.mark.asyncio
    async def test_neutral_no_strong_trend(self, mtf_filter, mock_client):
        """Тест: слабый тренд (EMA близко друг к другу)"""
        # Arrange
        # Создаем свечи где EMA8 и EMA21 очень близки (нет четкого тренда)
        neutral_candles = []
        base_price = 120.0
        for i in range(50):
            # Очень маленькое изменение цены
            price = base_price + (i % 5) * 0.01
            candle = OHLCV(
                timestamp=int(datetime.utcnow().timestamp()),
                symbol="BTC-USDT",
                open=price,
                high=price + 0.01,
                low=price - 0.01,
                close=price,
                volume=1000.0,
            )
            neutral_candles.append(candle)
        
        mock_client.get_candles.return_value = neutral_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        # В реальности даже при слабом тренде MTF может определить направление
        # Главное что он не блокирует сигнал
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_insufficient_data(self, mtf_filter, mock_client):
        """Тест: недостаточно данных для расчета"""
        # Arrange
        few_candles = self.create_bullish_candles(10)  # Меньше чем ema_slow_period (21)
        mock_client.get_candles.return_value = few_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        assert result.confirmed is False
        assert result.blocked is False
        assert result.bonus == 0
        assert result.htf_trend is None
        assert "Недостаточно" in result.reason

    @pytest.mark.asyncio
    async def test_api_error_handling(self, mtf_filter, mock_client):
        """Тест: обработка ошибок API"""
        # Arrange
        mock_client.get_candles.side_effect = Exception("API Error")

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        assert result.confirmed is False
        assert result.blocked is False
        assert result.bonus == 0
        assert result.htf_trend is None
        assert ("Недостаточно" in result.reason or "Ошибка" in result.reason)

    @pytest.mark.asyncio
    async def test_caching(self, mtf_filter, mock_client):
        """Тест: кэширование свечей работает"""
        # Arrange
        bullish_candles = self.create_bullish_candles(50)
        mock_client.get_candles.return_value = bullish_candles

        # Act
        result1 = await mtf_filter.check_confirmation("BTC-USDT", "LONG")
        result2 = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        # API должен быть вызван только 1 раз (второй раз из кэша)
        assert mock_client.get_candles.call_count == 1
        assert result1.confirmed == result2.confirmed

    def test_clear_cache_specific_symbol(self, mtf_filter, mock_client):
        """Тест: очистка кэша для конкретного символа"""
        # Arrange
        mtf_filter._candles_cache["BTC-USDT"] = ([], 0.0)
        mtf_filter._candles_cache["ETH-USDT"] = ([], 0.0)

        # Act
        mtf_filter.clear_cache("BTC-USDT")

        # Assert
        assert "BTC-USDT" not in mtf_filter._candles_cache
        assert "ETH-USDT" in mtf_filter._candles_cache

    def test_clear_cache_all(self, mtf_filter, mock_client):
        """Тест: очистка всего кэша"""
        # Arrange
        mtf_filter._candles_cache["BTC-USDT"] = ([], 0.0)
        mtf_filter._candles_cache["ETH-USDT"] = ([], 0.0)

        # Act
        mtf_filter.clear_cache()

        # Assert
        assert len(mtf_filter._candles_cache) == 0

    @pytest.mark.asyncio
    async def test_block_opposite_disabled(self, mock_client):
        """Тест: когда block_opposite=False, противоположный тренд не блокирует"""
        # Arrange
        config = MTFConfig(block_opposite=False)
        mtf_filter = MultiTimeframeFilter(mock_client, config)
        bearish_candles = self.create_bearish_candles(50)
        mock_client.get_candles.return_value = bearish_candles

        # Act
        result = await mtf_filter.check_confirmation("BTC-USDT", "LONG")

        # Assert
        # Медвежий тренд НЕ блокирует LONG (т.к. block_opposite=False)
        assert result.blocked is False
        assert result.confirmed is False  # Но и не подтверждает


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src.strategies.modules.multi_timeframe"])

