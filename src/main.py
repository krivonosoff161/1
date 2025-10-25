"""
Основной модуль для запуска торгового бота.

Этот модуль содержит класс BotRunner, который координирует работу
всех компонентов торгового бота: клиента биржи, стратегий и риск-менеджмента.

Поддерживает два режима работы:
- REST API (традиционный polling)
- WebSocket (real-time данные)
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from src.config import BotConfig, load_config
from src.okx_client import OKXClient
# REST API режим
from src.strategies.scalping.orchestrator import ScalpingOrchestrator
# WebSocket режим
from src.strategies.scalping.websocket_orchestrator import \
    WebSocketScalpingOrchestrator
# ✅ НОВОЕ: Единый полный лог с ротацией
from src.utils.logging_setup import setup_logging

# Создаем папку для логов если её нет
Path("logs").mkdir(exist_ok=True)

# Настраиваем логирование
setup_logging(log_level="DEBUG")  # Полный лог для отладки


class BotRunner:
    """
    Основной класс для управления торговым ботом.

    Координирует работу клиента биржи и торговых стратегий,
    обеспечивает правильную инициализацию и запуск всех компонентов.

    Поддерживает два режима работы:
    - REST API (традиционный polling)
    - WebSocket (real-time данные)

    Attributes:
        config: Полная конфигурация бота
        client: Клиент для взаимодействия с биржей OKX
        strategy: Активная торговая стратегия (REST или WebSocket)
        mode: Режим работы ('rest' или 'websocket')
    """

    def __init__(self, config: BotConfig, mode: str = "rest") -> None:
        """
        Инициализация торгового бота.

        Args:
            config: Полная конфигурация бота
            mode: Режим работы ('rest' или 'websocket')
        """
        self.config = config
        self.mode = mode.lower()
        self.client = OKXClient(config.api["okx"])

        # Выбор стратегии в зависимости от режима
        if self.mode == "websocket":
            logger.info("🚀 Initializing WebSocket mode...")
            self.strategy = WebSocketScalpingOrchestrator(config, self.client)
        else:
            logger.info("🔄 Initializing REST API mode...")
            self.strategy = ScalpingOrchestrator(
                self.client, config.scalping, config.risk, config
            )

    async def initialize(self) -> None:
        """
        Инициализация всех компонентов бота.

        Подключается к бирже, инициализирует стратегию и
        подготавливает все необходимые ресурсы для торговли.

        Raises:
            ConnectionError: Если не удалось подключиться к бирже
            Exception: При ошибках инициализации компонентов
        """
        logger.info(f"Initializing bot in {self.mode.upper()} mode...")
        await self.client.connect()

        # Инициализация WebSocket для быстрых входов (только для REST режима)
        if self.mode == "rest" and hasattr(self.strategy, "initialize_websocket"):
            try:
                await self.strategy.initialize_websocket()
                logger.info("✅ WebSocket Order Executor initialized for fast entries")
            except Exception as e:
                logger.warning(f"⚠️ WebSocket initialization failed: {e}")
                logger.info("🔄 Will use REST API for order placement")

        logger.info("Bot initialized.")

    async def run(self) -> None:
        """
        Запуск основного цикла торгового бота.

        Запускает выполнение торговой стратегии и продолжает работу
        до тех пор, пока не будет получена команда остановки.

        Raises:
            Exception: При критических ошибках во время торговли
        """
        logger.info(f"Running bot in {self.mode.upper()} mode...")

        if self.mode == "websocket":
            # WebSocket режим - асинхронный запуск
            await self.strategy.start()
        else:
            # REST режим - обычный запуск
            await self.strategy.run()

    async def shutdown(self) -> None:
        """
        Корректное завершение работы бота.

        Закрывает все открытые соединения и освобождает ресурсы.
        Должен вызываться при остановке бота.
        """
        logger.info("Shutting down bot...")

        if self.mode == "websocket":
            # WebSocket режим - остановка WebSocket соединения
            await self.strategy.stop()
        else:
            # REST режим - очистка WebSocket Order Executor
            if hasattr(self.strategy, "cleanup_websocket"):
                await self.strategy.cleanup_websocket()

        await self.client.disconnect()
        logger.info("Bot shutdown complete.")


def main() -> None:
    """
    Точка входа для запуска торгового бота из командной строки.

    Парсит аргументы командной строки, загружает конфигурацию и
    запускает бота в выбранном режиме (REST или WebSocket).

    Command-line Args:
        --config: Путь к файлу конфигурации (default: config.yaml)
        --mode: Режим работы ('rest' или 'websocket', default: 'rest')

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
    parser.add_argument(
        "--mode",
        choices=["rest", "websocket"],
        default="rest",
        help="Trading mode: 'rest' for REST API or 'websocket' for real-time data",
    )

    args = parser.parse_args()

    try:
        # Загружаем конфигурацию
        config = load_config(args.config)
        logger.info(f"Configuration loaded from {args.config}")

        # Создаем runner с выбранным режимом
        runner = BotRunner(config, mode=args.mode)

        # Запускаем асинхронный event loop
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(runner.initialize())
            loop.run_until_complete(runner.run())
        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C)")
            loop.run_until_complete(runner.shutdown())
            sys.exit(0)
        except Exception as e:
            logger.error(f"Critical error running bot: {e}")
            loop.run_until_complete(runner.shutdown())
            sys.exit(1)

    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
