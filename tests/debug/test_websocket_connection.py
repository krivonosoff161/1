#!/usr/bin/env python3
"""
Тест WebSocket подключения к OKX
Проверяет только подключение без запуска всего бота
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.websocket_manager import WebSocketPriceManager, WebSocketConfig
from src.config import load_config

async def test_websocket_connection():
    """Тест подключения к WebSocket OKX"""
    print("🔧 Testing WebSocket Connection...")
    
    try:
        # Загружаем конфигурацию
        print("📋 Loading config...")
        config = load_config("config.yaml")
        
        # Создаем WebSocket конфигурацию
        print("⚙️ Creating WebSocket config...")
        websocket_config = WebSocketConfig(
            url="wss://ws.okx.com:8443/ws/v5/public",
            ping_interval=20,
            ping_timeout=10,
            close_timeout=10,
            max_size=2**20,
            reconnect_attempts=5,
            reconnect_delay=5
        )
        
        # Создаем WebSocket Manager
        print("🔌 Creating WebSocket Manager...")
        websocket_manager = WebSocketPriceManager(websocket_config)
        
        # Пытаемся подключиться
        print("🚀 Attempting connection...")
        connected = await websocket_manager.connect()
        
        if connected:
            print("✅ WebSocket connected successfully!")
            
            # Тестируем подписку на тикер
            print("📊 Testing ticker subscription...")
            await websocket_manager.subscribe_ticker("BTC-USDT")
            
            # Ждем немного для получения данных
            print("⏳ Waiting for data (5 seconds)...")
            await asyncio.sleep(5)
            
            # Отключаемся
            print("🔌 Disconnecting...")
            await websocket_manager.disconnect()
            print("✅ Test completed successfully!")
            
        else:
            print("❌ Failed to connect to WebSocket")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    print("🧪 WebSocket Connection Test")
    print("=" * 50)
    
    result = asyncio.run(test_websocket_connection())
    
    if result:
        print("🎉 Test PASSED!")
    else:
        print("💥 Test FAILED!")
        sys.exit(1)

