#!/usr/bin/env python3
"""
Простой тест WebSocket подключения к OKX
Без сложных конфигураций - только подключение
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.websocket_manager import WebSocketPriceManager, WebSocketConfig

async def test_simple_websocket():
    """Простой тест WebSocket подключения"""
    print("🧪 Simple WebSocket Connection Test")
    print("=" * 50)
    
    try:
        # Создаем простую конфигурацию
        print("⚙️ Creating WebSocket config...")
        config = WebSocketConfig()
        print(f"   URL: {config.url}")
        print(f"   Ping interval: {config.ping_interval}")
        
        # Создаем WebSocket Manager
        print("🔌 Creating WebSocket Manager...")
        manager = WebSocketPriceManager(config)
        print(f"   Connected: {manager.is_connected}")
        print(f"   Running: {manager.is_running}")
        
        # Пытаемся подключиться
        print("🚀 Attempting connection...")
        connected = await manager.connect()
        
        if connected:
            print("✅ WebSocket connected successfully!")
            
            # Проверяем статус
            status = manager.get_connection_status()
            print(f"   Status: {status}")
            
            # Тестируем подписку
            print("📊 Testing subscription...")
            await manager.subscribe_ticker("BTC-USDT")
            
            # Ждем немного
            print("⏳ Waiting for data (3 seconds)...")
            await asyncio.sleep(3)
            
            # Отключаемся
            print("🔌 Disconnecting...")
            await manager.disconnect()
            print("✅ Disconnected successfully!")
            
            return True
        else:
            print("❌ Failed to connect")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_simple_websocket())
    
    if result:
        print("🎉 Test PASSED!")
    else:
        print("💥 Test FAILED!")
        sys.exit(1)

