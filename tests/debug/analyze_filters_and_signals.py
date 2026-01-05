"""
Анализатор фильтров и сигналов для оптимизации бота
"""

import collections
import csv
from pathlib import Path


def analyze_signals_and_filters(log_file_path: str):
    """Анализ сигналов и фильтров из логов"""

    print("📊 АНАЛИЗ ФИЛЬТРОВ И СИГНАЛОВ")
    print("=" * 50)

    # Читаем данные
    data = []
    with open(log_file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    signals = [row for row in data if row["record_type"] == "signals"]
    trades = [row for row in data if row["record_type"] == "trades"]

    print(f"📈 Всего сигналов: {len(signals)}")
    print(f"💰 Всего сделок: {len(trades)}")
    print(f"📊 Конверсия: {len(trades)/len(signals)*100:.1f}%")

    # Анализ по режимам
    regimes = collections.Counter(row["regime"] for row in signals)
    print(f"🎯 Режимы сигналов: {dict(regimes)}")

    # Анализ причин закрытия
    if trades:
        reasons = collections.Counter(row["reason"] for row in trades)
        print(f"❌ Причины закрытия: {dict(reasons)}")

        # Анализ P&L
        total_pnl = sum(float(row["net_pnl"]) for row in trades)
        win_trades = [row for row in trades if float(row["net_pnl"]) > 0]
        win_rate = len(win_trades) / len(trades) * 100

        print(f"💰 Общий P&L: ${total_pnl:.2f}")
        print(f"📈 Win Rate: {win_rate:.1f}%")

    # Анализ по символам
    symbols_signals = collections.Counter(row["symbol"] for row in signals)
    symbols_trades = collections.Counter(row["symbol"] for row in trades)

    print(f"📊 Сигналы по символам: {dict(symbols_signals)}")
    print(f"💼 Сделки по символам: {dict(symbols_trades)}")

    return {
        "total_signals": len(signals),
        "total_trades": len(trades),
        "conversion_rate": len(trades) / len(signals) * 100,
        "regimes": dict(regimes),
        "close_reasons": dict(reasons) if trades else {},
        "symbols_signals": dict(symbols_signals),
        "symbols_trades": dict(symbols_trades),
    }


if __name__ == "__main__":
    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        analyze_signals_and_filters(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")
