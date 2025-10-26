import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Детальный тест WebSocket Orchestrator с пошаговой диагностикой
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.config import load_config
from src.okx_client import OKXClient
from src.strategies.scalping.websocket_orchestrator import \
    WebSocketScalpingOrchestrator


async def test_orchestrator_detailed():
    """Детальный тест с пошаговой диагностикой"""
    print("🧪 Detailed WebSocket Orchestrator Test")
    print("=" * 60)

    try:
        # Загружаем конфигурацию
        print("📋 Loading config...")
        config = load_config("config.yaml")

        # Создаем OKX Client
        print("🔧 Creating OKX Client...")
        okx_client = OKXClient(config.get_okx_config())

        # Создаем WebSocket Orchestrator
        print("🔧 Creating WebSocket Orchestrator...")
        orchestrator = WebSocketScalpingOrchestrator(config, okx_client)

        print("✅ Orchestrator created successfully!")
        print(f"   WebSocket Manager: {orchestrator.websocket_manager}")
        print(f"   Is Running: {orchestrator.is_running}")

        # Тестируем каждый шаг start() отдельно
        print("\n🔍 Testing start() method step by step...")

        # Шаг 1: Проверяем WebSocket Manager
        print("1️⃣ Checking WebSocket Manager...")
        print(f"   Connected: {orchestrator.websocket_manager.is_connected}")
        print(f"   Running: {orchestrator.websocket_manager.is_running}")

        # Шаг 2: Тестируем connect() отдельно
        print("2️⃣ Testing WebSocket connect() separately...")
        try:
            connect_result = await asyncio.wait_for(
                orchestrator.websocket_manager.connect(), timeout=5.0
            )
            print(f"   Connect result: {connect_result}")

            if connect_result:
                print("✅ WebSocket connected successfully!")

                # Шаг 3: Тестируем подписки
                print("3️⃣ Testing subscriptions...")
                for symbol in config.trading.symbols:
                    print(f"   Subscribing to ticker: {symbol}")
                    await orchestrator.websocket_manager.subscribe_ticker(symbol)

                    for interval in config.scalping.candle_intervals:
                        print(f"   Subscribing to candles: {symbol} {interval}")
                        await orchestrator.websocket_manager.subscribe_candles(
                            symbol, interval
                        )

                print("✅ All subscriptions completed!")

                # Шаг 4: Тестируем start_listening()
                print("4️⃣ Testing start_listening()...")
                try:
                    # Запускаем start_listening с timeout
                    await asyncio.wait_for(
                        orchestrator.websocket_manager.start_listening(), timeout=3.0
                    )
                    print("✅ start_listening() completed!")
                except asyncio.TimeoutError:
                    print("⏰ start_listening() timed out (expected - it runs forever)")
                except Exception as e:
                    print(f"❌ start_listening() failed: {e}")

                # Отключаемся
                print("🔌 Disconnecting...")
                await orchestrator.websocket_manager.disconnect()
                print("✅ Disconnected successfully!")

                return True
            else:
                print("❌ WebSocket connection failed")
                return False

        except asyncio.TimeoutError:
            print("⏰ WebSocket connect() timed out!")
            print("   This is the problem - websockets.connect() is hanging!")
            return False
        except Exception as e:
            print(f"❌ WebSocket connect() failed: {e}")
            import traceback

            traceback.print_exc()
            return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_orchestrator_detailed())

    if result:
        print("🎉 Test PASSED!")
    else:
        print("💥 Test FAILED!")
        sys.exit(1)
