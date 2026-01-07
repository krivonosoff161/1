#!/usr/bin/env python3
"""
🔍 ДИАГНОСТИКА CPU 100%

Определяем что вызывает высокую нагрузку на CPU.
Используем профилирование для выявления узких мест.
"""

import asyncio
import cProfile
import io
import pstats
import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import BotConfig


def profile_indicator_calculation():
    """Профилируем вычисление индикаторов"""
    print("\n" + "=" * 80)
    print("🔍 ПРОФИЛЬ: Вычисление индикаторов (ATR, RSI, MACD, BB)")
    print("=" * 80)

    try:
        from src.indicators.indicator_manager import IndicatorManager
        from src.models import OHLCV

        # Создаем test data (500 свечей как после нашего фикса)
        test_candles = [
            OHLCV(
                timestamp=1000 + i * 60,
                symbol="BTC-USDT",
                open=93000.0 + (i * 10),
                high=93100.0 + (i * 10),
                low=92900.0 + (i * 10),
                close=93050.0 + (i * 10),
                volume=100.0 + i,
                timeframe="1m",
            )
            for i in range(500)
        ]

        indicator_manager = IndicatorManager()

        # Профилируем
        pr = cProfile.Profile()
        pr.enable()

        # Запускаем расчет 100 раз (симулируем 100 циклов)
        for _ in range(100):
            result = indicator_manager.calculate_all(test_candles)

        pr.disable()

        # Выводим результаты
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
        ps.print_stats(10)  # Top 10 функций

        print(s.getvalue())
        print("\n✅ Анализ завершен!")

    except Exception as e:
        print(f"❌ Ошибка при профилировании: {e}")
        import traceback

        traceback.print_exc()


def profile_signal_generation():
    """Профилируем генерацию сигналов"""
    print("\n" + "=" * 80)
    print("🔍 ПРОФИЛЬ: Генерация сигналов (SignalGenerator)")
    print("=" * 80)

    try:
        from src.clients.futures_client import OKXFuturesClient
        from src.models import OHLCV
        from src.strategies.scalping.futures.signal_generator import \
            FuturesSignalGenerator

        config = BotConfig.load_from_file("config/config_futures.yaml")
        client = OKXFuturesClient(config.get_okx_config())

        # Инициализируем (но не запускаем полный orchest)
        signal_gen = FuturesSignalGenerator(
            client=client,
            config=config,
            data_registry=None,  # Пока без реестра
        )

        print("✅ SignalGenerator инициализирован")
        print("⚠️ Полный профиль требует запущенного бота с реальными данными")
        print("   Используйте: python -m cProfile -s cumulative run.py --mode futures")

    except Exception as e:
        print(f"⚠️ Не удалось профилировать: {e}")


def check_logging_level():
    """Проверяем уровень логирования"""
    print("\n" + "=" * 80)
    print("🔍 ПРОВЕРКА: Уровень логирования")
    print("=" * 80)

    try:
        import inspect

        from loguru import logger

        # Проверяем текущий уровень
        for handler in logger._core.handlers:
            print(f"Хендлер: {handler}")
            print(f"  Level: {handler[1]}")

        # Рекомендации
        print("\n💡 РЕКОМЕНДАЦИИ:")
        print("  - Если уровень DEBUG: измените на INFO (меньше логов = меньше CPU)")
        print("  - Проверьте config.yaml на 'log_level'")
        print("  - В production используйте INFO, не DEBUG")

    except Exception as e:
        print(f"⚠️ Ошибка при проверке логирования: {e}")


def check_asyncio_tasks():
    """Проверяем количество asyncio tasks"""
    print("\n" + "=" * 80)
    print("🔍 ПРОВЕРКА: Asyncio tasks")
    print("=" * 80)

    try:
        import asyncio

        async def count_tasks():
            tasks = asyncio.all_tasks()
            print(f"Текущих tasks: {len(tasks)}")
            if len(tasks) > 20:
                print("⚠️ ВНИМАНИЕ: Много tasks!")
                print("   Может быть утечка задач (task leak)")
                print("   Убедитесь что все tasks отменяются правильно")
            for task in list(tasks)[:5]:
                print(f"  - {task}")

        asyncio.run(count_tasks())

    except Exception as e:
        print(f"⚠️ Ошибка: {e}")


def main():
    """Главная функция диагностики"""
    print("\n" + "█" * 80)
    print("█ 🔍 ДИАГНОСТИКА CPU 100%")
    print("█" * 80)

    print("\n📝 Что делает эта диагностика:")
    print("  1. Профилирует вычисление индикаторов")
    print("  2. Проверяет уровень логирования")
    print("  3. Проверяет asyncio tasks")
    print("  4. Дает рекомендации для оптимизации")

    # Профилируем индикаторы
    profile_indicator_calculation()

    # Проверяем логирование
    check_logging_level()

    # Проверяем asyncio
    check_asyncio_tasks()

    # Рекомендации
    print("\n" + "=" * 80)
    print("🎯 ИТОГОВЫЕ РЕКОМЕНДАЦИИ ДЛЯ СНИЖЕНИЯ CPU 100%")
    print("=" * 80)

    recommendations = [
        (
            "1. Уровень логирования",
            "Если DEBUG → измените на INFO в config.yaml",
            "50-70% сокращение CPU",
        ),
        (
            "2. Busy waiting в цикле",
            "Убедитесь check_interval > 0 в config (должен быть 1.0)",
            "Проверьте нет ли 'while True' без sleep",
        ),
        (
            "3. Параллельные asyncio tasks",
            "Проверьте нет ли утечки задач (task leaks)",
            "Используйте: asyncio.all_tasks() для проверки",
        ),
        (
            "4. WebSocket callbacks",
            "Если обработка WebSocket сообщений медленная",
            "Используйте: python -m cProfile -s cumulative run.py",
        ),
        (
            "5. Объем логирования",
            "Слишком много DEBUG логов = медленнее",
            "Отключите DEBUG для TradingControlCenter в production",
        ),
    ]

    for title, action, impact in recommendations:
        print(f"\n{title}")
        print(f"  ➜ {action}")
        print(f"  📊 Эффект: {impact}")

    print("\n" + "=" * 80)
    print("✅ Диагностика завершена")
    print("=" * 80)


if __name__ == "__main__":
    main()
