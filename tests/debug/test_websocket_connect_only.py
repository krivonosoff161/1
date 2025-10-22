#!/usr/bin/env python3
"""
Тест только WebSocket.connect() метода
Проверяем где именно зависает
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.websocket_manager import WebSocketConfig, WebSocketPriceManager


async def test_websocket_connect_only():
    """Тест только connect() метода"""
    print("🧪 Testing WebSocket connect() method only")
    print("=" * 50)

    try:
        # Создаем WebSocket Manager
        print("🔧 Creating WebSocket Manager...")
        config = WebSocketConfig()
        manager = WebSocketPriceManager(config)

        print(f"   URL: {config.url}")
        print(f"   Connected: {manager.is_connected}")

        # Тестируем только connect() с timeout
        print("🚀 Testing connect() with timeout...")

        try:
            result = await asyncio.wait_for(manager.connect(), timeout=5.0)
            print(f"✅ Connect() completed: {result}")

            if result:
                print("✅ WebSocket connected successfully!")
                await manager.disconnect()
                print("✅ Disconnected successfully!")
            else:
                print("❌ WebSocket connection failed")

        except asyncio.TimeoutError:
            print("⏰ Connect() timed out after 5 seconds")
            print("   This means websockets.connect() is hanging!")
            return False
        except Exception as e:
            print(f"❌ Connect() failed: {e}")
            import traceback

            traceback.print_exc()
            return False

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_websocket_connect_only())

    if result:
        print("🎉 Test PASSED!")
    else:
        print("💥 Test FAILED!")
        sys.exit(1)
