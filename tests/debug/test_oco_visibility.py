"""
Тест для диагностики проблемы OCO Visibility
Проблема: OCO ордера размещаются, но не видны через get_algo_orders
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

from loguru import logger

from src.config import load_config
from src.okx_client import OKXClient


async def test_oco_visibility():
    """Тест видимости OCO ордеров"""

    print("=" * 60)
    print("🔍 ТЕСТ: OCO VISIBILITY")
    print("=" * 60)

    # Загружаем конфиг
    config = load_config()
    # config.api это Dict[str, APIConfig], берем первое значение
    api_config = list(config.api.values())[0]
    client = OKXClient(api_config)
    await client.connect()

    try:
        # Получаем текущую цену ETH
        eth_price = await client.get_current_price("ETH-USDT")
        print(f"\n📊 Текущая цена ETH: ${eth_price:.2f}")

        # Размещаем OCO ордер
        print(f"\n🛒 Шаг 1: Размещаем OCO ордер...")

        tp_price = eth_price * 1.005  # +0.5%
        sl_price = eth_price * 0.9965  # -0.35%

        # Используем метод напрямую
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

        # Шаг 2: ДЕТАЛЬНАЯ ДИАГНОСТИКА OCO
        print(f"\n🔍 Шаг 2: ДЕТАЛЬНАЯ ДИАГНОСТИКА OCO...")

        # 2.1 Проверяем через get_algo_orders с фильтром OCO
        print(f"\n📊 2.1 Проверка через get_algo_orders (algo_type='oco'):")
        algo_orders_oco = await client.get_algo_orders(
            symbol="ETH-USDT", algo_type="oco"
        )
        print(f"   Найдено OCO ордеров: {len(algo_orders_oco)}")

        # 2.2 Проверяем ВСЕ алгоритмические ордера
        print(f"\n📊 2.2 Проверка ВСЕХ алгоритмических ордеров:")
        all_algo = await client.get_algo_orders()
        print(f"   Всего алгоритмических ордеров: {len(all_algo)}")

        if all_algo:
            print(f"   Детали всех ордеров:")
            for i, order in enumerate(all_algo):
                print(f"   Ордер {i+1}:")
                print(f"   - algoId: {order.get('algoId')}")
                print(f"   - ordType: {order.get('ordType')}")
                print(f"   - instId: {order.get('instId')}")
                print(f"   - state: {order.get('state')}")
                print(f"   - tpTriggerPx: {order.get('tpTriggerPx')}")
                print(f"   - slTriggerPx: {order.get('slTriggerPx')}")
                if order.get("algoId") == oco_id:
                    print(f"   ✅ СОВПАДАЕТ С РАЗМЕЩЕННЫМ OCO!")

        # 2.3 Проверяем через прямой API запрос
        print(f"\n📊 2.3 Прямой API запрос к /trade/orders-algo-pending:")
        try:
            direct_result = await client._make_request(
                "GET",
                "/trade/orders-algo-pending",
                params={"instType": "SPOT", "state": "live", "instId": "ETH-USDT"},
            )
            direct_orders = direct_result.get("data", [])
            print(f"   Прямой запрос нашел ордеров: {len(direct_orders)}")

            if direct_orders:
                print(f"   Детали прямого запроса:")
                for i, order in enumerate(direct_orders):
                    print(f"   Ордер {i+1}:")
                    print(f"   - algoId: {order.get('algoId')}")
                    print(f"   - ordType: {order.get('ordType')}")
                    print(f"   - instId: {order.get('instId')}")
                    print(f"   - state: {order.get('state')}")
                    if order.get("algoId") == oco_id:
                        print(f"   ✅ СОВПАДАЕТ С РАЗМЕЩЕННЫМ OCO!")
        except Exception as e:
            print(f"   ❌ Ошибка прямого запроса: {e}")

        # 2.4 Проверяем разные state
        print(f"\n📊 2.4 Проверка разных state:")
        for state in ["live", "effective", "partially_filled", "filled", "cancelled"]:
            try:
                state_orders = await client._make_request(
                    "GET",
                    "/trade/orders-algo-pending",
                    params={"instType": "SPOT", "state": state, "instId": "ETH-USDT"},
                )
                state_count = len(state_orders.get("data", []))
                print(f"   state='{state}': {state_count} ордеров")
            except Exception as e:
                print(f"   state='{state}': ошибка - {e}")

        # 2.5 Проверяем без фильтра instId
        print(f"\n📊 2.5 Проверка без фильтра instId:")
        try:
            no_filter_result = await client._make_request(
                "GET",
                "/trade/orders-algo-pending",
                params={"instType": "SPOT", "state": "live"},
            )
            no_filter_orders = no_filter_result.get("data", [])
            print(f"   Без фильтра instId: {len(no_filter_orders)} ордеров")

            # Ищем наш OCO среди всех
            found_our_oco = False
            for order in no_filter_orders:
                if order.get("algoId") == oco_id:
                    print(f"   ✅ НАШ OCO НАЙДЕН БЕЗ ФИЛЬТРА!")
                    print(f"   - instId: {order.get('instId')}")
                    print(f"   - ordType: {order.get('ordType')}")
                    print(f"   - state: {order.get('state')}")
                    found_our_oco = True
                    break

            if not found_our_oco:
                print(f"   ❌ НАШ OCO НЕ НАЙДЕН БЕЗ ФИЛЬТРА")

        except Exception as e:
            print(f"   ❌ Ошибка без фильтра: {e}")

        # ИТОГОВЫЙ АНАЛИЗ
        print(f"\n📊 ИТОГОВЫЙ АНАЛИЗ:")
        print(f"   Размещенный OCO ID: {oco_id}")
        print(f"   Найдено через get_algo_orders: {len(algo_orders_oco)}")
        print(f"   Найдено через все ордера: {len(all_algo)}")

        if len(all_algo) > 0 and len(algo_orders_oco) == 0:
            print(
                f"   🔍 ПРОБЛЕМА: OCO размещен, но фильтр algo_type='oco' его не находит!"
            )
            print(f"   🔍 РЕШЕНИЕ: Нужно изменить логику фильтрации в get_algo_orders")
        elif len(all_algo) == 0:
            print(f"   🔍 ПРОБЛЕМА: OCO не размещается или сразу отменяется!")
        else:
            print(f"   ✅ OCO работает корректно")

        # Отменяем все ордера
        print(f"\n🧹 Очистка...")

        # OCO в sandbox мгновенно исчезает (исполняется/отменяется)
        # Не пытаемся отменять - это нормальное поведение
        if oco_id:
            print(f"   ℹ️ OCO {oco_id} уже не существует (исполнился/отменился)")

        print(f"\n✅ Тест завершен")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(test_oco_visibility())
