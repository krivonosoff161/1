#!/usr/bin/env python3
"""
Запуск Futures бота на 2 минуты для тестирования.
"""

import asyncio
import signal
import sys
from pathlib import Path

# Добавляем корневую папку в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import BotConfig
# Импортируем Futures Orchestrator
from src.strategies.scalping.futures.orchestrator import \
    FuturesScalpingOrchestrator

# Флаг для остановки
should_stop = False


def signal_handler(sig, frame):
    """Обработчик Ctrl+C"""
    global should_stop
    logger.info("🛑 Получен сигнал остановки...")
    should_stop = True


async def run_futures_bot_for_2_minutes():
    """Запуск Futures бота на 2 минуты"""
    global should_stop

    orchestrator = None

    try:
        logger.info("🚀 Запуск Futures бота (тест на 2 минуты)...")

        # Загружаем конфигурацию
        config = BotConfig.load_from_file("config/config_futures.yaml")
        logger.info("✅ Конфигурация загружена")

        # Создаем оркестратор
        orchestrator = FuturesScalpingOrchestrator(config)
        logger.info("✅ Orchestrator создан")

        # Запускаем бота в фоне
        logger.info("🔄 Начинаем торговый цикл...")
        bot_task = asyncio.create_task(orchestrator.start())

        # Ждем 2 минуты или сигнала остановки
        wait_time = 120  # 2 минуты
        step = 1  # проверка каждую секунду

        for _ in range(wait_time):
            if should_stop:
                logger.info("🛑 Получен сигнал остановки (Ctrl+C)...")
                break
            await asyncio.sleep(step)

        # Останавливаем бота
        if orchestrator:
            logger.info("🛑 Остановка бота...")
            await orchestrator.stop()

        # Ждем завершения задачи
        await asyncio.wait_for(bot_task, timeout=5.0)

    except KeyboardInterrupt:
        logger.info("🛑 Получен KeyboardInterrupt...")
        if orchestrator:
            await orchestrator.stop()
    except asyncio.TimeoutError:
        logger.info("⏱️  Таймаут ожидания завершения бота")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        import traceback

        traceback.print_exc()
        if orchestrator:
            try:
                await orchestrator.stop()
            except:
                pass
    finally:
        logger.info("✅ Futures бот остановлен")


if __name__ == "__main__":
    # Исправляем кодировку для Windows
    import io

    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

    # Настройка обработчика сигналов
    signal.signal(signal.SIGINT, signal_handler)

    # Настройка логирования
    logger.remove()
    logger.add(
        sys.stdout, level="INFO", format="{time:HH:mm:ss} | {level: <8} | {message}"
    )
    logger.add(
        "logs/futures_test.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="1 day",
    )

    # Запуск
    try:
        asyncio.run(run_futures_bot_for_2_minutes())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
