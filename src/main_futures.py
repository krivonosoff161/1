#!/usr/bin/env python3
"""
Точка входа для Futures торговли.
Запускает Futures версию торгового бота.
"""

import asyncio
import os
import sys
from pathlib import Path

# Добавляем корневую папку проекта в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import BotConfig
from src.strategies.scalping.futures.orchestrator import \
    FuturesScalpingOrchestrator


async def main():
    """Основная функция запуска Futures бота"""
    try:
        logger.info("🚀 Запуск Futures торгового бота...")

        # Загружаем конфигурацию
        config_path = project_root / "config" / "config_futures.yaml"
        if not config_path.exists():
            logger.error(f"❌ Конфигурационный файл не найден: {config_path}")
            logger.info(
                "💡 Создайте файл config/config_futures.yaml с вашими настройками"
            )
            return

        # Создаем конфигурацию
        config = BotConfig.from_yaml(str(config_path))

        # Проверяем конфигурацию
        if not config.api.key or config.api.key == "your_api_key_here":
            logger.error("❌ API ключ не настроен в конфигурации")
            logger.info(
                "💡 Отредактируйте config/config_futures.yaml и укажите ваши API ключи"
            )
            return

        # Проверяем Futures-специфичные настройки
        if not hasattr(config, "futures") or not config.futures:
            logger.error("❌ Futures конфигурация не найдена")
            logger.info("💡 Убедитесь, что в config_futures.yaml есть секция 'futures'")
            return

        # Предупреждение о рисках Futures торговли
        logger.warning("⚠️ ВНИМАНИЕ: Futures торговля связана с высокими рисками!")
        logger.warning(
            "⚠️ Используйте только те средства, потерю которых можете себе позволить!"
        )
        logger.warning("⚠️ Рекомендуется начать с sandbox режима для тестирования!")

        # Создаем оркестратор
        orchestrator = FuturesScalpingOrchestrator(config)

        # Запускаем бота
        await orchestrator.start()

    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        raise
    finally:
        logger.info("✅ Futures бот остановлен")


if __name__ == "__main__":
    # Настройка логирования
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # Добавляем файловое логирование
    logger.add(
        "logs/futures/futures_main.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )

    # Запуск
    asyncio.run(main())
