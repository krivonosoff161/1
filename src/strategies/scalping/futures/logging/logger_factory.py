"""
LoggerFactory - Фабрика логгеров.

Создает и настраивает логгеры для системы.
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# 🔴 BUG #37 FIX: Import correlation ID context
from .correlation_id_context import CorrelationIdContext


class LoggerFactory:
    """
    Фабрика логгеров.

    Создает и настраивает логгеры для разных компонентов системы.
    """

    @staticmethod
    def _add_correlation_id(record):
        """
        🔴 BUG #37 FIX: Add correlation ID to all log records
        """
        correlation_id = CorrelationIdContext.get_correlation_id()
        if correlation_id:
            record["extra"]["correlation_id"] = correlation_id
        else:
            record["extra"]["correlation_id"] = "N/A"

    @staticmethod
    def setup_futures_logging(
        log_dir: str = "logs/futures",
        log_level: str = "DEBUG",
    ) -> None:
        """
        Настройка логирования для Futures бота.

        Создает:
        1. Основной лог (DEBUG+)
        2. INFO лог (INFO+)
        3. ERROR лог (ERROR+)

        Args:
            log_dir: Директория для логов
            log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        """
        # Создаем директорию для логов
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Удаляем дефолтный handler
        logger.remove()

        # 🔴 BUG #37 FIX: Patch logger to add correlation ID (global patcher)
        logger.configure(patcher=LoggerFactory._add_correlation_id)

        # 1. КОНСОЛЬ (INFO+) - для мониторинга в реальном времени
        logger.add(
            sys.stdout,
            level="INFO",
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
                "[<yellow>{extra[correlation_id]}</yellow>] | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

        # 2. Основной лог (DEBUG+)
        logger.add(
            str(log_path / "futures_main_{time:YYYY-MM-DD}.log"),
            level=log_level,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "[{extra[correlation_id]}] | "  # 🔴 BUG #37 FIX: Add correlation ID
                "{name}:{function}:{line} | "
                "{message}"
            ),
            rotation="5 MB",  # ✅ Ротация при достижении 5 MB - создает новый файл (futures_main_YYYY-MM-DD_1.log, _2.log и т.д.)
            retention="7 days",
            # ✅ УБРАНО compression="zip" - при ротации создаются обычные файлы, архивация в ZIP происходит один раз в сутки в 00:05 UTC
            enqueue=True,  # Асинхронная запись
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )

        # 3. INFO лог (INFO+)
        logger.add(
            str(log_path / "info_{time:YYYY-MM-DD}.log"),
            level="INFO",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "[{extra[correlation_id]}] | "  # 🔴 BUG #37 FIX: Add correlation ID
                "{name}:{function} | "
                "{message}"
            ),
            rotation="5 MB",
            retention="14 days",
            encoding="utf-8",
        )

        # 4. ERROR лог (ERROR+)
        logger.add(
            str(log_path / "errors_{time:YYYY-MM-DD}.log"),
            level="ERROR",
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
                "{level: <8} | "
                "[{extra[correlation_id]}] | "  # 🔴 BUG #37 FIX: Add correlation ID
                "{name}:{function}:{line} | "
                "{message}\n{exception}"
            ),
            rotation="5 MB",
            retention="30 days",
            encoding="utf-8",
            backtrace=True,
            diagnose=True,
        )

        logger.info("✅ Логирование настроено для Futures бота")

    @staticmethod
    def create_logger(
        name: str,
        log_level: str = "DEBUG",
        log_file: Optional[str] = None,
    ):
        """
        Создать кастомный логгер.

        Args:
            name: Имя логгера
            log_level: Уровень логирования
            log_file: Путь к файлу лога (опционально)

        Returns:
            Настроенный логгер
        """
        # Создаем новый логгер с именем
        custom_logger = logger.bind(name=name)

        # Если указан файл, добавляем handler
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            custom_logger.add(
                str(log_path),
                level=log_level,
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name} | {message}",
                rotation="5 MB",
                retention="7 days",
                encoding="utf-8",
            )

        return custom_logger
