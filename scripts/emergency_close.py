"""
🚨 EMERGENCY CLOSE - Ручное закрытие всех позиций

Использование:
    python scripts/emergency_close.py

ВАЖНО: Останови бота ПЕРЕД запуском этого скрипта!
"""

import asyncio
import sys
from pathlib import Path

# Добавляем корень проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from loguru import logger

from src.config import load_config
from src.models import OrderSide, OrderType, Position, PositionSide
from src.okx_client import OKXClient


async def main():
    print("=" * 60)
    print("🚨 EMERGENCY CLOSE ALL POSITIONS")
    print("=" * 60)
    print()

    # Подтверждение
    confirm = input("⚠️  Are you sure? This will close ALL open positions! (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Cancelled.")
        return

    print()
    print("🔄 Loading configuration...")

    try:
        # Загружаем конфиг
        config = load_config()
        okx_config = config.get_okx_config()

        # Подключаемся к OKX
        async with OKXClient(okx_config) as client:
            print("✅ Connected to OKX")
            print()

            # Получаем позиции с биржи
            print("📊 Fetching positions from exchange...")
            exchange_positions = await client.get_positions()

            if not exchange_positions:
                print("⚪ No open positions found on exchange")
                return

            print(f"📊 Found {len(exchange_positions)} open positions:")
            print()

            for pos in exchange_positions:
                print(
                    f"  • {pos.symbol} {pos.side.value.upper()}: {pos.size:.8f} @ ${pos.entry_price:.2f}"
                )

            print()

            # Закрываем каждую позицию
            for pos in exchange_positions:
                try:
                    print(f"🔴 Closing {pos.symbol} {pos.side.value.upper()}...")

                    # Определяем сторону закрытия
                    close_side = (
                        OrderSide.SELL
                        if pos.side == PositionSide.LONG
                        else OrderSide.BUY
                    )

                    # Получаем текущую цену
                    ticker = await client.get_ticker(pos.symbol)
                    current_price = float(ticker.get("last", pos.entry_price))

                    # Размещаем MARKET ордер
                    order = await client.place_order(
                        symbol=pos.symbol,
                        side=close_side,
                        order_type=OrderType.MARKET,
                        quantity=pos.size,
                    )

                    if order:
                        # Расчет PnL
                        if pos.side == PositionSide.LONG:
                            pnl = (current_price - pos.entry_price) * pos.size
                        else:
                            pnl = (pos.entry_price - current_price) * pos.size

                        print(f"  ✅ Closed @ ${current_price:.2f} | PnL: ${pnl:.2f}")
                    else:
                        print(f"  ❌ Failed to close")

                except Exception as e:
                    print(f"  ❌ Error: {e}")

            print()
            print("=" * 60)
            print("🚨 EMERGENCY CLOSE COMPLETED")
            print("=" * 60)

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        logger.error(f"Emergency close failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())
