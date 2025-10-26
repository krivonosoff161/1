#!/usr/bin/env python3
"""
Тест для диагностики Batch Amend "Invalid Sign" ошибки
"""

import asyncio
import os
import sys
from pathlib import Path

# Устанавливаем UTF-8 для консоли
if sys.platform == "win32":
    os.system("chcp 65001 >nul")

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.okx_client import OKXClient


async def test_batch_amend():
    """Тест Batch Amend функциональности"""

    print("=" * 60)
    print("🔧 ТЕСТ: BATCH AMEND")
    print("=" * 60)

    # Загружаем конфигурацию
    config = load_config()
    api_config = list(config.api.values())[0]
    client = OKXClient(api_config)
    await client.connect()

    try:
        # Получаем текущую цену ETH
        eth_price = await client.get_current_price("ETH-USDT")
        print(f"\n📊 Текущая цена ETH: ${eth_price:.2f}")

        # Размещаем OCO ордер для тестирования batch amend
        print(f"\n🛒 Шаг 1: Размещаем OCO ордер для тестирования...")

        tp_price = eth_price * 1.005  # +0.5%
        sl_price = eth_price * 0.9965  # -0.35%

        oco_result = await client._make_request(
            "POST",
            "/trade/order-algo",
            data={
                "instId": "ETH-USDT",
                "tdMode": "cash",
                "side": "sell",
                "ordType": "oco",
                "sz": "0.005",
                "tpTriggerPx": str(tp_price),
                "slTriggerPx": str(sl_price),
                "tpOrdPx": "-1",
                "slOrdPx": "-1",
                "autoBorrow": "false",
            },
        )

        oco_id = oco_result.get("data", [{}])[0].get("algoId")
        print(f"✅ OCO размещен: {oco_id}")
        print(f"   TP: ${tp_price:.2f}")
        print(f"   SL: ${sl_price:.2f}")

        # Ждем 2 секунды для синхронизации
        print(f"\n⏳ Ждем 2 секунды для синхронизации...")
        await asyncio.sleep(2)

        # Шаг 2: Тестируем Batch Amend
        print(f"\n🔧 Шаг 2: ТЕСТИРУЕМ BATCH AMEND...")

        # Новые цены для TP/SL
        new_tp_price = eth_price * 1.006  # +0.6%
        new_sl_price = eth_price * 0.996  # -0.4%

        print(f"   Обновляем TP: ${tp_price:.2f} → ${new_tp_price:.2f}")
        print(f"   Обновляем SL: ${sl_price:.2f} → ${new_sl_price:.2f}")

        # Подготавливаем данные для batch amend
        orders_data = [
            {
                "instId": "ETH-USDT",
                "algoId": oco_id,
                "newTpTriggerPx": str(new_tp_price),
                "newSlTriggerPx": str(new_sl_price),
            }
        ]

        try:
            # Вызываем batch amend
            result = await client.batch_amend_orders(orders_data)
            print(f"✅ Batch amend успешен!")
            print(f"   Результат: {result}")

        except Exception as e:
            print(f"❌ Batch amend failed: {e}")

            # Детальная диагностика
            print(f"\n🔍 ДИАГНОСТИКА:")
            print(f"   OCO ID: {oco_id}")
            print(f"   Новые цены: TP={new_tp_price:.2f}, SL={new_sl_price:.2f}")
            print(f"   Данные: {orders_data}")

            # Проверяем, существует ли OCO
            print(f"\n📊 Проверяем существование OCO...")
            try:
                # Пробуем получить OCO через другой метод
                algo_orders = await client.get_algo_orders(symbol="ETH-USDT")
                print(f"   Найдено алгоритмических ордеров: {len(algo_orders)}")

                if algo_orders:
                    for order in algo_orders:
                        print(f"   - {order.get('algoId')}: {order.get('state')}")
                        if order.get("algoId") == oco_id:
                            print(f"   ✅ НАШ OCO НАЙДЕН!")
                else:
                    print(f"   ❌ OCO не найден - возможно уже исполнился")

            except Exception as e2:
                print(f"   ❌ Ошибка проверки OCO: {e2}")

        # Очистка
        print(f"\n🧹 Очистка...")
        if oco_id:
            try:
                await client.cancel_algo_order(oco_id, "ETH-USDT")
                print(f"   ✅ OCO отменен")
            except Exception as e:
                print(f"   ❌ Ошибка отмены OCO: {e}")

        print(f"\n✅ Тест завершен")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_batch_amend())
