#!/usr/bin/env python3
"""
Анализ качества сделок из CSV файла
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


def analyze_trades(csv_path: str):
    """Анализ сделок из CSV"""
    try:
        df = pd.read_csv(csv_path)

        if len(df) == 0:
            print("❌ CSV файл пустой")
            return

        # Базовая статистика
        total_trades = len(df)
        positive_trades = len(df[df["net_pnl"] > 0])
        negative_trades = len(df[df["net_pnl"] < 0])
        zero_trades = len(df[df["net_pnl"] == 0])

        win_rate = (positive_trades / total_trades * 100) if total_trades > 0 else 0

        # PnL статистика
        total_pnl = df["net_pnl"].sum()
        avg_pnl = df["net_pnl"].mean()
        median_pnl = df["net_pnl"].median()
        max_profit = df["net_pnl"].max()
        max_loss = df["net_pnl"].min()

        # Статистика по прибыльным сделкам
        profitable_df = df[df["net_pnl"] > 0]
        avg_profit = profitable_df["net_pnl"].mean() if len(profitable_df) > 0 else 0
        total_profit = profitable_df["net_pnl"].sum() if len(profitable_df) > 0 else 0

        # Статистика по убыточным сделкам
        losing_df = df[df["net_pnl"] < 0]
        avg_loss = losing_df["net_pnl"].mean() if len(losing_df) > 0 else 0
        total_loss = losing_df["net_pnl"].sum() if len(losing_df) > 0 else 0

        # Статистика по причинам закрытия
        reason_stats = (
            df.groupby("reason").agg({"net_pnl": ["count", "sum", "mean"]}).round(4)
        )

        # Статистика по символам
        symbol_stats = (
            df.groupby("symbol").agg({"net_pnl": ["count", "sum", "mean"]}).round(4)
        )

        # Статистика по времени удержания
        if "duration_sec" in df.columns:
            df["duration_min"] = df["duration_sec"] / 60.0
            avg_duration = df["duration_min"].mean()
            median_duration = df["duration_min"].median()
        else:
            avg_duration = 0
            median_duration = 0

        # Вывод результатов
        print("=" * 80)
        print("📊 АНАЛИЗ КАЧЕСТВА СДЕЛОК")
        print("=" * 80)
        print(f"\n📁 Файл: {csv_path}")
        print(f"📅 Дата анализа: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        print("\n" + "=" * 80)
        print("📈 ОБЩАЯ СТАТИСТИКА")
        print("=" * 80)
        print(f"   Всего сделок: {total_trades}")
        print(
            f"   ✅ Положительных: {positive_trades} ({positive_trades/total_trades*100:.1f}%)"
        )
        print(
            f"   ❌ Отрицательных: {negative_trades} ({negative_trades/total_trades*100:.1f}%)"
        )
        print(f"   ⚪ Нулевых: {zero_trades} ({zero_trades/total_trades*100:.1f}%)")
        print(f"   🎯 Win Rate: {win_rate:.2f}%")

        print("\n" + "=" * 80)
        print("💰 PnL СТАТИСТИКА")
        print("=" * 80)
        print(f"   Общий PnL: ${total_pnl:.4f} USDT")
        print(f"   Средний PnL: ${avg_pnl:.4f} USDT")
        print(f"   Медианный PnL: ${median_pnl:.4f} USDT")
        print(f"   Максимальная прибыль: ${max_profit:.4f} USDT")
        print(f"   Максимальный убыток: ${max_loss:.4f} USDT")

        if len(profitable_df) > 0:
            print(f"\n   📈 ПРИБЫЛЬНЫЕ СДЕЛКИ:")
            print(f"      Средняя прибыль: ${avg_profit:.4f} USDT")
            print(f"      Общая прибыль: ${total_profit:.4f} USDT")

        if len(losing_df) > 0:
            print(f"\n   📉 УБЫТОЧНЫЕ СДЕЛКИ:")
            print(f"      Средний убыток: ${avg_loss:.4f} USDT")
            print(f"      Общий убыток: ${total_loss:.4f} USDT")

        if len(profitable_df) > 0 and len(losing_df) > 0:
            profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0
            print(f"\n   📊 Profit/Loss Ratio: {profit_loss_ratio:.2f}")

        if avg_duration > 0:
            print("\n" + "=" * 80)
            print("⏱️  ВРЕМЯ УДЕРЖАНИЯ")
            print("=" * 80)
            print(f"   Среднее время: {avg_duration:.2f} минут")
            print(f"   Медианное время: {median_duration:.2f} минут")

        print("\n" + "=" * 80)
        print("🎯 СТАТИСТИКА ПО ПРИЧИНАМ ЗАКРЫТИЯ")
        print("=" * 80)
        for reason in reason_stats.index:
            count = reason_stats.loc[reason, ("net_pnl", "count")]
            total = reason_stats.loc[reason, ("net_pnl", "sum")]
            avg = reason_stats.loc[reason, ("net_pnl", "mean")]
            print(f"   {reason}:")
            print(f"      Сделок: {int(count)}")
            print(f"      Общий PnL: ${total:.4f} USDT")
            print(f"      Средний PnL: ${avg:.4f} USDT")

        print("\n" + "=" * 80)
        print("📊 СТАТИСТИКА ПО СИМВОЛАМ")
        print("=" * 80)
        for symbol in symbol_stats.index:
            count = symbol_stats.loc[symbol, ("net_pnl", "count")]
            total = symbol_stats.loc[symbol, ("net_pnl", "sum")]
            avg = symbol_stats.loc[symbol, ("net_pnl", "mean")]
            symbol_df = df[df["symbol"] == symbol]
            symbol_win_rate = (
                (len(symbol_df[symbol_df["net_pnl"] > 0]) / len(symbol_df) * 100)
                if len(symbol_df) > 0
                else 0
            )
            print(f"   {symbol}:")
            print(f"      Сделок: {int(count)}")
            print(f"      Win Rate: {symbol_win_rate:.1f}%")
            print(f"      Общий PnL: ${total:.4f} USDT")
            print(f"      Средний PnL: ${avg:.4f} USDT")

        print("\n" + "=" * 80)
        print("⚠️  ВЫВОДЫ")
        print("=" * 80)
        if win_rate < 50:
            print(
                f"   ❌ Win Rate ниже 50% ({win_rate:.1f}%) - больше убыточных сделок!"
            )
        elif win_rate < 60:
            print(f"   ⚠️  Win Rate ниже 60% ({win_rate:.1f}%) - можно улучшить")
        else:
            print(f"   ✅ Win Rate хороший ({win_rate:.1f}%)")

        if total_pnl < 0:
            print(
                f"   ❌ Общий PnL отрицательный (${total_pnl:.4f} USDT) - бот в убытке!"
            )
        elif total_pnl == 0:
            print(f"   ⚠️  Общий PnL нулевой - нет прибыли")
        else:
            print(f"   ✅ Общий PnL положительный (${total_pnl:.4f} USDT)")

        if len(profitable_df) > 0 and len(losing_df) > 0:
            if abs(avg_loss) > avg_profit:
                print(
                    f"   ❌ Средний убыток (${abs(avg_loss):.4f}) больше средней прибыли (${avg_profit:.4f}) - нужно улучшить стоп-лоссы!"
                )
            elif abs(avg_loss) == avg_profit:
                print(
                    f"   ⚠️  Средний убыток равен средней прибыли - нужно улучшить risk/reward"
                )
            else:
                print(
                    f"   ✅ Средняя прибыль (${avg_profit:.4f}) больше среднего убытка (${abs(avg_loss):.4f})"
                )

        print("\n" + "=" * 80)

    except Exception as e:
        print(f"❌ Ошибка анализа: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    csv_path = "logs/trades_2025-12-04.csv"
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]

    if not Path(csv_path).exists():
        print(f"❌ Файл не найден: {csv_path}")
        sys.exit(1)

    analyze_trades(csv_path)
