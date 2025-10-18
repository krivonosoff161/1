"""
Интеграционный тест полного цикла позиций SHORT и LONG
Тестирует: открытие, OCO, проверку статуса, закрытие

ВНИМАНИЕ: Использует РЕАЛЬНЫЙ API OKX (demo/live)
"""
import asyncio
import os
import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient

# Загружаем конфиг
config = load_config("config.yaml")


async def test_short_position_lifecycle():
    """
    Тест SHORT позиции: SELL -> OCO -> Проверка -> Закрытие (BUY)
    """
    print("\n" + "=" * 60)
    print("TEST: SHORT POSITION LIFECYCLE (BTC-USDT)")
    print("=" * 60)

    # Получаем API конфиг для OKX
    from src.config import APIConfig

    api_config = config.api.get("okx") or APIConfig(
        api_key=os.getenv("OKX_API_KEY", ""),
        api_secret=os.getenv("OKX_SECRET_KEY", ""),
        passphrase=os.getenv("OKX_PASSPHRASE", ""),
        sandbox=True,
    )
    client = OKXClient(api_config)

    symbol = "BTC-USDT"

    # Шаг 1: Получаем начальные балансы
    print("\n[1] Получаем начальные балансы...")
    initial_btc = await client.get_balance("BTC")
    initial_usdt = await client.get_balance("USDT")
    print(f"   BTC: {initial_btc:.8f}")
    print(f"   USDT: ${initial_usdt:.2f}")

    # Шаг 2: Получаем текущую цену
    print("\n[2] Получаем текущую цену BTC...")
    ticker = await client.get_ticker(symbol)
    current_price = float(ticker["last"])
    print(f"   Current price: ${current_price:.2f}")

    # Шаг 3: Рассчитываем размер позиции (минимум $70)
    position_value = 71.40
    position_size = position_value / current_price
    print(f"\n[3] Размер позиции для SHORT:")
    print(f"   Value: ${position_value:.2f}")
    print(f"   Size: {position_size:.8f} BTC")

    # Проверка: хватит ли BTC для продажи?
    if initial_btc < position_size:
        print(f"\n!!! INSUFFICIENT BTC for SHORT !!!")
        print(f"   Have: {initial_btc:.8f}")
        print(f"   Need: {position_size:.8f}")
        return

    # Шаг 4: Открываем SHORT (SELL BTC)
    print(
        f"\n[4] Открываем SHORT: SELL {position_size:.8f} BTC @ ${current_price:.2f}..."
    )
    sell_order = await client.place_order(
        symbol=symbol,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=position_size,
    )
    print(f"   Order ID: {sell_order.id}")
    print(f"   Status: {sell_order.status}")

    # Ждем секунду
    await asyncio.sleep(1)

    # Шаг 5: Проверяем баланс после SELL
    print("\n[5] Проверяем балансы после SELL...")
    after_sell_btc = await client.get_balance("BTC")
    after_sell_usdt = await client.get_balance("USDT")
    print(
        f"   BTC: {after_sell_btc:.8f} (было {initial_btc:.8f}, diff: {after_sell_btc - initial_btc:.8f})"
    )
    print(
        f"   USDT: ${after_sell_usdt:.2f} (было ${initial_usdt:.2f}, diff: ${after_sell_usdt - initial_usdt:.2f})"
    )

    # Шаг 6: Выставляем OCO (TP + SL)
    tp_price = current_price * 0.999  # -0.1% для TP (SHORT прибыль = цена вниз)
    sl_price = current_price * 1.001  # +0.1% для SL (SHORT лосс = цена вверх)

    # Проверяем что SL выше текущей цены
    if sl_price <= current_price:
        sl_price = current_price * 1.002  # +0.2% для SL

    print(f"\n[6] Выставляем OCO ордер:")
    print(f"   TP: ${tp_price:.2f} (-0.1%)")
    print(f"   SL: ${sl_price:.2f} (+0.1%)")

    oco_order_id = await client.place_oco_order(
        symbol=symbol,
        side=OrderSide.BUY,  # Закрытие SHORT = BUY
        quantity=position_size,
        tp_trigger_price=tp_price,
        sl_trigger_price=sl_price,
    )
    print(f"   OCO ID: {oco_order_id}")

    # Шаг 7: Проверяем статус OCO
    print("\n[7] Проверяем статус OCO...")
    try:
        # Пробуем получить через API активные алго-ордера
        oco_status = await client._make_request(
            "GET",
            "/trade/orders-algo-pending",
            params={
                "instType": "SPOT",
                "ordType": "oco",
            },
        )

        if oco_status.get("data"):
            for order in oco_status["data"][:3]:  # Первые 3
                print(
                    f"   OCO {order.get('algoId')}: {order.get('state')} | {order.get('instId')}"
                )
        else:
            print("   Нет активных OCO ордеров")

    except Exception as e:
        print(f"   Не удалось получить OCO статус: {e}")

    # Шаг 8: Ждем 5 секунд (чтобы увидеть, сработает ли OCO)
    print("\n[8] Ждем 5 секунд (OCO может сработать)...")
    await asyncio.sleep(5)

    # Шаг 9: Проверяем баланс (может OCO сработал?)
    print("\n[9] Проверяем балансы (может OCO сработал?)...")
    after_wait_btc = await client.get_balance("BTC")
    after_wait_usdt = await client.get_balance("USDT")
    print(f"   BTC: {after_wait_btc:.8f} (diff: {after_wait_btc - after_sell_btc:.8f})")
    print(
        f"   USDT: ${after_wait_usdt:.2f} (diff: ${after_wait_usdt - after_sell_usdt:.2f})"
    )

    if abs(after_wait_btc - after_sell_btc) > 0.00000001:
        print("   !!! OCO СРАБОТАЛ! Позиция закрыта биржей!")
    else:
        print("   OCO не сработал, закрываем вручную...")

        # Шаг 10: Закрываем вручную (BUY обратно)
        print(f"\n[10] Закрываем SHORT вручную: BUY {position_size:.8f} BTC...")

        # Сначала отменяем OCO
        try:
            await client._make_request(
                "POST",
                "/trade/cancel-algos",
                data=[
                    {
                        "algoId": oco_order_id,
                        "instId": symbol,
                    }
                ],
            )
            print(f"   OCO отменен: {oco_order_id}")
        except Exception as e:
            print(f"   Не удалось отменить OCO: {e}")

        await asyncio.sleep(1)

        # Покупаем обратно (sz в BTC, нужен tgtCcy!)
        # Используем внутренний метод чтобы передать tgtCcy
        buy_data = {
            "instId": symbol,
            "tdMode": "cash",
            "side": "buy",
            "ordType": "market",
            "sz": str(position_size),
            "tgtCcy": "base_ccy",  # sz в BTC!
        }
        result = await client._make_request("POST", "/trade/order", data=buy_data)
        from src.models import Order, OrderStatus

        buy_order = Order(
            id=result["data"][0]["ordId"],
            symbol=symbol,
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            amount=position_size,
            price=current_price,
            status=OrderStatus.PENDING,
        )
        print(f"   Buy Order ID: {buy_order.id}")

        await asyncio.sleep(1)

        # Финальные балансы
        print("\n[11] ФИНАЛЬНЫЕ БАЛАНСЫ:")
        final_btc = await client.get_balance("BTC")
        final_usdt = await client.get_balance("USDT")
        print(
            f"   BTC: {final_btc:.8f} (начало: {initial_btc:.8f}, diff: {final_btc - initial_btc:.8f})"
        )
        print(
            f"   USDT: ${final_usdt:.2f} (начало: ${initial_usdt:.2f}, diff: ${final_usdt - initial_usdt:.2f})"
        )

        # Подсчет P&L
        btc_diff = final_btc - initial_btc
        usdt_diff = final_usdt - initial_usdt
        print(f"\n   P&L: ${usdt_diff:.2f} USDT")

    await client.session.close()
    print("\n" + "=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)


async def test_long_position_lifecycle():
    """
    Тест LONG позиции: BUY -> OCO -> Проверка -> Закрытие (SELL)
    """
    print("\n" + "=" * 60)
    print("TEST: LONG POSITION LIFECYCLE (ETH-USDT)")
    print("=" * 60)

    # Получаем API конфиг для OKX
    from src.config import APIConfig

    api_config = config.api.get("okx") or APIConfig(
        api_key=os.getenv("OKX_API_KEY", ""),
        api_secret=os.getenv("OKX_SECRET_KEY", ""),
        passphrase=os.getenv("OKX_PASSPHRASE", ""),
        sandbox=True,
    )
    client = OKXClient(api_config)

    symbol = "ETH-USDT"

    # Шаг 1: Начальные балансы
    print("\n[1] Начальные балансы...")
    initial_eth = await client.get_balance("ETH")
    initial_usdt = await client.get_balance("USDT")
    print(f"   ETH: {initial_eth:.8f}")
    print(f"   USDT: ${initial_usdt:.2f}")

    # Проверка: хватит ли USDT?
    position_value = 71.40
    if initial_usdt < position_value:
        print(f"\n!!! INSUFFICIENT USDT for LONG !!!")
        print(f"   Have: ${initial_usdt:.2f}")
        print(f"   Need: ${position_value:.2f}")
        return

    # Шаг 2: Текущая цена
    print("\n[2] Текущая цена ETH...")
    ticker = await client.get_ticker(symbol)
    current_price = float(ticker["last"])
    print(f"   Current price: ${current_price:.2f}")

    expected_size = position_value / current_price
    print(f"\n[3] Размер позиции для LONG:")
    print(f"   Value: ${position_value:.2f}")
    print(f"   Expected size: {expected_size:.8f} ETH")

    # Шаг 4: Открываем LONG (BUY ETH за USDT)
    print(
        f"\n[4] Открываем LONG: BUY ${position_value:.2f} USDT of ETH @ ${current_price:.2f}..."
    )
    buy_order = await client.place_order(
        symbol=symbol,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=position_value,  # В USDT для LONG
    )
    print(f"   Order ID: {buy_order.id}")

    await asyncio.sleep(1)

    # Шаг 5: Балансы после BUY
    print("\n[5] Балансы после BUY...")
    after_buy_eth = await client.get_balance("ETH")
    after_buy_usdt = await client.get_balance("USDT")
    actual_bought = after_buy_eth - initial_eth
    print(
        f"   ETH: {after_buy_eth:.8f} (было {initial_eth:.8f}, купили: {actual_bought:.8f})"
    )
    print(
        f"   USDT: ${after_buy_usdt:.2f} (было ${initial_usdt:.2f}, diff: ${after_buy_usdt - initial_usdt:.2f})"
    )

    # Шаг 6: OCO (TP + SL)
    tp_price = current_price * 1.001  # +0.1% для TP (LONG прибыль = цена вверх)
    sl_price = current_price * 0.999  # -0.1% для SL (LONG лосс = цена вниз)

    print(f"\n[6] Выставляем OCO ордер:")
    print(f"   TP: ${tp_price:.2f} (+0.1%)")
    print(f"   SL: ${sl_price:.2f} (-0.1%)")

    oco_order_id = await client.place_oco_order(
        symbol=symbol,
        side=OrderSide.SELL,  # Закрытие LONG = SELL
        quantity=actual_bought,  # Продаем сколько купили
        tp_trigger_price=tp_price,
        sl_trigger_price=sl_price,
    )
    print(f"   OCO ID: {oco_order_id}")

    # Шаг 7: Ждем 5 секунд
    print("\n[7] Ждем 5 секунд (OCO может сработать)...")
    await asyncio.sleep(5)

    # Шаг 8: Проверяем баланс
    print("\n[8] Проверяем баланс (может OCO сработал?)...")
    after_wait_eth = await client.get_balance("ETH")
    after_wait_usdt = await client.get_balance("USDT")
    print(f"   ETH: {after_wait_eth:.8f} (diff: {after_wait_eth - after_buy_eth:.8f})")
    print(
        f"   USDT: ${after_wait_usdt:.2f} (diff: ${after_wait_usdt - after_buy_usdt:.2f})"
    )

    if abs(after_wait_eth - after_buy_eth) > 0.00000001:
        print("   !!! OCO СРАБОТАЛ! Позиция закрыта биржей!")
    else:
        print("   OCO не сработал, закрываем вручную...")

        # Отменяем OCO
        try:
            await client._make_request(
                "POST",
                "/trade/cancel-algos",
                data=[
                    {
                        "algoId": oco_order_id,
                        "instId": symbol,
                    }
                ],
            )
            print(f"   OCO отменен: {oco_order_id}")
        except Exception as e:
            print(f"   Не удалось отменить OCO: {e}")

        await asyncio.sleep(1)

        # Продаем обратно
        print(f"\n[9] Закрываем LONG вручную: SELL {actual_bought:.8f} ETH...")
        sell_order = await client.place_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=actual_bought,
        )
        print(f"   Sell Order ID: {sell_order.id}")

        await asyncio.sleep(1)

        # Финальные балансы
        print("\n[10] ФИНАЛЬНЫЕ БАЛАНСЫ:")
        final_eth = await client.get_balance("ETH")
        final_usdt = await client.get_balance("USDT")
        print(
            f"   ETH: {final_eth:.8f} (начало: {initial_eth:.8f}, diff: {final_eth - initial_eth:.8f})"
        )
        print(
            f"   USDT: ${final_usdt:.2f} (начало: ${initial_usdt:.2f}, diff: ${final_usdt - initial_usdt:.2f})"
        )

        # P&L
        usdt_diff = final_usdt - initial_usdt
        print(f"\n   P&L: ${usdt_diff:.2f} USDT")

    await client.session.close()
    print("\n" + "=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)


async def main():
    """
    Запускает оба теста последовательно
    """
    print("\n" + "=" * 60)
    print("INTEGRATION TEST: POSITION LIFECYCLE")
    print("=" * 60)
    # Проверяем режим через переменную окружения или конфиг
    is_demo = os.getenv("OKX_DEMO", "true").lower() == "true"
    print(f"Exchange: {'DEMO' if is_demo else 'LIVE'}")
    print("=" * 60)

    # Тест SHORT
    await test_short_position_lifecycle()

    print("\n\nОжидание 3 секунды перед следующим тестом...\n")
    await asyncio.sleep(3)

    # Тест LONG
    await test_long_position_lifecycle()


if __name__ == "__main__":
    asyncio.run(main())
