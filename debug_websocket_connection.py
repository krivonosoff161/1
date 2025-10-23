"""
Глубокая диагностика WebSocket соединения
"""

import asyncio
import sys

from loguru import logger

sys.path.append(".")

from src.config import load_config
from src.websocket_order_executor import WebSocketOrderExecutor


async def debug_websocket_connection():
    """Глубокая диагностика WebSocket"""
    config = load_config()
    okx_config = config.api["okx"]

    logger.info("🔍 ГЛУБОКАЯ ДИАГНОСТИКА WEBSOCKET")
    logger.info("=" * 50)

    ws_executor = WebSocketOrderExecutor(okx_config)

    try:
        # 1. Подключение с детальным логированием
        logger.info("1️⃣ ПОДКЛЮЧЕНИЕ...")
        connected = await ws_executor.connect()

        if connected:
            logger.info("✅ Подключение успешно")
            logger.info(f"   Connected: {ws_executor.connected}")
            logger.info(f"   WS exists: {ws_executor.ws is not None}")
            if ws_executor.ws:
                logger.info(f"   WS closed: {ws_executor.ws.closed}")
        else:
            logger.error("❌ Подключение не удалось")
            return

        # 2. Ждем немного и проверяем статус
        logger.info("\n2️⃣ ПРОВЕРКА СТАТУСА ЧЕРЕЗ 2 СЕКУНДЫ...")
        await asyncio.sleep(2)

        logger.info(f"   Connected: {ws_executor.connected}")
        logger.info(f"   WS exists: {ws_executor.ws is not None}")
        if ws_executor.ws:
            logger.info(f"   WS closed: {ws_executor.ws.closed}")

        # 3. Пытаемся отправить ping
        logger.info("\n3️⃣ ТЕСТ PING...")
        try:
            if ws_executor.ws and not ws_executor.ws.closed:
                ping_msg = {"op": "ping"}
                await ws_executor.ws.send_str(ping_msg)
                logger.info("✅ Ping отправлен")
            else:
                logger.warning("⚠️ WebSocket недоступен для ping")
        except Exception as e:
            logger.error(f"❌ Ошибка ping: {e}")

        # 4. Проверяем listener
        logger.info("\n4️⃣ ПРОВЕРКА LISTENER...")
        if ws_executor.ws and not ws_executor.ws.closed:
            logger.info("✅ WebSocket доступен для listener")
        else:
            logger.warning("⚠️ WebSocket недоступен для listener")

        # 5. Ждем еще и проверяем
        logger.info("\n5️⃣ ПРОВЕРКА ЧЕРЕЗ 5 СЕКУНД...")
        await asyncio.sleep(5)

        logger.info(f"   Connected: {ws_executor.connected}")
        logger.info(f"   WS exists: {ws_executor.ws is not None}")
        if ws_executor.ws:
            logger.info(f"   WS closed: {ws_executor.ws.closed}")

    except Exception as e:
        logger.error(f"❌ Ошибка диагностики: {e}")

    finally:
        logger.info("\n6️⃣ ОТКЛЮЧЕНИЕ...")
        await ws_executor.disconnect()
        logger.info("✅ Отключение завершено")


if __name__ == "__main__":
    asyncio.run(debug_websocket_connection())
