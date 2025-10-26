#!/usr/bin/env python3
"""
CLI Launcher для торгового бота.
Позволяет выбрать режим торговли: Spot или Futures.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Добавляем корневую папку проекта в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger


def print_banner():
    """Вывод баннера приложения"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    🚀 TRADING BOT LAUNCHER 🚀                ║
║                                                              ║
║  Выберите режим торговли:                                    ║
║  • Spot Trading    - Торговля спотом (без левериджа)        ║
║  • Futures Trading - Торговля фьючерсами (с левериджем)     ║
║                                                              ║
║  ⚠️  ВНИМАНИЕ: Futures торговля связана с высокими рисками! ║
║     Используйте только те средства, потерю которых          ║
║     можете себе позволить!                                   ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_mode_info(mode: str):
    """Вывод информации о выбранном режиме"""
    if mode.lower() == "spot":
        info = """
╔══════════════════════════════════════════════════════════════╗
║                    📈 SPOT TRADING MODE 📈                  ║
║                                                              ║
║  Особенности Spot торговли:                                  ║
║  • Торговля без левериджа (1:1)                             ║
║  • Более низкие риски                                       ║
║  • Подходит для начинающих                                  ║
║  • Меньшая волатильность PnL                                ║
║                                                              ║
║  Конфигурация: config/config_spot.yaml                      ║
║  Логи: logs/spot/                                           ║
╚══════════════════════════════════════════════════════════════╝
        """
    elif mode.lower() == "futures":
        info = """
╔══════════════════════════════════════════════════════════════╗
║                   ⚡ FUTURES TRADING MODE ⚡                 ║
║                                                              ║
║  Особенности Futures торговли:                               ║
║  • Торговля с левериджем (3x по умолчанию)                  ║
║  • Высокие риски и потенциальная доходность                 ║
║  • Требует опыт в торговле                                  ║
║  • Защита от ликвидации                                     ║
║                                                              ║
║  ⚠️  КРИТИЧЕСКИ ВАЖНО:                                      ║
║     • Настройте правильные пороги маржи                     ║
║     • Используйте sandbox для тестирования                   ║
║     • Начните с минимальных сумм                            ║
║                                                              ║
║  Конфигурация: config/config_futures.yaml                   ║
║  Логи: logs/futures/                                        ║
╚══════════════════════════════════════════════════════════════╝
        """
    else:
        info = f"Неизвестный режим: {mode}"

    print(info)


async def run_spot_bot():
    """Запуск Spot бота"""
    try:
        logger.info("🚀 Запуск Spot торгового бота...")

        # Импорт и запуск Spot бота
        from src.main_spot import main

        await main()

    except Exception as e:
        logger.error(f"❌ Ошибка запуска Spot бота: {e}")
        raise


async def run_futures_bot():
    """Запуск Futures бота"""
    try:
        logger.info("🚀 Запуск Futures торгового бота...")

        # Импорт и запуск Futures бота
        from src.main_futures import main

        await main()

    except Exception as e:
        logger.error(f"❌ Ошибка запуска Futures бота: {e}")
        raise


def check_config_files():
    """Проверка наличия конфигурационных файлов"""
    spot_config = project_root / "config" / "config_spot.yaml"
    futures_config = project_root / "config" / "config_futures.yaml"

    missing_files = []

    if not spot_config.exists():
        missing_files.append("config/config_spot.yaml")

    if not futures_config.exists():
        missing_files.append("config/config_futures.yaml")

    if missing_files:
        logger.error("❌ Отсутствуют конфигурационные файлы:")
        for file in missing_files:
            logger.error(f"   • {file}")
        logger.info("💡 Создайте недостающие файлы конфигурации")
        return False

    return True


def check_api_keys(mode: str):
    """Проверка настроек API ключей"""
    config_file = f"config/config_{mode}.yaml"
    config_path = project_root / config_file

    if not config_path.exists():
        logger.error(f"❌ Конфигурационный файл не найден: {config_file}")
        return False

    # Простая проверка на наличие placeholder значений
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
            if "your_api_key_here" in content:
                logger.error(f"❌ API ключи не настроены в {config_file}")
                logger.info(
                    "💡 Отредактируйте конфигурационный файл и укажите ваши API ключи"
                )
                return False
    except Exception as e:
        logger.error(f"❌ Ошибка чтения конфигурации: {e}")
        return False

    return True


def interactive_mode():
    """Интерактивный режим выбора"""
    print_banner()

    while True:
        print("\nВыберите режим торговли:")
        print("1. Spot Trading (Спот торговля)")
        print("2. Futures Trading (Фьючерсная торговля)")
        print("3. Выход")

        choice = input("\nВведите номер (1-3): ").strip()

        if choice == "1":
            print_mode_info("spot")
            confirm = input("\nПродолжить с Spot торговлей? (y/n): ").strip().lower()
            if confirm in ["y", "yes", "да", "д"]:
                return "spot"
            else:
                continue

        elif choice == "2":
            print_mode_info("futures")
            print("\n⚠️  ВНИМАНИЕ: Futures торговля связана с высокими рисками!")
            confirm = (
                input("Вы уверены, что хотите продолжить? (y/n): ").strip().lower()
            )
            if confirm in ["y", "yes", "да", "д"]:
                return "futures"
            else:
                continue

        elif choice == "3":
            print("👋 До свидания!")
            return None

        else:
            print("❌ Неверный выбор. Попробуйте снова.")


def main():
    """Основная функция CLI launcher"""
    parser = argparse.ArgumentParser(
        description="Trading Bot Launcher - Запуск торгового бота",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python run.py --mode spot          # Запуск Spot бота
  python run.py --mode futures       # Запуск Futures бота
  python run.py --interactive        # Интерактивный режим
  python run.py --check-config       # Проверка конфигурации
        """,
    )

    parser.add_argument(
        "--mode",
        "-m",
        choices=["spot", "futures"],
        help="Режим торговли (spot или futures)",
    )

    parser.add_argument(
        "--interactive", "-i", action="store_true", help="Интерактивный режим выбора"
    )

    parser.add_argument(
        "--check-config",
        "-c",
        action="store_true",
        help="Проверка конфигурационных файлов",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")

    args = parser.parse_args()

    # Настройка логирования
    log_level = "DEBUG" if args.verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )

    # Проверка конфигурации
    if args.check_config:
        logger.info("🔍 Проверка конфигурационных файлов...")
        if check_config_files():
            logger.info("✅ Все конфигурационные файлы найдены")
        else:
            logger.error("❌ Проблемы с конфигурационными файлами")
            sys.exit(1)
        return

    # Определение режима
    mode = None

    if args.interactive:
        mode = interactive_mode()
    elif args.mode:
        mode = args.mode
    else:
        # Если не указан режим, запускаем интерактивный
        mode = interactive_mode()

    if mode is None:
        logger.info("👋 Запуск отменен")
        return

    # Проверка конфигурации для выбранного режима
    if not check_config_files():
        logger.error("❌ Проблемы с конфигурационными файлами")
        sys.exit(1)

    if not check_api_keys(mode):
        logger.error("❌ Проблемы с API ключами")
        sys.exit(1)

    # Запуск соответствующего бота
    try:
        if mode == "spot":
            logger.info("📈 Запуск Spot торгового бота...")
            asyncio.run(run_spot_bot())
        elif mode == "futures":
            logger.info("⚡ Запуск Futures торгового бота...")
            asyncio.run(run_futures_bot())

    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки...")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        sys.exit(1)
    finally:
        logger.info("✅ Торговый бот остановлен")


if __name__ == "__main__":
    main()
