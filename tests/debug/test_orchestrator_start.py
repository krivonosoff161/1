import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

#!/usr/bin/env python3
"""
Тест только start() метода WebSocket Orchestrator
Без запуска всего бота
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.config import load_config
from src.okx_client import OKXClient
from src.strategies.scalping.websocket_orchestrator import \
    WebSocketScalpingOrchestrator


async def test_orchestrator_start():
    """Тест только start() метода"""
    print("🧪 Testing WebSocket Orchestrator start() method")
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

        # Тестируем только start() метод
        print("🚀 Testing start() method...")

        # Добавляем timeout для start()
        try:
            result = await asyncio.wait_for(orchestrator.start(), timeout=10.0)
            print(f"✅ Start() completed: {result}")
        except asyncio.TimeoutError:
            print("⏰ Start() timed out after 10 seconds")
            print("   This means the method is hanging!")
            return False
        except Exception as e:
            print(f"❌ Start() failed: {e}")
            import traceback

            traceback.print_exc()
            return False

        # Отключаемся
        print("🔌 Shutting down...")
        await orchestrator.shutdown()

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_orchestrator_start())

    if result:
        print("🎉 Test PASSED!")
    else:
        print("💥 Test FAILED!")
        sys.exit(1)
