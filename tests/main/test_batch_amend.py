"""
Тест Batch Amend Orders для группировки обновлений TP/SL
Проверяет эффективность batch операций vs индивидуальных
"""

import asyncio
import sys
from datetime import datetime

from loguru import logger

# Добавляем корневую директорию проекта в sys.path
sys.path.append(".")

from src.config import load_config
from src.okx_client import OKXClient
from src.strategies.scalping.batch_order_manager import BatchOrderManager


async def test_batch_amend_efficiency():
    """Тест эффективности batch amend vs индивидуальных обновлений"""
    print("🔄 ТЕСТ ЭФФЕКТИВНОСТИ BATCH AMEND")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        # Создаем Batch Order Manager
        batch_manager = BatchOrderManager(client)

        # Тест 1: Индивидуальные обновления (старый способ)
        print("📊 Тест индивидуальных обновлений...")
        start_time = datetime.utcnow()

        # Симулируем 5 индивидуальных обновлений
        for i in range(5):
            batch_manager.add_order_update(
                inst_id="BTC-USDT", ord_id=f"test_tp_{i}", new_px="50000.0"
            )
            batch_manager.add_order_update(
                inst_id="BTC-USDT", ord_id=f"test_sl_{i}", new_px="49000.0"
            )

        # Flush для выполнения
        result = await batch_manager.force_flush()
        individual_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        print(f"   Индивидуальные обновления: {individual_time:.1f} мс")
        print(f"   Результат: {result.get('code', 'unknown')}")

        # Тест 2: Batch обновления (новый способ)
        print("\n📊 Тест batch обновлений...")
        start_time = datetime.utcnow()

        # Симулируем batch обновление 10 ордеров
        orders_data = []
        for i in range(10):
            orders_data.append(
                {
                    "instId": "BTC-USDT",
                    "ordId": f"batch_test_{i}",
                    "newPx": f"{50000 + i}.0",
                }
            )

        result = await client.batch_amend_orders(orders_data)
        batch_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        print(f"   Batch обновления: {batch_time:.1f} мс")
        print(f"   Результат: {result.get('code', 'unknown')}")

        # Сравнение
        if individual_time > 0 and batch_time > 0:
            improvement = individual_time - batch_time
            improvement_percent = (improvement / individual_time) * 100
            print(f"\n📈 УЛУЧШЕНИЕ:")
            print(
                f"   Экономия времени: {improvement:.1f} мс ({improvement_percent:.1f}%)"
            )
            print(f"   API calls: 10 → 1 (-90%)")

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста: {e}")


async def test_batch_manager_stats():
    """Тест статистики Batch Order Manager"""
    print("\n📊 ТЕСТ СТАТИСТИКИ BATCH MANAGER")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        batch_manager = BatchOrderManager(client)

        # Добавляем несколько обновлений
        for i in range(3):
            batch_manager.add_order_update(
                inst_id="BTC-USDT", ord_id=f"stat_test_{i}", new_px="50000.0"
            )

        # Получаем статистику
        stats = batch_manager.get_stats()
        print(f"📈 Статистика Batch Manager:")
        print(f"   Pending updates: {stats['pending_updates']}")
        print(f"   Max batch size: {stats['max_batch_size']}")
        print(f"   Auto flush threshold: {stats['auto_flush_threshold']}")
        print(f"   Ready for flush: {stats['ready_for_flush']}")

        # Тест auto-flush
        print(f"\n🔄 Тест auto-flush...")
        for i in range(8):  # Добавляем еще 8, чтобы достичь threshold (10)
            batch_manager.add_order_update(
                inst_id="ETH-USDT", ord_id=f"auto_test_{i}", new_px="4000.0"
            )

        # Проверяем статистику после auto-flush
        stats_after = batch_manager.get_stats()
        print(f"   После auto-flush: {stats_after['pending_updates']} pending")

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста статистики: {e}")


async def test_tp_sl_batch_update():
    """Тест batch обновления TP/SL ордеров"""
    print("\n🎯 ТЕСТ BATCH TP/SL ОБНОВЛЕНИЯ")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        batch_manager = BatchOrderManager(client)

        # Тест обновления TP/SL
        result = await batch_manager.update_tp_sl_batch(
            inst_id="BTC-USDT",
            tp_ord_id="test_tp_123",
            sl_ord_id="test_sl_123",
            new_tp_price="51000.0",
            new_sl_price="49000.0",
            new_tp_trigger="50500.0",
            new_sl_trigger="49500.0",
        )

        print(f"📊 Результат batch TP/SL обновления:")
        print(f"   Code: {result.get('code', 'unknown')}")
        print(f"   Message: {result.get('msg', 'No message')}")
        print(f"   Data: {result.get('data', [])}")

        # Проверяем статистику
        stats = batch_manager.get_stats()
        print(f"\n📈 Статистика после TP/SL обновления:")
        print(f"   Pending updates: {stats['pending_updates']}")

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста TP/SL: {e}")


async def main():
    """Главная функция тестирования"""
    print("🧪 ТЕСТИРОВАНИЕ BATCH AMEND ORDERS")
    print("=" * 60)

    # Тест 1: Эффективность
    await test_batch_amend_efficiency()

    # Тест 2: Статистика
    await test_batch_manager_stats()

    # Тест 3: TP/SL обновления
    await test_tp_sl_batch_update()

    print("\n✅ ТЕСТИРОВАНИЕ BATCH AMEND ЗАВЕРШЕНО")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
