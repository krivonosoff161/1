#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Забирает РЕАЛЬНУЮ историю сделок с OKX и анализирует
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

# Добавляем корень проекта
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config import load_config
from src.okx_client import OKXClient


class TradeAnalyzer:
    """Анализатор реальных сделок с биржи"""

    def __init__(self):
        self.client = None
        self.config = None
        self.trades = []
        self.orders = []
        self.oco_orders = []
        self.positions = []

    async def connect(self):
        """Подключение к OKX"""
        print("🔌 Подключаюсь к OKX API...")

        self.config = load_config("config.yaml")
        okx_config = self.config.get_okx_config()
        self.client = OKXClient(okx_config)
        await self.client.connect()

        print("✅ Подключено к OKX!")

    async def fetch_closed_positions(self):
        """Забирает закрытые позиции"""
        print("\n📊 Загружаю закрытые позиции за последние 24 часа...")

        try:
            # OKX API: /api/v5/account/positions-history
            response = await self.client._make_request(
                "GET",
                "/account/positions-history",
                params={
                    "instType": "SPOT",  # Или MARGIN если маржинальная торговля
                },
            )

            if response and response.get("data"):
                self.positions = response["data"]
                print(f"✅ Получено {len(self.positions)} закрытых позиций")

                for pos in self.positions[:5]:  # Первые 5 для примера
                    print(
                        f"   - {pos.get('instId')}: {pos.get('posSide')} | PnL: {pos.get('realizedPnl', 'N/A')}"
                    )
            else:
                print("⚠️  Закрытых позиций не найдено (или это SPOT торговля)")

        except Exception as e:
            print(f"⚠️  Ошибка получения позиций: {e}")

    async def fetch_order_history(self, symbol="BTC-USDT"):
        """Забирает историю ордеров"""
        print(f"\n📋 Загружаю историю ордеров для {symbol}...")

        try:
            # За последние 24 часа
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

            response = await self.client._make_request(
                "GET",
                "/trade/orders-history",
                params={
                    "instId": symbol,
                    "begin": start_time,
                    "end": end_time,
                    "limit": 100,
                },
            )

            if response and response.get("data"):
                orders = response["data"]
                print(f"✅ Получено {len(orders)} ордеров")

                # Группируем по статусу
                filled = [o for o in orders if o.get("state") == "filled"]
                canceled = [o for o in orders if o.get("state") == "canceled"]

                print(f"   Исполнено: {len(filled)}")
                print(f"   Отменено: {len(canceled)}")

                self.orders.extend(orders)

                return orders
            else:
                print("⚠️  Ордеров не найдено")
                return []

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return []

    async def fetch_algo_orders(self, symbol="BTC-USDT"):
        """Забирает историю алго-ордеров (OCO, TP/SL)"""
        print(f"\n🤖 Загружаю историю OCO ордеров для {symbol}...")

        try:
            # Сначала активные
            response_active = await self.client._make_request(
                "GET",
                "/trade/orders-algo-pending",
                params={"instId": symbol, "ordType": "oco"},
            )

            # Потом исторические
            response_history = await self.client._make_request(
                "GET",
                "/trade/orders-algo-history",
                params={
                    "instId": symbol,
                    "ordType": "oco",
                    "state": "effective",  # Исполненные
                },
            )

            active = response_active.get("data", []) if response_active else []
            history = response_history.get("data", []) if response_history else []

            print(f"✅ Активных OCO: {len(active)}")
            print(f"✅ Исполненных OCO: {len(history)}")

            self.oco_orders = active + history

            return self.oco_orders

        except Exception as e:
            print(f"⚠️  Ошибка получения OCO: {e}")
            return []

    async def fetch_fills(self, symbol="BTC-USDT"):
        """Забирает fills (исполненные сделки)"""
        print(f"\n💰 Загружаю fills (исполненные сделки) для {symbol}...")

        try:
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)

            response = await self.client._make_request(
                "GET",
                "/trade/fills",
                params={
                    "instId": symbol,
                    "begin": start_time,
                    "end": end_time,
                    "limit": 100,
                },
            )

            if response and response.get("data"):
                fills = response["data"]
                print(f"✅ Получено {len(fills)} fills")

                self.trades = fills

                # Группируем по side
                buys = [f for f in fills if f.get("side") == "buy"]
                sells = [f for f in fills if f.get("side") == "sell"]

                print(f"   Покупок: {len(buys)}")
                print(f"   Продаж: {len(sells)}")

                return fills
            else:
                print("⚠️  Fills не найдены")
                return []

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return []

    def analyze_trades(self):
        """Анализирует сделки и находит пары"""
        print("\n" + "=" * 100)
        print("🔍 АНАЛИЗ СДЕЛОК")
        print("=" * 100 + "\n")

        if not self.trades:
            print("❌ Нет данных для анализа")
            return

        # Сортируем по времени
        sorted_trades = sorted(self.trades, key=lambda x: int(x.get("ts", 0)))

        # Ищем пары (BUY -> SELL)
        positions = []
        open_buys = []

        for trade in sorted_trades:
            side = trade.get("side")
            symbol = trade.get("instId")
            price = float(trade.get("fillPx", 0))
            size = float(trade.get("fillSz", 0))
            fee = float(trade.get("fee", 0))
            timestamp = datetime.fromtimestamp(int(trade.get("ts", 0)) / 1000)
            order_id = trade.get("ordId")

            if side == "buy":
                open_buys.append(
                    {
                        "symbol": symbol,
                        "buy_price": price,
                        "size": size,
                        "buy_fee": abs(fee),
                        "buy_time": timestamp,
                        "buy_order_id": order_id,
                    }
                )

            elif side == "sell" and open_buys:
                # Ищем соответствующую покупку
                for buy in open_buys:
                    if buy["symbol"] == symbol and abs(buy["size"] - size) < 0.0001:
                        # Нашли пару!
                        gross_pnl = (price - buy["buy_price"]) * size
                        total_fee = buy["buy_fee"] + abs(fee)
                        net_pnl = gross_pnl - total_fee
                        duration = (timestamp - buy["buy_time"]).total_seconds()

                        positions.append(
                            {
                                "symbol": symbol,
                                "buy_price": buy["buy_price"],
                                "sell_price": price,
                                "size": size,
                                "gross_pnl": gross_pnl,
                                "total_fee": total_fee,
                                "net_pnl": net_pnl,
                                "duration_sec": duration,
                                "buy_time": buy["buy_time"],
                                "sell_time": timestamp,
                                "buy_order_id": buy["buy_order_id"],
                                "sell_order_id": order_id,
                            }
                        )

                        open_buys.remove(buy)
                        break

        # Печатаем результаты
        if positions:
            print(f"✅ Найдено {len(positions)} закрытых позиций:\n")

            total_pnl = 0
            wins = 0

            for i, pos in enumerate(positions, 1):
                print(f"{i}. {pos['symbol']}")
                print(f"   Открыта: {pos['buy_time'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Закрыта: {pos['sell_time'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(
                    f"   Длительность: {pos['duration_sec']:.0f}с ({pos['duration_sec']/60:.1f}мин)"
                )
                print(f"   Entry: ${pos['buy_price']:.2f}")
                print(f"   Exit:  ${pos['sell_price']:.2f}")
                print(f"   Size:  {pos['size']:.8f}")
                print(f"   Gross PnL: ${pos['gross_pnl']:.4f}")
                print(f"   Fee: ${pos['total_fee']:.4f}")
                print(f"   Net PnL: ${pos['net_pnl']:.4f}")

                if pos["net_pnl"] > 0:
                    print(f"   ✅ PROFIT")
                    wins += 1
                else:
                    print(f"   ❌ LOSS")

                total_pnl += pos["net_pnl"]
                print()

            print("=" * 100)
            print("📊 ИТОГОВАЯ СТАТИСТИКА:")
            print("=" * 100)
            print(f"Всего сделок: {len(positions)}")
            print(f"Прибыльных: {wins} ({wins/len(positions)*100:.1f}%)")
            print(
                f"Убыточных: {len(positions) - wins} ({(len(positions) - wins)/len(positions)*100:.1f}%)"
            )
            print(f"Total Net PnL: ${total_pnl:.4f}")
            print()

        if open_buys:
            print("=" * 100)
            print(f"⚠️  ОТКРЫТЫЕ ПОЗИЦИИ: {len(open_buys)}")
            print("=" * 100 + "\n")

            for buy in open_buys:
                print(f"  {buy['symbol']}")
                print(f"    Открыта: {buy['buy_time'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    Entry: ${buy['buy_price']:.2f}")
                print(f"    Size: {buy['size']:.8f}")
                print()

    def analyze_oco_orders(self):
        """Анализирует OCO ордера"""
        print("\n" + "=" * 100)
        print("🤖 АНАЛИЗ OCO ОРДЕРОВ")
        print("=" * 100 + "\n")

        if not self.oco_orders:
            print("❌ OCO ордеров не найдено")
            return

        for i, oco in enumerate(self.oco_orders, 1):
            print(f"{i}. OCO Order ID: {oco.get('algoId')}")
            print(f"   Symbol: {oco.get('instId')}")
            print(f"   Status: {oco.get('state')}")
            print(f"   TP Price: {oco.get('tpTriggerPx')}")
            print(f"   SL Price: {oco.get('slTriggerPx')}")

            # Проверяем какой leg сработал
            actual_side = oco.get("actualSide")
            if actual_side:
                if actual_side == "tp":
                    print(f"   ✅ Сработал TAKE PROFIT")
                elif actual_side == "sl":
                    print(f"   ❌ Сработал STOP LOSS")

            print()

    async def run_analysis(self):
        """Полный анализ"""
        await self.connect()

        symbols = ["BTC-USDT", "ETH-USDT"]

        for symbol in symbols:
            print("\n" + "🔹" * 50)
            print(f"АНАЛИЗ: {symbol}")
            print("🔹" * 50)

            # Забираем данные
            await self.fetch_fills(symbol)
            await self.fetch_order_history(symbol)
            await self.fetch_algo_orders(symbol)

        # Анализируем
        self.analyze_trades()
        self.analyze_oco_orders()

        # Закрываем соединение
        await self.client.session.close()


async def main():
    print("\n" + "=" * 100)
    print("💰 АНАЛИЗАТОР РЕАЛЬНЫХ СДЕЛОК С OKX")
    print("=" * 100)

    analyzer = TradeAnalyzer()
    await analyzer.run_analysis()

    print("\n" + "=" * 100)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
