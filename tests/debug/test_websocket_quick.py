"""
Быстрый тест WebSocket компонентов
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.websocket_manager import (PriceData, WebSocketConfig,
                                   WebSocketPriceManager)


def test_websocket_config():
    """Тест конфигурации WebSocket"""
    config = WebSocketConfig()
    assert config.url == "wss://ws.okx.com:8443/ws/v5/public"
    assert config.ping_interval == 20


def test_price_data():
    """Тест данных о цене"""
    price_data = PriceData(symbol="ETH-USDT", price=3851.16, timestamp=1698000000.0)
    assert price_data.symbol == "ETH-USDT"
    assert price_data.price == 3851.16


def test_websocket_manager_init():
    """Тест инициализации WebSocket менеджера"""
    config = WebSocketConfig()
    manager = WebSocketPriceManager(config)

    assert manager.config == config
    assert manager.is_connected is False
    assert manager.is_running is False


@pytest.mark.asyncio
async def test_websocket_connect():
    """Тест подключения WebSocket"""
    config = WebSocketConfig()
    manager = WebSocketPriceManager(config)

    with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_websocket = AsyncMock()
        mock_connect.return_value = mock_websocket

        result = await manager.connect()

        assert result is True
        assert manager.is_connected is True


def test_websocket_callbacks():
    """Тест добавления callbacks"""
    config = WebSocketConfig()
    manager = WebSocketPriceManager(config)

    price_callback = Mock()
    error_callback = Mock()

    manager.add_price_callback(price_callback)
    manager.add_error_callback(error_callback)

    assert price_callback in manager.price_callbacks
    assert error_callback in manager.error_callbacks


def test_websocket_connection_status():
    """Тест статуса соединения"""
    config = WebSocketConfig()
    manager = WebSocketPriceManager(config)

    status = manager.get_connection_status()

    assert status["connected"] is False
    assert status["running"] is False
    assert status["subscriptions"] == []
    assert status["latency"] == 0.0


if __name__ == "__main__":
    print("🧪 Running WebSocket quick tests...")

    # Запуск тестов
    test_websocket_config()
    print("✅ WebSocket config test passed")

    test_price_data()
    print("✅ Price data test passed")

    test_websocket_manager_init()
    print("✅ WebSocket manager init test passed")

    test_websocket_callbacks()
    print("✅ WebSocket callbacks test passed")

    test_websocket_connection_status()
    print("✅ WebSocket connection status test passed")

    print("🎉 All WebSocket quick tests passed!")
