"""
Главный скрипт для запуска backtesting
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import BotConfig
from tests.backtesting.backtest_engine import BacktestEngine


async def main():
    """Главная функция"""
    import argparse

    parser = argparse.ArgumentParser(description="Тестирование торгового бота")
    parser.add_argument(
        "--test",
        choices=["simple", "params", "optimize", "all"],
        default="simple",
        help="Какой тест запустить",
    )

    args = parser.parse_args()

    try:
        # Загрузить конфиг
        config = BotConfig.load_from_file("config/config_futures.yaml")

        # Создать engine
        engine = BacktestEngine(config, symbol="BTC-USDT")

        # Запустить backtesting
        metrics = await engine.run(
            start_date="2025-12-01", end_date="2026-01-06", timeframe="1m", verbose=True
        )

        print("✅ Backtesting завершен!")

    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
