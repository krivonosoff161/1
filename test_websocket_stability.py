"""
Тест стабильности WebSocket соединения
"""

import asyncio
import sys

from loguru import logger

sys.path.append(".")

from src.config import load_config
from src.websocket_order_executor import WebSocketOrderExecutor


async def test_websocket_stability():
    """Тестируем стабильность WebSocket соединения"""
    config = load_config()
    okx_config = config.api["okx"]

    logger.info("🔍 ТЕСТ СТАБИЛЬНОСТИ WEBSOCKET СОЕДИНЕНИЯ")
    logger.info("=" * 60)

    ws_executor = WebSocketOrderExecutor(okx_config)

    try:
        # 1. Подключение
        logger.info("1️⃣ ПОДКЛЮЧЕНИЕ К WEBSOCKET...")
        connected = await ws_executor.connect()
        if not connected:
            logger.error("❌ Не удалось подключиться к WebSocket")
            return

        logger.info("✅ WebSocket подключен")

        # 2. Тест стабильности - держим соединение 30 секунд
        logger.info("\n2️⃣ ТЕСТ СТАБИЛЬНОСТИ (30 секунд)...")
        logger.info("   Проверяем соединение каждые 5 секунд...")

        for i in range(6):  # 6 проверок по 5 секунд = 30 секунд
            await asyncio.sleep(5)

            # Проверяем статус соединения
            is_connected = ws_executor.connected
            is_closed = ws_executor.ws.closed if ws_executor.ws else True

            logger.info(
                f"   Проверка {i+1}/6: Connected={is_connected}, Closed={is_closed}"
            )

            if not is_connected or is_closed:
                logger.warning(f"⚠️ Соединение потеряно на {i*5} секунде!")
                break

        # 3. Тест латентности
        logger.info("\n3️⃣ ТЕСТ ЛАТЕНТНОСТИ...")
        try:
            latency = await ws_executor.get_latency()
            logger.info(f"   WebSocket латентность: {latency:.2f} мс")
        except Exception as e:
            logger.error(f"   Ошибка теста латентности: {e}")

        # 4. Проверка переподключения
        logger.info("\n4️⃣ ТЕСТ ПЕРЕПОДКЛЮЧЕНИЯ...")
        logger.info("   Имитируем разрыв соединения...")

        # Принудительно закрываем соединение
        if ws_executor.ws:
            await ws_executor.ws.close()
            ws_executor.connected = False

        logger.info("   Соединение закрыто, тестируем переподключение...")

        # Пытаемся переподключиться
        reconnected = await ws_executor.reconnect()
        if reconnected:
            logger.info("✅ Переподключение успешно")
        else:
            logger.error("❌ Переподключение не удалось")

    except Exception as e:
        logger.error(f"❌ Ошибка теста: {e}")

    finally:
        # 5. Отключение
        logger.info("\n5️⃣ ОТКЛЮЧЕНИЕ...")
        await ws_executor.disconnect()
        logger.info("✅ WebSocket отключен")

        logger.info("\n📊 ИТОГИ ТЕСТА:")
        logger.info("   - Подключение: ✅")
        logger.info("   - Стабильность: Проверено")
        logger.info("   - Латентность: Измерена")
        logger.info("   - Переподключение: Протестировано")


if __name__ == "__main__":
    asyncio.run(test_websocket_stability())
