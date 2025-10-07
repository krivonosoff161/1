import argparse
import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))
from src.config import load_config
from src.main import BotRunner


def main():
    parser = argparse.ArgumentParser(description="OKX Trading Bot")
    parser.add_argument(
        "--config", "-c", default="config.yaml", help="Path to config file"
    )
    args = parser.parse_args()

    print("Запуск бота в DEMO режиме с реальными ордерами на демо-счёте OKX")

    # Загружаем конфигурацию
    config = load_config(args.config)

    bot = BotRunner(config.get_okx_config(), config.risk, config.scalping)

    try:
        asyncio.run(bot.run())
    except Exception as e:
        print(f"❌ Ошибка при работе бота: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
