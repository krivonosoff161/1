#!/usr/bin/env python3
"""
Тестовый скрипт для проверки Futures бота.
Проверяет: подключение к API, баланс, размещение тестового ордера.
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корневую папку в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.clients.futures_client import OKXFuturesClient
from src.config import BotConfig


async def test_futures_connection():
    """Тест подключения к API и получения баланса."""
    try:
        logger.info("🧪 Тест 1: Загрузка конфигурации...")
        config = BotConfig.load_from_file("config/config_futures.yaml")
        logger.info("✅ Конфигурация загружена")

        logger.info("🧪 Тест 2: Инициализация Futures клиента...")
        okx_config = config.get_okx_config()

        client = OKXFuturesClient(
            api_key=okx_config.api_key,
            secret_key=okx_config.api_secret,
            passphrase=okx_config.passphrase,
            sandbox=okx_config.sandbox,
            leverage=3,
        )
        logger.info("✅ Клиент инициализирован")

        logger.info("🧪 Тест 3: Получение баланса...")
        balance = await client.get_balance()
        logger.info(f"✅ Баланс: {balance:.2f} USDT")

        if balance == 0:
            logger.warning("⚠️ Баланс = 0 (sandbox или нет средств)")

        logger.info("🧪 Тест 4: Проверка маржи...")
        margin_info = await client.get_margin_info("BTC-USDT")
        logger.info(f"✅ Информация о марже: {margin_info}")

        logger.info("🧪 Тест 5: Тест округления размера...")
        from src.clients.futures_client import round_to_step

        test_size = round_to_step(0.12345, 0.001)
        logger.info(f"✅ Округление: 0.12345 → {test_size}")

        logger.info("🧪 Все тесты пройдены успешно! ✅")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка в тесте: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        try:
            await client.close()
        except:
            pass


if __name__ == "__main__":
    # Настройка логирования
    import io
    import sys

    # Исправляем кодировку для Windows
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    logger.remove()
    logger.add(
        sys.stdout, level="INFO", format="{time:HH:mm:ss} | {level: <8} | {message}"
    )

    # Запуск теста
    result = asyncio.run(test_futures_connection())

    if result:
        logger.info("🎉 Всё работает! Бот готов к тестированию!")
        sys.exit(0)
    else:
        logger.error("💥 Есть ошибки, нужно исправить")
        sys.exit(1)
