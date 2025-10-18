"""
Основной модуль для запуска торгового бота.

Этот модуль содержит класс BotRunner, который координирует работу
всех компонентов торгового бота: клиента биржи, стратегий и риск-менеджмента.
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config import APIConfig, RiskConfig, ScalpingConfig
from src.okx_client import OKXClient
# 🆕 НОВАЯ МОДУЛЬНАЯ АРХИТЕКТУРА
from src.strategies.scalping import ScalpingOrchestrator
# ✅ НОВОЕ: Единый полный лог с ротацией
from src.utils.logging_setup import setup_logging

# Для совместимости (если нужно переключиться обратно)
# from src.strategies.scalping_old import ScalpingStrategy


# Создаем папку для логов если её нет
Path("logs").mkdir(exist_ok=True)

# Настраиваем логирование
setup_logging(log_level="DEBUG")  # Полный лог для отладки


class BotRunner:
    """
    Основной класс для управления торговым ботом.

    Координирует работу клиента биржи и торговых стратегий,
    обеспечивает правильную инициализацию и запуск всех компонентов.

    Attributes:
        config: Конфигурация API биржи
        client: Клиент для взаимодействия с биржей OKX
        strategy: Активная торговая стратегия
    """

    def __init__(
        self,
        config: APIConfig,
        risk_config: Optional[RiskConfig] = None,
        strategy_config: Optional[ScalpingConfig] = None,
    ) -> None:
        """
        Инициализация торгового бота.

        Args:
            config: Конфигурация API для подключения к бирже
            risk_config: Конфигурация управления рисками (опционально)
            strategy_config: Конфигурация торговой стратегии (опционально)
        """
        self.config = config
        self.client = OKXClient(config)
        # 🆕 НОВАЯ АРХИТЕКТУРА: ScalpingOrchestrator
        self.strategy = ScalpingOrchestrator(self.client, strategy_config, risk_config)

    async def initialize(self) -> None:
        """
        Инициализация всех компонентов бота.

        Подключается к бирже, инициализирует стратегию и
        подготавливает все необходимые ресурсы для торговли.

        Raises:
            ConnectionError: Если не удалось подключиться к бирже
            Exception: При ошибках инициализации компонентов
        """
        logger.info("Initializing bot...")
        await self.client.connect()
        # await self.strategy.initialize()
        # Метод может отсутствовать, закомментировано
        logger.info("Bot initialized.")

    async def run(self) -> None:
        """
        Запуск основного цикла торгового бота.

        Запускает выполнение торговой стратегии и продолжает работу
        до тех пор, пока не будет получена команда остановки.

        Raises:
            Exception: При критических ошибках во время торговли
        """
        logger.info("Running bot...")
        await self.strategy.run()

    async def shutdown(self) -> None:
        """
        Корректное завершение работы бота.

        Закрывает все открытые соединения и освобождает ресурсы.
        Должен вызываться при остановке бота.
        """
        logger.info("Shutting down bot...")
        await self.client.disconnect()
        logger.info("Bot shutdown complete.")


def main() -> None:
    """
    Точка входа для запуска торгового бота из командной строки.

    Парсит аргументы командной строки, загружает конфигурацию и
    запускает бота в режиме демо-торговли на бирже OKX.

    Command-line Args:
        --config: Путь к файлу конфигурации (default: config.yaml)

    Raises:
        SystemExit: При критических ошибках с кодом 1
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="OKX Trading Bot CLI")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file",
    )
    parser.parse_args()  # Парсим для валидации, но пока не используем

    # Загружаем конфигурацию (метод load нужно будет реализовать)
    config = APIConfig()
    # config.load(args.config)  # Закомментировано до реализации
    # Выставляем демо-режим для тестирования на демо-счёте OKX
    config.sandbox = True

    runner = BotRunner(config)

    # Запускаем асинхронный event loop
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(runner.initialize())
        loop.run_until_complete(runner.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Critical error running bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
