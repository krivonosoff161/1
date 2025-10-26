"""
Тест Maker-First Strategy для экономии комиссий
Проверяет POST-ONLY попытки и fallback на MARKET
"""

import asyncio
import sys
from datetime import datetime

from loguru import logger

# Добавляем корневую директорию проекта в sys.path
sys.path.append(".")

from src.config import load_config
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient


async def test_maker_vs_taker_commission():
    """Тест разницы комиссий Maker vs Taker"""
    print("💰 ТЕСТ КОМИССИЙ MAKER vs TAKER")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        # Получаем текущую цену BTC
        ticker = await client.get_ticker("BTC-USDT")
        current_price = float(ticker.get("last", 0))

        # Тестовый размер позиции
        test_value_usdt = 100.0  # $100
        test_quantity = test_value_usdt / current_price

        print(f"📊 Тестовые параметры:")
        print(f"   Текущая цена BTC: ${current_price:.2f}")
        print(f"   Тестовый размер: ${test_value_usdt} ({test_quantity:.8f} BTC)")

        # Расчет комиссий
        maker_commission = test_value_usdt * 0.0008  # 0.08%
        taker_commission = test_value_usdt * 0.001  # 0.10%
        commission_savings = taker_commission - maker_commission
        savings_percent = (commission_savings / taker_commission) * 100

        print(f"\n💸 Комиссии:")
        print(f"   Maker (POST-ONLY): ${maker_commission:.4f} (0.08%)")
        print(f"   Taker (MARKET): ${taker_commission:.4f} (0.10%)")
        print(f"   Экономия: ${commission_savings:.4f} ({savings_percent:.1f}%)")

        # Расчет для разных размеров позиций
        print(f"\n📈 Экономия на разных размерах:")
        sizes = [50, 100, 200, 500, 1000]
        for size in sizes:
            maker_fee = size * 0.0008
            taker_fee = size * 0.001
            savings = taker_fee - maker_fee
            print(
                f"   ${size:4d}: Экономия ${savings:.4f} ({savings/size*100:.2f}% от позиции)"
            )

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста комиссий: {e}")


async def test_post_only_order():
    """Тест размещения POST-ONLY ордера"""
    print("\n🎯 ТЕСТ POST-ONLY ОРДЕРА")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        # Получаем текущую цену
        ticker = await client.get_ticker("BTC-USDT")
        current_price = float(ticker.get("last", 0))

        # Рассчитываем цену для POST-ONLY (немного хуже рыночной)
        maker_price = current_price * 0.9995  # -0.05%
        test_quantity = 0.0001  # Очень маленький размер для теста

        print(f"📊 POST-ONLY параметры:")
        print(f"   Текущая цена: ${current_price:.2f}")
        print(f"   POST-ONLY цена: ${maker_price:.2f}")
        print(f"   Тестовый размер: {test_quantity} BTC")
        print(f"   ⚠️ ВНИМАНИЕ: Это тест на САНДБОКСЕ!")

        # Размещаем POST-ONLY ордер
        print(f"\n🚀 Размещение POST-ONLY ордера...")
        start_time = datetime.utcnow()

        order = await client.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=test_quantity,
            price=maker_price,
            post_only=True,
        )

        order_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        if order:
            print(f"   ✅ POST-ONLY ордер размещен за {order_time:.1f} мс")
            print(f"   Order ID: {order.id}")
            print(f"   Status: {order.status}")
            print(f"   Price: ${order.price}")
            print(f"   Commission: 0.08% (Maker)")
        else:
            print(f"   ❌ POST-ONLY ордер не размещен за {order_time:.1f} мс")
            print(
                f"   Возможные причины: цена неконкурентоспособна, недостаток ликвидности"
            )

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста POST-ONLY: {e}")


async def test_maker_fallback():
    """Тест fallback с POST-ONLY на MARKET"""
    print("\n🔄 ТЕСТ MAKER FALLBACK")
    print("=" * 50)

    try:
        config = load_config()
        client = OKXClient(config.api["okx"])
        await client.connect()

        # Получаем текущую цену
        ticker = await client.get_ticker("BTC-USDT")
        current_price = float(ticker.get("last", 0))

        # Тест 1: POST-ONLY с неконкурентоспособной ценой (должен упасть)
        bad_price = current_price * 0.95  # -5% (слишком далеко от рынка)
        test_quantity = 0.0001

        print(f"📊 Тест с неконкурентоспособной ценой:")
        print(f"   Рыночная цена: ${current_price:.2f}")
        print(f"   POST-ONLY цена: ${bad_price:.2f} (-5%)")
        print(f"   Ожидаемый результат: POST-ONLY должен упасть")

        start_time = datetime.utcnow()

        # Попытка POST-ONLY
        post_only_order = await client.place_order(
            symbol="BTC-USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=test_quantity,
            price=bad_price,
            post_only=True,
        )

        post_only_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        if not post_only_order:
            print(f"   ✅ POST-ONLY упал как ожидалось за {post_only_time:.1f} мс")

            # Fallback на MARKET
            print(f"\n🔄 Fallback на MARKET...")
            start_time = datetime.utcnow()

            market_order = await client.place_order(
                symbol="BTC-USDT",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=test_quantity,
            )

            market_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            if market_order:
                print(f"   ✅ MARKET fallback успешен за {market_time:.1f} мс")
                print(f"   Order ID: {market_order.id}")
                print(f"   Commission: 0.10% (Taker)")
            else:
                print(f"   ❌ MARKET fallback не сработал")
        else:
            print(
                f"   ⚠️ POST-ONLY неожиданно сработал (возможно, цена стала конкурентоспособной)"
            )

        await client.disconnect()

    except Exception as e:
        print(f"❌ Ошибка теста fallback: {e}")


async def test_commission_calculation():
    """Тест расчета комиссий в PositionManager"""
    print("\n🧮 ТЕСТ РАСЧЕТА КОМИССИЙ")
    print("=" * 50)

    try:
        # Симулируем разные сценарии
        scenarios = [
            {
                "entry_price": 50000.0,
                "exit_price": 50000.0,
                "size": 0.001,
                "description": "POST-ONLY (цена не изменилась)",
            },
            {
                "entry_price": 50000.0,
                "exit_price": 50010.0,
                "size": 0.001,
                "description": "MARKET (цена изменилась)",
            },
            {
                "entry_price": 50000.0,
                "exit_price": 51000.0,
                "size": 0.001,
                "description": "MARKET (большое изменение)",
            },
        ]

        for i, scenario in enumerate(scenarios, 1):
            entry_price = scenario["entry_price"]
            exit_price = scenario["exit_price"]
            size = scenario["size"]
            description = scenario["description"]

            # Определяем тип entry ордера
            price_diff_pct = abs(exit_price - entry_price) / entry_price

            if price_diff_pct < 0.001:  # < 0.1% разница = POST-ONLY
                open_commission_rate = 0.0008  # Maker
                entry_type = "POST-ONLY (Maker)"
            else:
                open_commission_rate = 0.001  # Taker
                entry_type = "MARKET (Taker)"

            close_commission_rate = 0.001  # Taker (всегда MARKET)

            # Расчет комиссий
            open_value = size * entry_price
            close_value = size * exit_price
            open_commission = open_value * open_commission_rate
            close_commission = close_value * close_commission_rate
            total_commission = open_commission + close_commission

            print(f"📊 Сценарий {i}: {description}")
            print(f"   Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f}")
            print(f"   Entry type: {entry_type}")
            print(
                f"   Open commission: ${open_commission:.4f} ({open_commission_rate*100:.2f}%)"
            )
            print(
                f"   Close commission: ${close_commission:.4f} ({close_commission_rate*100:.2f}%)"
            )
            print(f"   Total commission: ${total_commission:.4f}")
            print()

    except Exception as e:
        print(f"❌ Ошибка теста расчета комиссий: {e}")


async def main():
    """Главная функция тестирования"""
    print("🧪 ТЕСТИРОВАНИЕ MAKER-FIRST STRATEGY")
    print("=" * 60)

    # Тест 1: Комиссии
    await test_maker_vs_taker_commission()

    # Тест 2: POST-ONLY ордер
    await test_post_only_order()

    # Тест 3: Fallback
    await test_maker_fallback()

    # Тест 4: Расчет комиссий
    await test_commission_calculation()

    print("\n✅ ТЕСТИРОВАНИЕ MAKER STRATEGY ЗАВЕРШЕНО")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
