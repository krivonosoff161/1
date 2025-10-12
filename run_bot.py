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
    args = parser.parse_args()

    # Информационное сообщение о режиме работы
    print("=" * 70)
    print("OKX Trading Bot - Starting...")
    print("=" * 70)
    print("MODE: DEMO (OKX Sandbox)")
    print(f"Config: {args.config}")
    print("=" * 70)
    print()

    try:
        # Загружаем конфигурацию из YAML файла
        config = load_config(args.config)

        # Инициализируем бота с конфигурациями
        bot = BotRunner(
            config=config.get_okx_config(),
            risk_config=config.risk,
            strategy_config=config.scalping,
        )

        # Запускаем бота (asyncio.run создаёт и управляет event loop)
        asyncio.run(bot.run())

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


if __name__ == "__main__":
    main()
