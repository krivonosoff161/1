"""
💰 CHECK BALANCE - Проверка общего баланса на OKX

Показывает:
- Баланс каждой валюты
- Эквивалент в USD
- Общий баланс портфеля
- Заёмные средства (если есть)

Использование:
    python scripts/check_balance.py
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
# tests/debug/check_balance.py -> parent.parent.parent = project root
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import load_config
from src.okx_client import OKXClient


async def main():
    print("=" * 70)
    print("💰 OKX BALANCE CHECKER")
    print("=" * 70)
    print()

    try:
        # Загружаем конфиг
        config = load_config()
        okx_config = config.get_okx_config()

        # Подключаемся к OKX
        async with OKXClient(okx_config) as client:
            print("✅ Connected to OKX")
            print()

            # Получаем балансы
            balances = await client.get_account_balance()

            if not balances:
                print("⚪ No balances found")
                return

            print("📊 ACCOUNT BALANCES:")
            print("-" * 70)

            total_usd = 0.0
            balance_data = []

            for balance in balances:
                if balance.total > 0:
                    # Получаем текущую цену
                    if balance.currency == "USDT":
                        price_usd = 1.0
                        value_usd = balance.total
                    else:
                        try:
                            ticker = await client.get_ticker(f"{balance.currency}-USDT")
                            price_usd = float(ticker.get("last", 0))
                            value_usd = balance.total * price_usd
                        except:
                            price_usd = 0
                            value_usd = 0

                    total_usd += value_usd
                    balance_data.append(
                        {
                            "currency": balance.currency,
                            "total": balance.total,
                            "free": balance.free,
                            "used": balance.used,
                            "price": price_usd,
                            "value_usd": value_usd,
                        }
                    )

            # Выводим балансы
            for b in balance_data:
                if b["currency"] == "USDT":
                    print(
                        f"💵 {b['currency']:6} | Total: ${b['total']:>12,.2f} | Free: ${b['free']:>12,.2f} | Used: ${b['used']:>8,.2f}"
                    )
                else:
                    print(
                        f"🪙 {b['currency']:6} | Total: {b['total']:>12,.8f} | Free: {b['free']:>12,.8f} | Price: ${b['price']:>10,.2f} | Value: ${b['value_usd']:>10,.2f}"
                    )

            print("-" * 70)
            print(f"💰 TOTAL PORTFOLIO VALUE: ${total_usd:,.2f}")
            print()

            # Проверка заёмных средств
            print("🔍 CHECKING BORROWED FUNDS...")
            print("-" * 70)

            has_borrowed = False
            for b in balance_data:
                try:
                    borrowed = await client.get_borrowed_balance(b["currency"])
                    if borrowed > 0:
                        has_borrowed = True
                        print(f"⚠️  {b['currency']:6} | Borrowed: {borrowed:.8f}")
                except Exception as e:
                    pass

            if not has_borrowed:
                print("✅ No borrowed funds - SPOT mode OK!")
            else:
                print()
                print("🚨 WARNING: Borrowed funds detected!")
                print("   Switch to SPOT mode and repay loans!")

            print("-" * 70)
            print()

            # Открытые позиции
            print("📈 OPEN POSITIONS:")
            print("-" * 70)

            try:
                positions = await client.get_positions()
                if positions:
                    for pos in positions:
                        emoji = "🟢" if pos.side.value == "long" else "🔴"
                        print(
                            f"{emoji} {pos.symbol:12} | {pos.side.value.upper():5} | Size: {pos.size:.8f} | Entry: ${pos.entry_price:,.2f} | PnL: ${pos.unrealized_pnl:+.2f}"
                        )
                else:
                    print("⚪ No open positions")
            except Exception as e:
                print(f"⚠️  Cannot fetch positions: {e}")

            print("-" * 70)
            print()
            print("=" * 70)
            print("✅ BALANCE CHECK COMPLETED")
            print("=" * 70)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        logger.error(f"Balance check failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
