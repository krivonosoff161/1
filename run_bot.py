"""
Точка входа для запуска торгового бота OKX.

Этот скрипт является основной точкой входа для запуска торгового бота.
Загружает конфигурацию из YAML файла, инициализирует все компоненты
и запускает бота в режиме демо-торговли или реальной торговли.

Usage:
    python run_bot.py --config config.yaml
    python run_bot.py -c my_config.yaml

Examples:
    # Запуск с конфигурацией по умолчанию
    python run_bot.py

    # Запуск с кастомной конфигурацией
    python run_bot.py --config custom_config.yaml
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import NoReturn

# Добавляем директорию src в путь поиска модулей
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from src.config import load_config  # noqa: E402
from src.main import BotRunner  # noqa: E402


def main() -> NoReturn:
    """
    Главная функция для запуска торгового бота.

    Парсит аргументы командной строки, загружает конфигурацию из YAML файла,
    инициализирует BotRunner с необходимыми параметрами и запускает
    основной торговый цикл.

    Command-line Arguments:
        --config, -c: Путь к файлу конфигурации (default: config.yaml)

    Raises:
        FileNotFoundError: Если файл конфигурации не найден
        ValueError: Если конфигурация содержит некорректные данные
        SystemExit: При критических ошибках с кодом 1

    Returns:
        NoReturn: Функция либо запускает бесконечный цикл, либо завершается
    """
    # Проверка на уже запущенный экземпляр через lock file
    lock_file = Path("data/cache/bot.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    if lock_file.exists():
        print("=" * 70)
        print("ERROR: Bot is already running!")
        print("=" * 70)
        print(f"Lock file found: {lock_file}")
        print("If bot is not running, delete the lock file:")
        print(f"  del {lock_file}")
        print("=" * 70)
        sys.exit(1)

    # Создаём lock file
    try:
        lock_file.write_text(str(os.getpid()))
    except Exception as e:
        print(f"WARNING: Could not create lock file: {e}")

    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(
        description="OKX Trading Bot - Автоматизированный торговый бот",
        epilog="Для получения справки: python run_bot.py --help",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Путь к файлу конфигурации (default: config.yaml)",
    )
    parser.add_argument(
        "--mode",
        choices=["websocket", "rest"],
        default="rest",
        help="Режим работы бота: websocket (real-time) или rest (polling)",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Запуск в тестовом режиме с дополнительным логированием",
    )
    args = parser.parse_args()

    # Информационное сообщение о режиме работы
    print("=" * 70)
    print("OKX Trading Bot - Starting...")
    print("=" * 70)
    print("MODE: DEMO (OKX Sandbox)")
    print(f"Config: {args.config}")
    print(f"Mode: {args.mode.upper()}")
    if args.test_mode:
        print("TEST MODE: ENABLED")
    print("=" * 70)
    print()

    async def run_with_cleanup():
        """Запуск бота с корректным завершением."""
        bot = None
        try:
            # Загружаем конфигурацию из YAML файла
            config = load_config(args.config)

            # Выбираем режим работы
            if args.mode == "websocket":
                print("🔧 Creating WebSocket Orchestrator...")
                from src.strategies.scalping.websocket_orchestrator import WebSocketScalpingOrchestrator
                from src.okx_client import OKXClient
                
                print("🔧 Initializing OKX Client...")
                # Инициализируем WebSocket оркестратор
                okx_client = OKXClient(config.get_okx_config())
                
                print("🔧 Creating WebSocket Orchestrator...")
                bot = WebSocketScalpingOrchestrator(config, okx_client)
                
                # Устанавливаем тестовый режим
                if args.test_mode:
                    bot.test_mode = True
                
                print("🚀 Starting WebSocket Bot...")
                # Запускаем WebSocket бота
                await bot.start()
            else:
                # Стандартный REST режим
                bot = BotRunner(
                    config=config,
                    mode="rest"
                )
                
                # Инициализируем и запускаем
                await bot.initialize()
                await bot.run()

        finally:
            # Всегда закрываем соединения
            if bot is not None:
                await bot.shutdown()

    try:
        # Запускаем бота (asyncio.run создаёт и управляет event loop)
        asyncio.run(run_with_cleanup())

    except KeyboardInterrupt:
        # Корректное завершение при Ctrl+C
        print("\n")
        print("Bot stopped by user (Ctrl+C)")
        sys.exit(0)
    except FileNotFoundError as e:
        print(f"ERROR: Config file not found - {e}")
        sys.exit(1)
    except Exception as e:
        # Логирование критических ошибок
        print(f"CRITICAL ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Удаляем lock file при любом завершении
        lock_file = Path("data/cache/bot.lock")
        if lock_file.exists():
            try:
                lock_file.unlink()
            except Exception as e:  # noqa: B110
                # Игнорируем ошибки удаления lock file при завершении
                print(f"WARNING: Could not remove lock file: {e}")


if __name__ == "__main__":
    main()
