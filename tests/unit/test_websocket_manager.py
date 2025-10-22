"""
Unit тесты для WebSocket Manager
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.websocket_manager import (EnhancedLatencyMonitor, LatencyMonitor,
                                   PriceData, WebSocketConfig,
                                   WebSocketPriceManager)


class TestWebSocketConfig:
    """Тесты для WebSocketConfig"""

    def test_default_config(self):
        """Тест создания конфигурации с параметрами по умолчанию"""
        config = WebSocketConfig()

        assert config.url == "wss://ws.okx.com:8443/ws/v5/public"
        assert config.private_url == "wss://ws.okx.com:8443/ws/v5/private"
        assert config.ping_interval == 20
        assert config.ping_timeout == 10
        assert config.close_timeout == 10
        assert config.max_size == 2**20
        assert config.reconnect_interval == 5
        assert config.max_reconnect_attempts == 10


class TestPriceData:
    """Тесты для PriceData"""

    def test_price_data_creation(self):
        """Тест создания объекта PriceData"""
        price_data = PriceData(
            symbol="ETH-USDT",
            price=3851.16,
            timestamp=1698000000.0,
            volume=1000.0,
            bid=3850.0,
            ask=3852.0,
        )

        assert price_data.symbol == "ETH-USDT"
        assert price_data.price == 3851.16
        assert price_data.timestamp == 1698000000.0
        assert price_data.volume == 1000.0
        assert price_data.bid == 3850.0
        assert price_data.ask == 3852.0


class TestWebSocketPriceManager:
    """Тесты для WebSocketPriceManager"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.config = WebSocketConfig()
        self.manager = WebSocketPriceManager(self.config)

    def test_initialization(self):
        """Тест инициализации менеджера"""
        assert self.manager.config == self.config
        assert self.manager.websocket is None
        assert self.manager.is_connected is False
        assert self.manager.is_running is False
        assert self.manager.subscriptions == set()
        assert self.manager.price_callbacks == []
        assert self.manager.error_callbacks == []
        assert self.manager.latency_data == []
        assert self.manager.reconnect_attempts == 0

    def test_add_price_callback(self):
        """Тест добавления callback для цен"""
        callback = Mock()
        self.manager.add_price_callback(callback)

        assert callback in self.manager.price_callbacks

    def test_add_error_callback(self):
        """Тест добавления callback для ошибок"""
        callback = Mock()
        self.manager.add_error_callback(callback)

        assert callback in self.manager.error_callbacks

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Тест успешного подключения"""
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_websocket = AsyncMock()
            mock_connect.return_value = mock_websocket

            result = await self.manager.connect()

            assert result is True
            assert self.manager.is_connected is True
            assert self.manager.websocket == mock_websocket
            assert self.manager.reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """Тест неудачного подключения"""
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result = await self.manager.connect()

            assert result is False
            assert self.manager.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Тест отключения"""
        # Сначала подключаемся
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_websocket = AsyncMock()
            mock_connect.return_value = mock_websocket

            await self.manager.connect()

            # Теперь отключаемся
            await self.manager.disconnect()

            assert self.manager.is_connected is False
            assert self.manager.is_running is False
            mock_websocket.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_ticker_not_connected(self):
        """Тест подписки на тикеры без подключения"""
        result = await self.manager.subscribe_ticker(["ETH-USDT"])

        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_ticker_success(self):
        """Тест успешной подписки на тикеры"""
        # Подключаемся
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_websocket = AsyncMock()
            mock_connect.return_value = mock_websocket

            await self.manager.connect()

            # Подписываемся на тикеры
            result = await self.manager.subscribe_ticker(["ETH-USDT", "BTC-USDT"])

            assert result is True
            assert "ETH-USDT" in self.manager.subscriptions
            assert "BTC-USDT" in self.manager.subscriptions
            mock_websocket.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_candles_success(self):
        """Тест успешной подписки на свечи"""
        # Подключаемся
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_websocket = AsyncMock()
            mock_connect.return_value = mock_websocket

            await self.manager.connect()

            # Подписываемся на свечи
            result = await self.manager.subscribe_candles(["ETH-USDT"], "5m")

            assert result is True
            mock_websocket.send.assert_called_once()

    def test_get_connection_status(self):
        """Тест получения статуса соединения"""
        status = self.manager.get_connection_status()

        assert status["connected"] is False
        assert status["running"] is False
        assert status["subscriptions"] == []
        assert status["latency"] == 0.0
        assert status["reconnect_attempts"] == 0


class TestLatencyMonitor:
    """Тесты для LatencyMonitor"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.monitor = LatencyMonitor(max_samples=5)

    def test_initialization(self):
        """Тест инициализации монитора"""
        assert self.monitor.max_samples == 5
        assert self.monitor.latency_samples == []
        assert self.monitor.last_ping_time == 0

    def test_record_ping(self):
        """Тест записи времени ping"""
        self.monitor.record_ping()

        assert self.monitor.last_ping_time > 0

    def test_record_pong(self):
        """Тест записи времени pong и расчета латентности"""
        self.monitor.record_ping()

        # Имитируем задержку
        import time

        time.sleep(0.01)  # 10ms

        self.monitor.record_pong()

        assert len(self.monitor.latency_samples) == 1
        assert self.monitor.latency_samples[0] > 0
        assert self.monitor.last_ping_time == 0

    def test_get_average_latency(self):
        """Тест получения средней латентности"""
        # Добавляем несколько образцов
        self.monitor.latency_samples = [10.0, 20.0, 30.0]

        avg_latency = self.monitor.get_average_latency()

        assert avg_latency == 20.0

    def test_get_max_latency(self):
        """Тест получения максимальной латентности"""
        self.monitor.latency_samples = [10.0, 50.0, 30.0]

        max_latency = self.monitor.get_max_latency()

        assert max_latency == 50.0

    def test_latency_stats(self):
        """Тест получения статистики латентности"""
        self.monitor.latency_samples = [10.0, 20.0, 30.0]

        stats = self.monitor.get_latency_stats()

        assert stats["avg"] == 20.0
        assert stats["max"] == 30.0
        assert stats["min"] == 10.0
        assert stats["count"] == 3


class TestEnhancedLatencyMonitor:
    """Тесты для EnhancedLatencyMonitor"""

    def setup_method(self):
        """Настройка перед каждым тестом"""
        self.monitor = EnhancedLatencyMonitor(
            max_samples=5, warning_threshold=100.0, critical_threshold=500.0
        )

    def test_initialization(self):
        """Тест инициализации расширенного монитора"""
        assert self.monitor.warning_threshold == 100.0
        assert self.monitor.critical_threshold == 500.0
        assert self.monitor.warning_callbacks == []
        assert self.monitor.critical_callbacks == []

    def test_add_warning_callback(self):
        """Тест добавления callback для предупреждений"""
        callback = Mock()
        self.monitor.add_warning_callback(callback)

        assert callback in self.monitor.warning_callbacks

    def test_add_critical_callback(self):
        """Тест добавления callback для критических задержек"""
        callback = Mock()
        self.monitor.add_critical_callback(callback)

        assert callback in self.monitor.critical_callbacks

    def test_record_pong_warning(self):
        """Тест записи pong с предупреждением о латентности"""
        warning_callback = Mock()
        self.monitor.add_warning_callback(warning_callback)

        # Добавляем высокую латентность
        self.monitor.latency_samples = [150.0]  # Выше warning_threshold

        self.monitor.record_pong()

        warning_callback.assert_called_once_with(150.0)

    def test_record_pong_critical(self):
        """Тест записи pong с критической латентностью"""
        critical_callback = Mock()
        self.monitor.add_critical_callback(critical_callback)

        # Добавляем критическую латентность
        self.monitor.latency_samples = [600.0]  # Выше critical_threshold

        self.monitor.record_pong()

        critical_callback.assert_called_once_with(600.0)
