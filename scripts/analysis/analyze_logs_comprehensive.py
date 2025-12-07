#!/usr/bin/env python3
"""
Комплексный анализ логов бота и сравнение с данными биржи
"""
import asyncio
import csv
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

# Добавляем путь к проекту
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.clients.futures_client import OKXFuturesClient
from src.config import load_config


class LogAnalyzer:
    def __init__(self, archive_path: Path):
        self.archive_path = archive_path
        self.extracted_path = archive_path.parent / archive_path.stem
        self.trades = []
        self.logs = []
        self.errors = []

    def extract_archive(self):
        """Распаковка архива"""
        if not self.extracted_path.exists():
            print(f"📦 Распаковка архива {self.archive_path.name}...")
            with zipfile.ZipFile(self.archive_path, "r") as zip_ref:
                zip_ref.extractall(self.extracted_path)
            print(f"✅ Архив распакован в {self.extracted_path}")
        else:
            print(f"✅ Архив уже распакован: {self.extracted_path}")

    def load_trades_csv(self):
        """Загрузка CSV файла со сделками"""
        csv_files = list(self.extracted_path.glob("trades_*.csv"))
        if not csv_files:
            print("⚠️ CSV файлы со сделками не найдены!")
            return

        for csv_file in csv_files:
            print(f"📊 Загрузка {csv_file.name}...")
            try:
                df = pd.read_csv(csv_file)
                self.trades.extend(df.to_dict("records"))
                print(f"✅ Загружено {len(df)} сделок из {csv_file.name}")
            except Exception as e:
                print(f"❌ Ошибка загрузки {csv_file.name}: {e}")

    def analyze_trades(self):
        """Анализ сделок"""
        if not self.trades:
            print("⚠️ Нет сделок для анализа!")
            return

        df = pd.DataFrame(self.trades)

        # Конвертируем timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df["net_pnl"] = pd.to_numeric(df["net_pnl"], errors="coerce")
        df["duration_sec"] = pd.to_numeric(df["duration_sec"], errors="coerce")

        print("\n" + "=" * 80)
        print("📊 АНАЛИЗ СДЕЛОК")
        print("=" * 80)

        # Общая статистика
        total_trades = len(df)
        positive = len(df[df["net_pnl"] > 0])
        negative = len(df[df["net_pnl"] < 0])
        zero = len(df[df["net_pnl"] == 0])

        print(f"\n📈 ОБЩАЯ СТАТИСТИКА:")
        print(f"   Всего сделок: {total_trades}")
        print(f"   ✅ Положительных: {positive} ({positive/total_trades*100:.1f}%)")
        print(f"   ❌ Отрицательных: {negative} ({negative/total_trades*100:.1f}%)")
        print(f"   ⚪ Нулевых: {zero} ({zero/total_trades*100:.1f}%)")
        print(f"   🎯 Win Rate: {positive/total_trades*100:.2f}%")

        # PnL статистика
        total_pnl = df["net_pnl"].sum()
        avg_pnl = df["net_pnl"].mean()
        median_pnl = df["net_pnl"].median()

        print(f"\n💰 PnL СТАТИСТИКА:")
        print(f"   Общий PnL: ${total_pnl:+.4f} USDT")
        print(f"   Средний PnL: ${avg_pnl:+.4f} USDT")
        print(f"   Медианный PnL: ${median_pnl:+.4f} USDT")

        if positive > 0:
            avg_profit = df[df["net_pnl"] > 0]["net_pnl"].mean()
            print(f"   📈 Средняя прибыль: ${avg_profit:+.4f} USDT")

        if negative > 0:
            avg_loss = df[df["net_pnl"] < 0]["net_pnl"].mean()
            print(f"   📉 Средний убыток: ${avg_loss:+.4f} USDT")
            if positive > 0:
                profit_loss_ratio = abs(avg_profit / avg_loss)
                print(f"   📊 Profit/Loss Ratio: {profit_loss_ratio:.2f}")

        # Проблемы с duration
        negative_duration = len(df[df["duration_sec"] < 0])
        zero_duration = len(df[df["duration_sec"] == 0])

        print(f"\n⏱️ ПРОБЛЕМЫ С DURATION:")
        print(
            f"   Отрицательных duration: {negative_duration} ({negative_duration/total_trades*100:.1f}%)"
        )
        print(
            f"   Нулевых duration: {zero_duration} ({zero_duration/total_trades*100:.1f}%)"
        )

        if negative_duration > 0:
            print(f"\n   ⚠️ ПРИМЕРЫ ОТРИЦАТЕЛЬНЫХ DURATION:")
            negative_samples = df[df["duration_sec"] < 0].head(5)
            for _, row in negative_samples.iterrows():
                print(
                    f"      {row['symbol']} {row['side']}: duration={row['duration_sec']:.2f}s, "
                    f"timestamp={row['timestamp']}, reason={row['reason']}"
                )

        # Анализ по причинам закрытия
        print(f"\n🎯 СТАТИСТИКА ПО ПРИЧИНАМ ЗАКРЫТИЯ:")
        reason_stats = (
            df.groupby("reason").agg({"net_pnl": ["count", "sum", "mean"]}).round(4)
        )
        for reason in reason_stats.index:
            count = reason_stats.loc[reason, ("net_pnl", "count")]
            total = reason_stats.loc[reason, ("net_pnl", "sum")]
            avg = reason_stats.loc[reason, ("net_pnl", "mean")]
            print(f"   {reason}:")
            print(f"      Сделок: {int(count)} ({count/total_trades*100:.1f}%)")
            print(f"      Общий PnL: ${total:+.4f} USDT")
            print(f"      Средний PnL: ${avg:+.4f} USDT")

        # Анализ по символам
        print(f"\n📊 СТАТИСТИКА ПО СИМВОЛАМ:")
        symbol_stats = (
            df.groupby("symbol").agg({"net_pnl": ["count", "sum", "mean"]}).round(4)
        )
        for symbol in symbol_stats.index:
            count = symbol_stats.loc[symbol, ("net_pnl", "count")]
            total = symbol_stats.loc[symbol, ("net_pnl", "sum")]
            avg = symbol_stats.loc[symbol, ("net_pnl", "mean")]
            positive_count = len(df[(df["symbol"] == symbol) & (df["net_pnl"] > 0)])
            win_rate = (positive_count / count * 100) if count > 0 else 0
            print(f"   {symbol}:")
            print(f"      Сделок: {int(count)}")
            print(f"      Win Rate: {win_rate:.1f}%")
            print(f"      Общий PnL: ${total:+.4f} USDT")
            print(f"      Средний PnL: ${avg:+.4f} USDT")

        # Временной анализ
        if "timestamp" in df.columns and not df["timestamp"].isna().all():
            df["date"] = df["timestamp"].dt.date
            daily_stats = (
                df.groupby("date").agg({"net_pnl": ["count", "sum", "mean"]}).round(4)
            )

            print(f"\n📅 СТАТИСТИКА ПО ДНЯМ:")
            for date in daily_stats.index:
                count = daily_stats.loc[date, ("net_pnl", "count")]
                total = daily_stats.loc[date, ("net_pnl", "sum")]
                avg = daily_stats.loc[date, ("net_pnl", "mean")]
                print(f"   {date}:")
                print(f"      Сделок: {int(count)}")
                print(f"      Общий PnL: ${total:+.4f} USDT")
                print(f"      Средний PnL: ${avg:+.4f} USDT")

        return df

    def analyze_logs(self):
        """Анализ лог файлов"""
        print("\n" + "=" * 80)
        print("📋 АНАЛИЗ ЛОГОВ")
        print("=" * 80)

        # Ищем основные лог файлы
        log_files = list(self.extracted_path.glob("*.log"))
        zip_logs = list(self.extracted_path.glob("*.log.zip"))

        print(f"\n📁 Найдено лог файлов: {len(log_files)}")
        print(f"📁 Найдено заархивированных логов: {len(zip_logs)}")

        # Анализируем errors log
        errors_log = self.extracted_path / "errors_*.log"
        error_files = list(self.extracted_path.glob("errors_*.log"))
        if error_files:
            print(f"\n❌ ОШИБКИ В ЛОГАХ:")
            for error_file in error_files[:5]:  # Первые 5 файлов
                try:
                    with open(error_file, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        if lines:
                            print(f"   {error_file.name}: {len(lines)} строк")
                            # Показываем первые ошибки
                            for line in lines[:3]:
                                if line.strip():
                                    print(f"      {line.strip()[:100]}")
                except Exception as e:
                    print(f"   ⚠️ Ошибка чтения {error_file.name}: {e}")


async def fetch_exchange_data(start_date: datetime, end_date: datetime):
    """Получение данных с биржи"""
    print("\n" + "=" * 80)
    print("🔌 ПОЛУЧЕНИЕ ДАННЫХ С БИРЖИ")
    print("=" * 80)

    try:
        config = load_config()
        okx_config = config.get_okx_config()
        client = OKXFuturesClient(okx_config)

        print("✅ Подключение к OKX...")

        # Получаем баланс
        balance = await client.get_balance()
        print(f"\n💰 ТЕКУЩИЙ БАЛАНС: ${balance:.4f} USDT")

        # Получаем открытые позиции
        positions = await client.get_positions()
        print(f"\n📊 ОТКРЫТЫЕ ПОЗИЦИИ: {len(positions)}")
        for pos in positions:
            print(
                f"   {pos.get('instId', 'N/A')}: {pos.get('pos', '0')} "
                f"(PnL: {pos.get('upl', '0')} USDT)"
            )

        # Получаем историю ордеров
        print(f"\n📋 ПОЛУЧЕНИЕ ИСТОРИИ ОРДЕРОВ...")
        print(f"   Период: {start_date.date()} - {end_date.date()}")

        # OKX API для получения истории ордеров
        # Нужно использовать правильный endpoint
        # await client.get_order_history(...)

        await client.close()

    except Exception as e:
        print(f"❌ Ошибка получения данных с биржи: {e}")
        import traceback

        traceback.print_exc()


def main():
    archive_path = Path(
        r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-06_15-58-40.zip"
    )

    if not archive_path.exists():
        print(f"❌ Архив не найден: {archive_path}")
        return

    analyzer = LogAnalyzer(archive_path)

    # Распаковка
    analyzer.extract_archive()

    # Загрузка сделок
    analyzer.load_trades_csv()

    # Анализ сделок
    df = analyzer.analyze_trades()

    # Анализ логов
    analyzer.analyze_logs()

    # Получение данных с биржи
    if df is not None and not df.empty:
        start_date = df["timestamp"].min()
        end_date = df["timestamp"].max()
        print(f"\n📅 Период торговли: {start_date} - {end_date}")

        # Запрашиваем данные с биржи
        asyncio.run(fetch_exchange_data(start_date, end_date))

    print("\n" + "=" * 80)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 80)


if __name__ == "__main__":
    main()
