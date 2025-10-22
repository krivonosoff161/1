#!/usr/bin/env python3
"""
Проверка баланса на OKX
"""
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.config import APIConfig
from src.okx_client import OKXClient


async def main():
    try:
        # Загружаем конфиг
        config = APIConfig()
        client = OKXClient(config)

        print("🔍 ПРОВЕРКА БАЛАНСА OKX")
        print("=" * 50)

        # Получаем баланс
        balances = await client.get_account_balance()

        total_usd = 0.0
        print(
            f"{'Валюта':<10} {'Свободно':<15} {'Заморожено':<15} {'Всего':<15} {'USD':<15}"
        )
        print("-" * 70)

        for balance in balances:
            if balance.total > 0:
                # Примерная конвертация в USD (упрощенно)
                if balance.currency == "USDT":
                    usd_value = balance.total
                elif balance.currency == "BTC":
                    # Получаем цену BTC
                    try:
                        ticker = await client.get_ticker("BTC-USDT")
                        btc_price = float(ticker.get("last", 0))
                        usd_value = balance.total * btc_price
                    except:
                        usd_value = balance.total * 100000  # Примерная цена
                elif balance.currency == "ETH":
                    try:
                        ticker = await client.get_ticker("ETH-USDT")
                        eth_price = float(ticker.get("last", 0))
                        usd_value = balance.total * eth_price
                    except:
                        usd_value = balance.total * 4000  # Примерная цена
                else:
                    usd_value = 0

                total_usd += usd_value

                print(
                    f"{balance.currency:<10} {balance.free:<15.8f} {balance.frozen:<15.8f} {balance.total:<15.8f} ${usd_value:<14.2f}"
                )

        print("-" * 70)
        print(f"{'ИТОГО USD:':<40} ${total_usd:.2f}")
        print("=" * 50)

        # Проверяем открытые позиции
        print("\n🔍 ОТКРЫТЫЕ ПОЗИЦИИ:")
        positions = await client.get_positions()
        if positions:
            for pos in positions:
                print(
                    f"  {pos.symbol}: {pos.side.value} {pos.size:.8f} @ ${pos.entry_price:.2f}"
                )
        else:
            print("  Нет открытых позиций")

    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
