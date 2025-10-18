"""
Скрипт для анализа результатов торговли из CSV.

Использование:
    python scripts/analyze_trades.py logs/trades_2025-10-18.csv
    python scripts/analyze_trades.py logs/trades_*.csv  # Все файлы
"""

import sys
from pathlib import Path

import pandas as pd


def analyze_trades(csv_path: str):
    """
    Анализ trades.csv файла.

    Args:
        csv_path: Путь к CSV файлу
    """
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 АНАЛИЗ: {csv_path}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    try:
        df = pd.read_csv(csv_path)

        if len(df) == 0:
            print("⚠️ Файл пустой - сделок нет")
            return

        # Основная статистика
        total_trades = len(df)
        winning_trades = len(df[df["net_pnl"] > 0])
        losing_trades = len(df[df["net_pnl"] < 0])
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

        total_pnl = df["net_pnl"].sum()
        total_commission = df["commission"].sum()

        avg_win = df[df["net_pnl"] > 0]["net_pnl"].mean() if winning_trades > 0 else 0
        avg_loss = df[df["net_pnl"] < 0]["net_pnl"].mean() if losing_trades > 0 else 0

        best_trade = df["net_pnl"].max()
        worst_trade = df["net_pnl"].min()

        avg_duration = df["duration_sec"].mean()

        # Распределение по reason
        reason_counts = df["reason"].value_counts()

        print(f"\n📈 ОСНОВНАЯ СТАТИСТИКА:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Winning: {winning_trades} ({winning_trades/total_trades*100:.1f}%)")
        print(f"   Losing: {losing_trades} ({losing_trades/total_trades*100:.1f}%)")
        print(f"   Win Rate: {win_rate:.2f}%")

        print(f"\n💰 PnL:")
        print(f"   Total PnL: ${total_pnl:.2f}")
        print(f"   Total Commission: -${total_commission:.2f}")
        print(f"   Avg Win: ${avg_win:.2f}")
        print(f"   Avg Loss: ${avg_loss:.2f}")
        print(f"   Best Trade: ${best_trade:.2f}")
        print(f"   Worst Trade: ${worst_trade:.2f}")

        print(f"\n⏱️ ВРЕМЯ:")
        print(f"   Avg Duration: {avg_duration:.0f}s ({avg_duration/60:.1f} min)")
        print(f"   Min Duration: {df['duration_sec'].min():.0f}s")
        print(f"   Max Duration: {df['duration_sec'].max():.0f}s")

        print(f"\n📊 РАСПРЕДЕЛЕНИЕ ПО ПРИЧИНАМ:")
        for reason, count in reason_counts.items():
            print(f"   {reason}: {count} ({count/total_trades*100:.1f}%)")

        # Profit Harvesting статистика
        harvesting_trades = len(df[df["reason"] == "profit_harvesting"])
        if harvesting_trades > 0:
            harvesting_pnl = df[df["reason"] == "profit_harvesting"]["net_pnl"].sum()
            print(f"\n💰 PROFIT HARVESTING:")
            print(
                f"   Trades: {harvesting_trades} ({harvesting_trades/total_trades*100:.1f}%)"
            )
            print(f"   Total PnL: ${harvesting_pnl:.2f}")
            print(f"   Avg PnL: ${harvesting_pnl/harvesting_trades:.2f}")

        # Распределение по символам
        print(f"\n📊 ПО СИМВОЛАМ:")
        for symbol in df["symbol"].unique():
            symbol_df = df[df["symbol"] == symbol]
            symbol_wins = len(symbol_df[symbol_df["net_pnl"] > 0])
            symbol_total = len(symbol_df)
            symbol_wr = (symbol_wins / symbol_total * 100) if symbol_total > 0 else 0
            symbol_pnl = symbol_df["net_pnl"].sum()

            print(
                f"   {symbol}: {symbol_total} trades, WR: {symbol_wr:.1f}%, PnL: ${symbol_pnl:.2f}"
            )

        # Распределение по side
        print(f"\n📊 ПО НАПРАВЛЕНИЮ:")
        for side in df["side"].unique():
            side_df = df[df["side"] == side]
            side_wins = len(side_df[side_df["net_pnl"] > 0])
            side_total = len(side_df)
            side_wr = (side_wins / side_total * 100) if side_total > 0 else 0
            side_pnl = side_df["net_pnl"].sum()

            print(
                f"   {side.upper()}: {side_total} trades, WR: {side_wr:.1f}%, PnL: ${side_pnl:.2f}"
            )

        print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # ВЫВОД
        print(f"\n🎯 ИТОГ:")
        if win_rate >= 50 and total_pnl > 10:
            print(f"   ✅ ОТЛИЧНО! Win Rate {win_rate:.1f}%, PnL ${total_pnl:.2f}")
            print(f"   Рекомендация: Продолжать с текущими параметрами")
        elif win_rate >= 40:
            print(f"   ⚠️ СРЕДНЕ. Win Rate {win_rate:.1f}%, PnL ${total_pnl:.2f}")
            print(f"   Рекомендация: Попробовать другие параметры TP/SL")
        else:
            print(f"   ❌ ПЛОХО. Win Rate {win_rate:.1f}%, PnL ${total_pnl:.2f}")
            print(f"   Рекомендация: Откатить изменения или пересмотреть стратегию")

        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    except FileNotFoundError:
        print(f"❌ Файл не найден: {csv_path}")
    except Exception as e:
        print(f"❌ Ошибка анализа: {e}")


def compare_variants(csv_a: str, csv_b: str, csv_c: str = None):
    """
    Сравнение результатов A/B/C теста.

    Args:
        csv_a: Путь к CSV варианта A
        csv_b: Путь к CSV варианта B
        csv_c: Путь к CSV варианта C (опционально)
    """
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 СРАВНЕНИЕ ВАРИАНТОВ A/B/C")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    variants = [("A", csv_a), ("B", csv_b)]
    if csv_c:
        variants.append(("C", csv_c))

    results = []

    for name, path in variants:
        try:
            df = pd.read_csv(path)

            if len(df) == 0:
                continue

            total_trades = len(df)
            win_rate = (len(df[df["net_pnl"] > 0]) / total_trades) * 100
            total_pnl = df["net_pnl"].sum()
            avg_trade = df["net_pnl"].mean()
            avg_duration = df["duration_sec"].mean()

            results.append(
                {
                    "variant": name,
                    "trades": total_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "avg_trade": avg_trade,
                    "avg_duration": avg_duration,
                }
            )

        except Exception as e:
            print(f"⚠️ Ошибка загрузки варианта {name}: {e}")

    # Сравнительная таблица
    print("| Вариант | Trades | Win Rate | Total PnL | Avg Trade | Avg Time |")
    print("|---------|--------|----------|-----------|-----------|----------|")

    for r in results:
        print(
            f"| {r['variant']: <7} | {r['trades']: <6} | "
            f"{r['win_rate']:>6.1f}% | ${r['total_pnl']:>8.2f} | "
            f"${r['avg_trade']:>8.2f} | {r['avg_duration']/60:>6.1f} min |"
        )

    print()

    # Определение лучшего
    if results:
        best_wr = max(results, key=lambda x: x["win_rate"])
        best_pnl = max(results, key=lambda x: x["total_pnl"])

        print(
            f"🏆 Лучший Win Rate: Вариант {best_wr['variant']} ({best_wr['win_rate']:.1f}%)"
        )
        print(
            f"💰 Лучший Total PnL: Вариант {best_pnl['variant']} (${best_pnl['total_pnl']:.2f})"
        )

        if best_wr["variant"] == best_pnl["variant"]:
            print(
                f"\n✅ ПОБЕДИТЕЛЬ: Вариант {best_wr['variant']} (лучший по обоим метрикам!)"
            )
        else:
            print(f"\n⚠️ Разные победители - выбери приоритет (WinRate или PnL)")

    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/analyze_trades.py <csv_file>")
        print("  python scripts/analyze_trades.py logs/trades_2025-10-18.csv")
        print()
        print("Compare variants:")
        print("  python scripts/analyze_trades.py --compare <csv_a> <csv_b> [csv_c]")
        sys.exit(1)

    if sys.argv[1] == "--compare":
        if len(sys.argv) < 4:
            print("❌ Нужно минимум 2 файла для сравнения")
            sys.exit(1)

        csv_a = sys.argv[2]
        csv_b = sys.argv[3]
        csv_c = sys.argv[4] if len(sys.argv) > 4 else None

        compare_variants(csv_a, csv_b, csv_c)
    else:
        csv_path = sys.argv[1]
        analyze_trades(csv_path)


if __name__ == "__main__":
    main()
