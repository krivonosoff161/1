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
project_root = Path(
    __file__
).parent.parent  # Переходим на уровень выше (из src в корень)
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import BotConfig
from src.strategies.scalping.futures.orchestrator import \
    FuturesScalpingOrchestrator


async def main():
    """Основная функция запуска Futures бота"""
    orchestrator = None
    try:
        logger.info("🚀 Запуск Futures торгового бота...")

        # Загружаем конфигурацию
        config_path = project_root / "config" / "config_futures.yaml"
        if not config_path.exists():
            # Пробуем альтернативный путь (если запускаем из корня)
            alt_path = Path("config/config_futures.yaml")
            if alt_path.exists():
                config_path = alt_path
            else:
                logger.error(f"❌ Конфигурационный файл не найден: {config_path}")
                logger.error(f"❌ Альтернативный путь также не найден: {alt_path}")
                logger.info(
                    "💡 Создайте файл config/config_futures.yaml с вашими настройками"
                )
                return

        # Создаем конфигурацию
        config = BotConfig.load_from_file(str(config_path))

        # Проверяем конфигурацию
        if (
            not config.get_okx_config().api_key
            or config.get_okx_config().api_key == "your_api_key_here"
        ):
            logger.error("❌ API ключ не настроен в конфигурации")
            logger.info(
                "💡 Отредактируйте config/config_futures.yaml и укажите ваши API ключи"
            )
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
        logger.info("🛑 Получен сигнал остановки (Ctrl+C)...")
        # Останавливаем оркестратор при KeyboardInterrupt
        if orchestrator:
            try:
                await orchestrator.stop()
            except (asyncio.CancelledError, Exception) as stop_error:
                logger.debug(
                    f"⚠️ Ошибка при остановке (ожидаемо при прерывании): {stop_error}"
                )
    except asyncio.CancelledError:
        logger.info("🛑 Задача отменена")
        if orchestrator:
            try:
                await orchestrator.stop()
            except Exception as stop_error:
                logger.debug(f"⚠️ Ошибка при остановке: {stop_error}")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        # Останавливаем оркестратор при ошибке
        if orchestrator:
            try:
                await orchestrator.stop()
            except Exception as stop_error:
                logger.debug(f"⚠️ Ошибка при остановке: {stop_error}")
        raise
    finally:
        logger.info("✅ Futures бот остановлен")


if __name__ == "__main__":
    # Настройка логирования
    logger.remove()

    # ✅ КОНСОЛЬ: только INFO и выше (чтобы не засорять экран)
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    # ✅ ФАЙЛ: ВСЕ логи (DEBUG+) с ротацией по размеру (5 MB)
    # Создаем директорию для логов, если её нет
    log_dir = Path("logs/futures")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(log_dir / "futures_main_{time:YYYY-MM-DD}.log"),  # Имя файла с датой
        level="DEBUG",  # ✅ ВСЕ уровни логирования
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="5 MB",  # ✅ Ротация при достижении 5 MB - создает новый файл (futures_main_YYYY-MM-DD_1.log, _2.log и т.д.)
        retention="7 days",  # ✅ Храним 7 дней
        # ✅ УБРАНО compression="zip" - при ротации создаются обычные файлы, архивация в ZIP происходит один раз в сутки в 00:05 UTC
        encoding="utf-8",
        backtrace=True,  # Полный backtrace при ошибках
        diagnose=True,  # Дополнительная диагностика
    )

    # Запуск
    asyncio.run(main())
