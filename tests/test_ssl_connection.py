#!/usr/bin/env python
"""
Диагностика SSL/сетевого подключения к OKX
"""
import asyncio
import socket
import ssl

import aiohttp
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg), format="{message}")


async def test_ssl_with_ignore():
    """Попытка подключения с игнорированием SSL ошибок"""
    logger.info("🔌 Тест 1: Подключение с отключенной проверкой SSL")

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        connector = aiohttp.TCPConnector(ssl=ssl_context, limit=10)
        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(
                "https://www.okx.com", allow_redirects=False
            ) as resp:
                logger.info(f"✅ Статус: {resp.status}")
                return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


async def test_regular_ssl():
    """Попытка подключения с обычной проверкой SSL"""
    logger.info("🔌 Тест 2: Подключение с обычной проверкой SSL")

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.get(
                "https://www.okx.com", allow_redirects=False
            ) as resp:
                logger.info(f"✅ Статус: {resp.status}")
                return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


async def test_websocket_connection():
    """Попытка подключения к WebSocket"""
    logger.info("🔌 Тест 3: Подключение к WebSocket wss://wspap.okx.com:8443")

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session:
            async with session.ws_connect(
                "wss://wspap.okx.com:8443/ws/v5/public"
            ) as ws:
                logger.info(f"✅ WebSocket подключен")
                return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


async def test_socket_connection():
    """Прямое соединение по TCP"""
    logger.info("🔌 Тест 4: Прямое TCP подключение к www.okx.com:443")

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("www.okx.com", 443), timeout=10
        )
        logger.info("✅ TCP соединение установлено")
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return False


async def main():
    logger.info("=" * 60)
    logger.info("ДИАГНОСТИКА СЕТЕВОГО ПОДКЛЮЧЕНИЯ К OKX")
    logger.info("=" * 60)

    results = []

    # Тест 1: Обычное подключение
    results.append(("Обычное SSL", await test_regular_ssl()))

    # Тест 2: TCP
    results.append(("TCP соединение", await test_socket_connection()))

    # Тест 3: SSL игнорируя ошибки
    results.append(("SSL (без проверки)", await test_ssl_with_ignore()))

    # Тест 4: WebSocket
    results.append(("WebSocket", await test_websocket_connection()))

    logger.info("=" * 60)
    logger.info("ИТОГИ")
    logger.info("=" * 60)
    for name, success in results:
        status = "✅ OK" if success else "❌ FAIL"
        logger.info(f"{status} - {name}")


if __name__ == "__main__":
    asyncio.run(main())
