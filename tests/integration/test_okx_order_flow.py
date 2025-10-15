"""
Интеграционный тест полного цикла сделки на OKX.

Тест:
1. Получить баланс
2. Разместить маленький MARKET ордер
3. Разместить OCO TP/SL
4. Проверить баланс после
5. Дождаться закрытия (TP/SL)
6. Финальный баланс

Цель: Найти где именно Invalid Sign!
"""

import asyncio
import os
import sys
from datetime import datetime

# Добавляем путь к src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from dotenv import load_dotenv
from loguru import logger

from src.config import APIConfig
from src.models import OrderSide, OrderType
from src.okx_client import OKXClient

# Настройка логирования
logger.remove()
logger.add(sys.stdout, level="DEBUG")  # DEBUG уровень для всех деталей!


async def test_full_order_cycle():
    """Полный цикл сделки с детальным логированием"""

    # Загружаем env
    load_dotenv()

    # Создаем конфиг
    config = APIConfig(
        api_key=os.getenv("OKX_API_KEY"),
        api_secret=os.getenv("OKX_API_SECRET"),
        passphrase=os.getenv("OKX_PASSPHRASE"),
        sandbox=True,  # DEMO режим!
    )

    print("=" * 80)
    print("INTEGRATION TEST: OKX Order Flow")
    print("=" * 80)
    print(f"Mode: DEMO (Sandbox)")
    print(f"Symbol: ETH-USDT")
    print(f"Order: LONG $20 (минимальная сумма для теста)")
    print("=" * 80)
    print()

    client = OKXClient(config)

    try:
        await client.connect()
        print("✅ Connected to OKX API\n")

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 1: Получить баланс ДО
        # ═══════════════════════════════════════════════════════════════
        print("📊 STEP 1: Get balance BEFORE")
        print("-" * 80)

        try:
            usdt_before = await client.get_balance("USDT")
            print(f"✅ USDT Balance: ${usdt_before:.2f}")
        except Exception as e:
            print(f"❌ ERROR getting USDT balance: {e}")
            return

        try:
            eth_before = await client.get_balance("ETH")
            print(f"✅ ETH Balance: {eth_before:.8f}")
        except Exception as e:
            print(f"❌ ERROR getting ETH balance: {e}")
            return

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 2: Разместить LONG ордер (BUY)
        # ═══════════════════════════════════════════════════════════════
        print("📤 STEP 2: Place LONG (BUY) order")
        print("-" * 80)

        symbol = "ETH-USDT"
        buy_amount_usdt = 20.0  # Минимум для теста

        print(f"Symbol: {symbol}")
        print(f"Side: BUY")
        print(f"Type: MARKET")
        print(f"Amount: ${buy_amount_usdt} USDT (with tgtCcy='quote_ccy')")
        print()

        try:
            order = await client.place_order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=buy_amount_usdt,  # Сумма в USDT
            )
            print(f"✅ Order placed!")
            print(f"   Order ID: {order.id}")
            print(f"   Expected: ~{buy_amount_usdt / 4000:.6f} ETH (примерно)")
        except Exception as e:
            print(f"❌ ERROR placing order: {e}")
            return

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 3: Подождать и проверить баланс ПОСЛЕ
        # ═══════════════════════════════════════════════════════════════
        print("⏳ STEP 3: Wait 1 second and check balance AFTER")
        print("-" * 80)

        await asyncio.sleep(1)

        try:
            eth_after = await client.get_balance("ETH")
            print(f"✅ ETH Balance AFTER: {eth_after:.8f}")
            print(f"   Difference: {eth_after - eth_before:.8f} ETH (bought)")
        except Exception as e:
            print(f"❌ ERROR getting ETH balance AFTER: {e}")
            return

        try:
            usdt_after = await client.get_balance("USDT")
            print(f"✅ USDT Balance AFTER: ${usdt_after:.2f}")
            print(f"   Spent: ${usdt_before - usdt_after:.2f}")
        except Exception as e:
            print(f"❌ ERROR getting USDT balance AFTER: {e}")
            return

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 4: Рассчитать TP/SL и разместить OCO
        # ═══════════════════════════════════════════════════════════════
        print("🎯 STEP 4: Place OCO (TP/SL) order")
        print("-" * 80)

        # Получаем текущую цену
        try:
            ticker = await client.get_ticker(symbol)
            current_price = float(ticker.get("last", ticker.get("lastPx", 0)))
            print(f"Current price: ${current_price:.2f}")
        except Exception as e:
            print(f"❌ ERROR getting ticker: {e}")
            return

        # Рассчитываем TP/SL (маленькие для быстрого закрытия)
        tp_price = current_price * 0.999  # -0.1% для TP (SHORT имитация)
        sl_price = current_price * 1.002  # +0.2% для SL

        actual_eth_bought = eth_after - eth_before

        print(f"Position size: {actual_eth_bought:.8f} ETH")
        print(f"TP price: ${tp_price:.2f} (-0.1%)")
        print(f"SL price: ${sl_price:.2f} (+0.2%)")
        print()

        try:
            print("📤 Calling place_oco_order()...")
            oco_id = await client.place_oco_order(
                symbol=symbol,
                side=OrderSide.SELL,  # Закрываем LONG
                quantity=actual_eth_bought,
                tp_trigger_price=tp_price,
                sl_trigger_price=sl_price,
            )
            print(f"✅ OCO order placed!")
            print(f"   OCO ID: {oco_id}")
            print(f"   Endpoint: POST /trade/order-algo")
        except Exception as e:
            print(f"❌ ERROR placing OCO: {e}")
            import traceback

            traceback.print_exc()
            return

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 5: Проверить баланс СРАЗУ ПОСЛЕ OCO (ЗДЕСЬ ОШИБКА?)
        # ═══════════════════════════════════════════════════════════════
        print("🔍 STEP 5: Check balance IMMEDIATELY after OCO")
        print("-" * 80)
        print("⚠️ КРИТИЧЕСКИЙ МОМЕНТ: Здесь обычно Invalid Sign!")
        print()

        try:
            eth_after_oco = await client.get_balance("ETH")
            print(f"✅ ETH Balance after OCO: {eth_after_oco:.8f}")
        except Exception as e:
            print(f"❌ ERROR getting ETH after OCO: {e}")
            print(f"🎯 НАЙДЕНА ПРОБЛЕМА! get_balance() после OCO дает Invalid Sign!")
            return

        try:
            usdt_after_oco = await client.get_balance("USDT")
            print(f"✅ USDT Balance after OCO: ${usdt_after_oco:.2f}")
        except Exception as e:
            print(f"❌ ERROR getting USDT after OCO: {e}")
            return

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 6: Подождать закрытия (TP должен сработать быстро)
        # ═══════════════════════════════════════════════════════════════
        print("⏳ STEP 6: Wait for TP/SL (max 60 seconds)")
        print("-" * 80)

        for i in range(60):
            await asyncio.sleep(1)

            try:
                eth_now = await client.get_balance("ETH")
                usdt_now = await client.get_balance("USDT")

                if abs(eth_now - eth_before) < 0.00001:
                    # Позиция закрылась!
                    print(f"\n✅ Position CLOSED at {i+1} seconds!")
                    print(f"   ETH: {eth_after:.8f} → {eth_now:.8f}")
                    print(f"   USDT: ${usdt_after:.2f} → ${usdt_now:.2f}")
                    print(f"   P&L: ${usdt_now - usdt_before:.2f}")
                    break

                if (i + 1) % 10 == 0:
                    print(f"   {i+1}s: ETH={eth_now:.8f}, USDT=${usdt_now:.2f}")

            except Exception as e:
                print(f"❌ ERROR checking balance at {i+1}s: {e}")
                print(f"🎯 Invalid Sign на {i+1} секунде!")
                break

        print()

        # ═══════════════════════════════════════════════════════════════
        # ШАГ 7: Финальный баланс
        # ═══════════════════════════════════════════════════════════════
        print("📊 STEP 7: Final balance")
        print("-" * 80)

        try:
            eth_final = await client.get_balance("ETH")
            usdt_final = await client.get_balance("USDT")

            print(
                f"ETH: {eth_before:.8f} → {eth_final:.8f} (Δ {eth_final - eth_before:.8f})"
            )
            print(
                f"USDT: ${usdt_before:.2f} → ${usdt_final:.2f} (Δ ${usdt_final - usdt_before:.2f})"
            )

        except Exception as e:
            print(f"❌ ERROR getting final balance: {e}")

        print()
        print("=" * 80)
        print("✅ TEST COMPLETED")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback

        traceback.print_exc()

    finally:
        await client.disconnect()
        print("\n✅ Disconnected from OKX API")


if __name__ == "__main__":
    print()
    print("WARNING: This test will place REAL orders on DEMO account!")
    print("Make sure you have DEMO (sandbox) credentials in .env file")
    print()
    print("Starting test...")
    print()
    asyncio.run(test_full_order_cycle())
