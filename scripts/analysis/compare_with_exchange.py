#!/usr/bin/env python3
"""
Сравнение данных бота с данными биржи OKX
Получает историю ордеров, позиций и fills с биржи за период 2025-12-04 - 2025-12-05
"""
import asyncio
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Добавляем путь к проекту
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.clients.futures_client import OKXFuturesClient
from src.config import load_config


class ExchangeDataComparator:
    def __init__(self):
        self.client = None
        self.bot_trades = []
        self.exchange_orders = []
        self.exchange_fills = []
        self.exchange_positions = []

    async def connect(self):
        """Подключение к OKX"""
        try:
            config = load_config()
            okx_config = config.get_okx_config()

            # OKXFuturesClient требует api_key, secret_key, passphrase
            self.client = OKXFuturesClient(
                api_key=okx_config.api_key,
                secret_key=okx_config.api_secret,
                passphrase=okx_config.passphrase,
                sandbox=okx_config.sandbox,
            )

            print("✅ Подключено к OKX Futures API")
        except Exception as e:
            print(f"❌ Ошибка подключения: {e}")
            raise

    def load_bot_trades(self, csv_path: Path):
        """Загрузка сделок из CSV бота"""
        print(f"\n📊 Загрузка сделок бота из {csv_path.name}...")
        try:
            df = pd.read_csv(csv_path)
            self.bot_trades = df.to_dict("records")
            print(f"✅ Загружено {len(self.bot_trades)} сделок из логов бота")
            return True
        except Exception as e:
            print(f"❌ Ошибка загрузки CSV: {e}")
            return False

    async def fetch_exchange_orders(self, start_date: datetime, end_date: datetime):
        """Получение истории ордеров с биржи"""
        print(f"\n📋 Получение истории ордеров с биржи...")
        print(f"   Период: {start_date.date()} - {end_date.date()}")

        try:
            # Конвертируем в миллисекунды
            start_ts = int(start_date.timestamp() * 1000)
            end_ts = int(end_date.timestamp() * 1000)

            # Символы для проверки
            symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

            all_orders = []

            for symbol in symbols:
                try:
                    # OKX API: /api/v5/trade/orders-history
                    params = {
                        "instType": "SWAP",
                        "instId": f"{symbol}-SWAP",
                        "begin": str(start_ts),
                        "end": str(end_ts),
                        "limit": 100,
                    }

                    response = await self.client._make_request(
                        "GET", "/api/v5/trade/orders-history", params=params
                    )

                    if response and response.get("code") == "0":
                        orders = response.get("data", [])
                        print(f"   ✅ {symbol}: {len(orders)} ордеров")
                        all_orders.extend(orders)
                    else:
                        print(f"   ⚠️ {symbol}: {response.get('msg', 'Ошибка')}")

                except Exception as e:
                    print(f"   ❌ {symbol}: Ошибка - {e}")

            self.exchange_orders = all_orders
            print(f"\n✅ Всего получено {len(all_orders)} ордеров с биржи")
            return all_orders

        except Exception as e:
            print(f"❌ Ошибка получения ордеров: {e}")
            import traceback

            traceback.print_exc()
            return []

    async def fetch_exchange_fills(self, start_date: datetime, end_date: datetime):
        """Получение fills (исполненных сделок) с биржи"""
        print(f"\n💰 Получение fills (исполненных сделок) с биржи...")
        print(f"   Период: {start_date.date()} - {end_date.date()}")

        try:
            start_ts = int(start_date.timestamp() * 1000)
            end_ts = int(end_date.timestamp() * 1000)

            symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"]

            all_fills = []

            for symbol in symbols:
                try:
                    # OKX API: /api/v5/trade/fills
                    params = {
                        "instType": "SWAP",
                        "instId": f"{symbol}-SWAP",
                        "begin": str(start_ts),
                        "end": str(end_ts),
                        "limit": 100,
                    }

                    response = await self.client._make_request(
                        "GET", "/api/v5/trade/fills", params=params
                    )

                    if response and response.get("code") == "0":
                        fills = response.get("data", [])
                        print(f"   ✅ {symbol}: {len(fills)} fills")
                        all_fills.extend(fills)
                    else:
                        print(f"   ⚠️ {symbol}: {response.get('msg', 'Ошибка')}")

                except Exception as e:
                    print(f"   ❌ {symbol}: Ошибка - {e}")

            self.exchange_fills = all_fills
            print(f"\n✅ Всего получено {len(all_fills)} fills с биржи")
            return all_fills

        except Exception as e:
            print(f"❌ Ошибка получения fills: {e}")
            import traceback

            traceback.print_exc()
            return []

    async def fetch_exchange_positions_history(
        self, start_date: datetime, end_date: datetime
    ):
        """Получение истории позиций с биржи"""
        print(f"\n📊 Получение истории позиций с биржи...")
        print(f"   Период: {start_date.date()} - {end_date.date()}")

        try:
            start_ts = int(start_date.timestamp() * 1000)
            end_ts = int(end_date.timestamp() * 1000)

            # OKX API: /api/v5/account/positions-history
            params = {
                "instType": "SWAP",
                "begin": str(start_ts),
                "end": str(end_ts),
                "limit": 100,
            }

            response = await self.client._make_request(
                "GET", "/api/v5/account/positions-history", params=params
            )

            if response and response.get("code") == "0":
                positions = response.get("data", [])
                print(f"✅ Получено {len(positions)} закрытых позиций с биржи")
                self.exchange_positions = positions
                return positions
            else:
                print(f"⚠️ Ошибка: {response.get('msg', 'Неизвестная ошибка')}")
                return []

        except Exception as e:
            print(f"❌ Ошибка получения позиций: {e}")
            import traceback

            traceback.print_exc()
            return []

    def compare_data(self):
        """Сравнение данных бота с данными биржи"""
        print("\n" + "=" * 80)
        print("🔍 СРАВНЕНИЕ ДАННЫХ БОТА С ДАННЫМИ БИРЖИ")
        print("=" * 80)

        # Статистика
        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Сделок в логах бота: {len(self.bot_trades)}")
        print(f"   Ордеров с биржи: {len(self.exchange_orders)}")
        print(f"   Fills с биржи: {len(self.exchange_fills)}")
        print(f"   Позиций с биржи: {len(self.exchange_positions)}")

        # Анализ fills
        if self.exchange_fills:
            print(f"\n💰 АНАЛИЗ FILLS С БИРЖИ:")

            # Группируем по символам
            fills_by_symbol = {}
            for fill in self.exchange_fills:
                inst_id = fill.get("instId", "").replace("-SWAP", "")
                if inst_id not in fills_by_symbol:
                    fills_by_symbol[inst_id] = []
                fills_by_symbol[inst_id].append(fill)

            for symbol, fills in fills_by_symbol.items():
                print(f"\n   {symbol}:")
                print(f"      Всего fills: {len(fills)}")

                # Группируем по стороне
                buys = [f for f in fills if f.get("side") == "buy"]
                sells = [f for f in fills if f.get("side") == "sell"]
                print(f"      Покупок (buy): {len(buys)}")
                print(f"      Продаж (sell): {len(sells)}")

                # Считаем общий объем
                total_volume = sum(float(f.get("fillSz", 0)) for f in fills)
                print(f"      Общий объем: {total_volume:.8f}")

                # Считаем комиссии
                total_fees = sum(abs(float(f.get("fee", 0))) for f in fills)
                print(f"      Общие комиссии: {total_fees:.4f} USDT")

        # Сравнение количества сделок
        print(f"\n📊 СРАВНЕНИЕ КОЛИЧЕСТВА:")

        # Считаем сделки бота по символам
        bot_trades_by_symbol = {}
        for trade in self.bot_trades:
            symbol = trade.get("symbol", "")
            if symbol not in bot_trades_by_symbol:
                bot_trades_by_symbol[symbol] = 0
            bot_trades_by_symbol[symbol] += 1

        print(f"\n   Сделки бота по символам:")
        for symbol, count in bot_trades_by_symbol.items():
            print(f"      {symbol}: {count}")

        # Считаем fills биржи по символам
        exchange_fills_by_symbol = {}
        for fill in self.exchange_fills:
            inst_id = fill.get("instId", "").replace("-SWAP", "")
            if inst_id not in exchange_fills_by_symbol:
                exchange_fills_by_symbol[inst_id] = 0
            exchange_fills_by_symbol[inst_id] += 1

        print(f"\n   Fills биржи по символам:")
        for symbol, count in exchange_fills_by_symbol.items():
            print(f"      {symbol}: {count}")

        # Сравнение PnL
        if self.bot_trades and self.exchange_positions:
            print(f"\n💰 СРАВНЕНИЕ PnL:")

            bot_total_pnl = sum(float(t.get("net_pnl", 0)) for t in self.bot_trades)
            print(f"   Общий PnL бота: ${bot_total_pnl:+.4f} USDT")

            exchange_total_pnl = sum(
                float(p.get("realizedPnl", 0)) for p in self.exchange_positions
            )
            print(f"   Общий PnL биржи: ${exchange_total_pnl:+.4f} USDT")

            difference = bot_total_pnl - exchange_total_pnl
            print(f"   Разница: ${difference:+.4f} USDT")

            if abs(difference) > 0.1:
                print(f"   ⚠️ ВНИМАНИЕ: Значительная разница в PnL!")
            else:
                print(f"   ✅ PnL совпадает")

        # Сохраняем данные для детального анализа
        self.save_comparison_report()

    def save_comparison_report(self):
        """Сохранение отчета сравнения"""
        report_path = Path("exchange_comparison_report.json")

        report = {
            "comparison_date": datetime.now(timezone.utc).isoformat(),
            "bot_trades_count": len(self.bot_trades),
            "exchange_orders_count": len(self.exchange_orders),
            "exchange_fills_count": len(self.exchange_fills),
            "exchange_positions_count": len(self.exchange_positions),
            "bot_trades": self.bot_trades[:10],  # Первые 10 для примера
            "exchange_fills_sample": self.exchange_fills[:10],  # Первые 10 для примера
            "exchange_positions_sample": self.exchange_positions[
                :10
            ],  # Первые 10 для примера
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n✅ Отчет сохранен в {report_path}")

    async def close(self):
        """Закрытие соединения"""
        if self.client:
            await self.client.close()


async def main():
    # Период для анализа
    start_date = datetime(2025, 12, 4, 0, 0, 0, tzinfo=timezone.utc)
    end_date = datetime(2025, 12, 6, 0, 0, 0, tzinfo=timezone.utc)

    # Путь к CSV файлу бота
    csv_path = Path(
        "logs/futures/archived/logs_2025-12-06_15-58-40/trades_2025-12-04.csv"
    )

    print("=" * 80)
    print("🔍 СРАВНЕНИЕ ДАННЫХ БОТА С ДАННЫМИ БИРЖИ OKX")
    print("=" * 80)

    comparator = ExchangeDataComparator()

    try:
        # Подключение
        await comparator.connect()

        # Загрузка данных бота
        if not csv_path.exists():
            print(f"❌ CSV файл не найден: {csv_path}")
            return

        comparator.load_bot_trades(csv_path)

        # Получение данных с биржи
        await comparator.fetch_exchange_orders(start_date, end_date)
        await comparator.fetch_exchange_fills(start_date, end_date)
        await comparator.fetch_exchange_positions_history(start_date, end_date)

        # Сравнение
        comparator.compare_data()

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await comparator.close()

    print("\n" + "=" * 80)
    print("✅ СРАВНЕНИЕ ЗАВЕРШЕНО")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
