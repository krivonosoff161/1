#!/usr/bin/env python3
"""
Полный анализ сессии бота 29.11.2025
"""
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

# Путь к архиву
archive_path = Path("logs/futures/archived/logs_2025-11-29_21-49-18")
trades_file = archive_path / "trades_2025-11-29.csv"
log_file = archive_path / "futures_main_2025-11-29.log"

print("=" * 80)
print("ПОЛНЫЙ АНАЛИЗ СЕССИИ БОТА 29.11.2025")
print("=" * 80)

# 1. Анализ trades.csv
print("\n" + "=" * 80)
print("1. СТАТИСТИКА ЗАКРЫТИЙ ПОЗИЦИЙ")
print("=" * 80)

if trades_file.exists():
    df = pd.read_csv(trades_file)

    print(f"\nВсего закрытий: {len(df)}")
    print(f"\nПо причинам закрытия:")
    print(df["reason"].value_counts())

    print(f"\nОбщая статистика:")
    print(f"  Общий Net PnL: {df['net_pnl'].sum():.2f} USDT")
    print(
        f"  Прибыльных: {len(df[df['net_pnl'] > 0])} ({len(df[df['net_pnl'] > 0])/len(df)*100:.1f}%)"
    )
    print(
        f"  Убыточных: {len(df[df['net_pnl'] < 0])} ({len(df[df['net_pnl'] < 0])/len(df)*100:.1f}%)"
    )
    print(f"  Безубыточных: {len(df[df['net_pnl'] == 0])}")

    print(f"\nСредняя длительность позиций:")
    print(
        f"  Средняя: {df['duration_sec'].mean():.1f}с ({df['duration_sec'].mean()/60:.1f} мин)"
    )
    print(
        f"  Медиана: {df['duration_sec'].median():.1f}с ({df['duration_sec'].median()/60:.1f} мин)"
    )
    print(
        f"  Минимум: {df['duration_sec'].min():.1f}с ({df['duration_sec'].min()/60:.1f} мин)"
    )
    print(
        f"  Максимум: {df['duration_sec'].max():.1f}с ({df['duration_sec'].max()/60:.1f} мин)"
    )

    print(f"\nPnL по причинам закрытия:")
    pnl_by_reason = df.groupby("reason")["net_pnl"].agg(["sum", "mean", "count"])
    print(pnl_by_reason)

    print(f"\nТоп-5 прибыльных позиций:")
    top_profitable = df.nlargest(5, "net_pnl")[
        ["symbol", "side", "net_pnl", "reason", "duration_sec"]
    ]
    for idx, row in top_profitable.iterrows():
        print(
            f"  {row['symbol']} {row['side']}: {row['net_pnl']:.2f} USDT ({row['reason']}, {row['duration_sec']/60:.1f} мин)"
        )

    print(f"\nТоп-5 убыточных позиций:")
    top_losses = df.nsmallest(5, "net_pnl")[
        ["symbol", "side", "net_pnl", "reason", "duration_sec"]
    ]
    for idx, row in top_losses.iterrows():
        print(
            f"  {row['symbol']} {row['side']}: {row['net_pnl']:.2f} USDT ({row['reason']}, {row['duration_sec']/60:.1f} мин)"
        )

    print(f"\nСтатистика по символам:")
    symbol_stats = df.groupby("symbol").agg(
        {"net_pnl": ["sum", "mean", "count"], "duration_sec": "mean"}
    )
    print(symbol_stats)
else:
    print(f"❌ Файл {trades_file} не найден!")

# 2. Анализ логов - проблемы с Profit Harvesting
print("\n" + "=" * 80)
print("2. АНАЛИЗ ПРОБЛЕМ С PROFIT HARVESTING")
print("=" * 80)

if log_file.exists():
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Поиск всех случаев, когда PH не сработал
    ph_failed_pattern = (
        r"❌ PH для (\w+-USDT): (Прибыль недостаточна|Превышен time_limit)"
    )
    ph_failed_matches = re.findall(ph_failed_pattern, content)

    ph_failed_by_reason = defaultdict(int)
    ph_failed_by_symbol = defaultdict(int)

    for symbol, reason in ph_failed_matches:
        ph_failed_by_reason[reason] += 1
        ph_failed_by_symbol[symbol] += 1

    print(f"\nВсего случаев, когда PH не сработал: {len(ph_failed_matches)}")
    print(f"\nПо причинам:")
    for reason, count in ph_failed_by_reason.items():
        print(f"  {reason}: {count}")

    print(f"\nПо символам:")
    for symbol, count in sorted(
        ph_failed_by_symbol.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {symbol}: {count}")

    # Поиск случаев с отрицательным PnL
    negative_pnl_pattern = (
        r"❌ PH для (\w+-USDT): Прибыль недостаточна \(\$(-?\d+\.\d+) <"
    )
    negative_pnl_matches = re.findall(negative_pnl_pattern, content)

    print(f"\nПозиции с отрицательным PnL при проверке PH:")
    negative_pnl_by_symbol = defaultdict(list)
    for symbol, pnl in negative_pnl_matches:
        negative_pnl_by_symbol[symbol].append(float(pnl))

    for symbol, pnls in negative_pnl_by_symbol.items():
        avg_pnl = sum(pnls) / len(pnls)
        print(f"  {symbol}: средний PnL = ${avg_pnl:.4f} (всего проверок: {len(pnls)})")

    # Поиск случаев превышения time_limit
    time_limit_pattern = (
        r"❌ PH для (\w+-USDT): Превышен time_limit \((\d+\.\d+)с >= 300с\)"
    )
    time_limit_matches = re.findall(time_limit_pattern, content)

    print(f"\nПозиции с превышением time_limit (300с):")
    time_limit_by_symbol = defaultdict(list)
    for symbol, time_sec in time_limit_matches:
        time_limit_by_symbol[symbol].append(float(time_sec))

    for symbol, times in time_limit_by_symbol.items():
        avg_time = sum(times) / len(times)
        print(
            f"  {symbol}: среднее время = {avg_time:.1f}с ({avg_time/60:.1f} мин) (всего проверок: {len(times)})"
        )

# 3. Анализ проблем с peak_profit
print("\n" + "=" * 80)
print("3. АНАЛИЗ ПРОБЛЕМ С PEAK_PROFIT")
print("=" * 80)

if log_file.exists():
    # Поиск всех случаев "Нет peak_profit"
    no_peak_pattern = r"🔍 \[PROFIT_DRAWDOWN\] (\w+-USDT): Нет peak_profit"
    no_peak_matches = re.findall(no_peak_pattern, content)

    print(f"\nВсего случаев 'Нет peak_profit': {len(no_peak_matches)}")

    no_peak_by_symbol = defaultdict(int)
    for symbol in no_peak_matches:
        no_peak_by_symbol[symbol] += 1

    print(f"\nПо символам:")
    for symbol, count in sorted(
        no_peak_by_symbol.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {symbol}: {count} раз")

    # Поиск обновлений peak_profit
    update_peak_pattern = r"🔍 \[UPDATE_PEAK_PROFIT\] (\w+-USDT): Расчет PnL \| gross=\$(-?\d+\.\d+), commission=\$(-?\d+\.\d+), net=\$(-?\d+\.\d+)"
    update_peak_matches = re.findall(update_peak_pattern, content)

    print(f"\nОбновления peak_profit:")
    update_peak_by_symbol = defaultdict(list)
    for symbol, gross, commission, net in update_peak_matches:
        update_peak_by_symbol[symbol].append(float(net))

    for symbol, pnls in update_peak_by_symbol.items():
        positive_pnls = [p for p in pnls if p > 0]
        negative_pnls = [p for p in pnls if p < 0]
        print(f"  {symbol}:")
        print(f"    Всего обновлений: {len(pnls)}")
        print(
            f"    Прибыльных: {len(positive_pnls)} (макс: ${max(positive_pnls) if positive_pnls else 0:.4f})"
        )
        print(
            f"    Убыточных: {len(negative_pnls)} (мин: ${min(negative_pnls) if negative_pnls else 0:.4f})"
        )
        if positive_pnls:
            print(f"    Средняя прибыль: ${sum(positive_pnls)/len(positive_pnls):.4f}")
        if negative_pnls:
            print(f"    Средний убыток: ${sum(negative_pnls)/len(negative_pnls):.4f}")

# 4. Анализ MAX_HOLDING
print("\n" + "=" * 80)
print("4. АНАЛИЗ MAX_HOLDING")
print("=" * 80)

if trades_file.exists():
    max_holding_closes = df[df["reason"] == "max_holding_exceeded"]
    print(f"\nЗакрытий по MAX_HOLDING: {len(max_holding_closes)}")

    if len(max_holding_closes) > 0:
        print(f"\nСредняя длительность позиций, закрытых по MAX_HOLDING:")
        print(
            f"  Средняя: {max_holding_closes['duration_sec'].mean():.1f}с ({max_holding_closes['duration_sec'].mean()/60:.1f} мин)"
        )
        print(
            f"  Медиана: {max_holding_closes['duration_sec'].median():.1f}с ({max_holding_closes['duration_sec'].median()/60:.1f} мин)"
        )

        print(f"\nPnL позиций, закрытых по MAX_HOLDING:")
        print(f"  Общий: {max_holding_closes['net_pnl'].sum():.2f} USDT")
        print(f"  Средний: {max_holding_closes['net_pnl'].mean():.2f} USDT")
        print(
            f"  Прибыльных: {len(max_holding_closes[max_holding_closes['net_pnl'] > 0])}"
        )
        print(
            f"  Убыточных: {len(max_holding_closes[max_holding_closes['net_pnl'] < 0])}"
        )

# 5. Выводы и рекомендации
print("\n" + "=" * 80)
print("5. ВЫВОДЫ И РЕКОМЕНДАЦИИ")
print("=" * 80)

print("\n🔍 ОБНАРУЖЕННЫЕ ПРОБЛЕМЫ:")
print("\n1. PEAK_PROFIT НЕ ОБНОВЛЯЕТСЯ:")
print("   - Все позиции показывают 'Нет peak_profit (peak_profit=0.0)'")
print("   - Причина: позиции никогда не достигают положительного PnL")
print("   - Следствие: Profit Drawdown не может сработать")
print("\n2. PROFIT HARVESTING НЕ СРАБАТЫВАЕТ:")
print("   - Основные причины: отрицательный PnL и превышение time_limit (300с)")
print("   - Позиции часто держатся > 5 минут, превышая time_limit")
print("\n3. МНОГО ЗАКРЫТИЙ ПО MAX_HOLDING:")
print("   - Большинство позиций закрывается по MAX_HOLDING (20 минут)")
print("   - Это означает, что другие механизмы закрытия не срабатывают")

print("\n💡 РЕКОМЕНДАЦИИ:")
print("\n1. ИСПРАВИТЬ ОБНОВЛЕНИЕ PEAK_PROFIT:")
print(
    "   - Обновлять peak_profit даже для убыточных позиций (отслеживать минимальный убыток)"
)
print(
    "   - Или обновлять peak_profit при любом изменении PnL (не только при увеличении)"
)
print("\n2. ОПТИМИЗИРОВАТЬ PH TIME_LIMIT:")
print("   - Увеличить time_limit для ranging режима (с 300с до 600с или больше)")
print("   - Или сделать time_limit адаптивным в зависимости от волатильности")
print("\n3. УЛУЧШИТЬ ОТКРЫТИЕ ПОЗИЦИЙ:")
print("   - Улучшить фильтрацию сигналов для уменьшения количества убыточных позиций")
print("   - Проверить логику определения направления тренда")

print("\n" + "=" * 80)
