"""
Настройка единого полного логирования.

Конфигурация:
- Один файл с ВСЕМИ уровнями (DEBUG, INFO, WARNING, ERROR)
- Структурированный формат
- Ротация по 10 MB
- Хранение 7 дней
- Сжатие старых логов
- Асинхронная запись
"""

import sys
from datetime import datetime

from loguru import logger


def setup_logging(log_level: str = "DEBUG"):
    """
    Настройка единого полного лога.

    Создает:
    1. Консольный вывод (INFO+) с цветами
    2. Файловый лог (DEBUG+) полный со всей информацией

    Args:
        log_level: Уровень логирования для файла (DEBUG по умолчанию)
    """

    # Удаляем дефолтный handler
    logger.remove()

    # 1. КОНСОЛЬ (INFO+) - для мониторинга в реальном времени
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # 2. ФАЙЛ (DEBUG+) - ПОЛНЫЙ ЛОГ со всей информацией
    logger.add(
        "logs/trading_bot_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} | "
            "{message}"
        ),
        rotation="10 MB",  # Ротация при 10 MB
        retention="7 days",  # Хранить 7 дней
        compression="zip",  # Сжимать старые
        enqueue=True,  # Асинхронная запись (не блокирует)
        encoding="utf-8",
    )

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("📝 LOGGING CONFIGURED")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info(f"   Console: INFO+ (colored)")
    logger.info(f"   File: {log_level}+ (full log)")
    logger.info(f"   Rotation: 10 MB")
    logger.info(f"   Retention: 7 days")
    logger.info(f"   Compression: ZIP")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def setup_structured_logging():
    """
    Альтернативная настройка - раздельные файлы по уровням.

    (Пока не используем - оставляем для будущего)

    Создаст:
    - logs/debug_YYYY-MM-DD.log (DEBUG+)
    - logs/info_YYYY-MM-DD.log (INFO+)
    - logs/errors_YYYY-MM-DD.log (ERROR+)
    """
    logger.remove()

    # Консоль (INFO+)
    logger.add(sys.stderr, level="INFO", colorize=True)

    # DEBUG файл
    logger.add(
        "logs/debug_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="10 MB",
        retention="3 days",
        compression="zip",
    )

    # INFO файл
    logger.add(
        "logs/info_{time:YYYY-MM-DD}.log",
        level="INFO",
        rotation="5 MB",
        retention="7 days",
        compression="zip",
    )

    # ERROR файл
    logger.add(
        "logs/errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        rotation="5 MB",
        retention="30 days",  # Ошибки храним дольше
        compression="zip",
    )

    logger.info("📝 Structured logging configured (debug/info/errors)")
