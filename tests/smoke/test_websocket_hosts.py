#!/usr/bin/env python
"""
Тест различных WebSocket хостов OKX
"""
import asyncio

import aiohttp
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg), format="{message}")

# Список хостов для тестирования
WEBSOCKET_HOSTS = [
    ("wspap.okx.com:8443", "wss://wspap.okx.com:8443/ws/v5/public"),
    ("wspp.okx.com:8443", "wss://wspp.okx.com:8443/ws/v5/public"),
    ("ws.okx.com:8443", "wss://ws.okx.com:8443/ws/v5/public"),
    ("wspap.okx.com:443", "wss://wspap.okx.com:443/ws/v5/public"),
]


async def test_ws_host(name: str, url: str) -> bool:
    """Тест подключения к WebSocket хосту"""
    logger.info(f"🔌 Тест: {name}")

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as session:
            async with session.ws_connect(url) as ws:
                logger.info(f"  ✅ Успешно подключено к {name}")
                return True
    except asyncio.TimeoutError:
        logger.error(f"  ⏱️  Timeout при подключении к {name}")
        return False
    except Exception as e:
        error_msg = str(e).split("[")[0].strip()  # Убираем деталей ошибки
        logger.error(f"  ❌ Ошибка: {error_msg}")
        return False


async def main():
    logger.info("=" * 60)
    logger.info("ТЕСТИРОВАНИЕ РАЗЛИЧНЫХ WEBSOCKET ХОСТОВ OKX")
    logger.info("=" * 60)

    results = []
    for name, url in WEBSOCKET_HOSTS:
        success = await test_ws_host(name, url)
        results.append((name, success))
        await asyncio.sleep(1)  # Небольшая пауза между попытками

    logger.info("=" * 60)
    logger.info("ИТОГИ")
    logger.info("=" * 60)

    working = [name for name, success in results if success]
    if working:
        logger.info(f"✅ Работающие хосты: {', '.join(working)}")
    else:
        logger.warning("❌ Ни один WebSocket хост не доступен")
        logger.info("\n💡 Возможные решения:")
        logger.info("  1. Использовать VPN для подключения к OKX")
        logger.info("  2. Проверить блокировку firewall/ISP для WebSocket портов")
        logger.info("  3. Использовать только REST API для торговли")
        logger.info("  4. Попробовать позже (может быть временный сбой)")


if __name__ == "__main__":
    asyncio.run(main())
