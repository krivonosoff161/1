"""
Тест для анализа причин закрытия позиций
Определяет, почему так много стоп-лоссов и мало тейк-профитов
"""

import collections
import csv
from typing import Dict, List


def analyze_close_reasons(log_file_path: str) -> Dict:
    """Анализ причин закрытия позиций"""

    print("🔍 АНАЛИЗ ПРИЧИН ЗАКРЫТИЯ ПОЗИЦИЙ")
    print("=" * 50)

    # Читаем данные
    positions = []
    with open(log_file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["record_type"] in ["positions_open", "trades"]:
                positions.append(row)

    if not positions:
        print("❌ Нет данных о позициях")
        return {}

    total_positions = len(positions)
    print(f"📈 Всего позиций: {total_positions}")

    # Анализ причин закрытия
    close_reasons = collections.Counter(
        row.get("reason", "unknown") for row in positions
    )
    print(f"📋 Причины закрытия: {dict(close_reasons)}")

    # Анализ P&L
    pnl_values = []
    for pos in positions:
        try:
            pnl = float(pos.get("net_pnl", 0))
            pnl_values.append(pnl)
        except (ValueError, TypeError):
            continue

    if pnl_values:
        print(
            f"💰 P&L: min={min(pnl_values):.2f}, max={max(pnl_values):.2f}, avg={sum(pnl_values)/len(pnl_values):.2f}"
        )

    # Анализ по символам
    symbols = collections.Counter(row["symbol"] for row in positions)
    print(f"📊 Позиции по символам: {dict(symbols)}")

    # Детальный анализ по причинам закрытия
    print(f"\n📊 ДЕТАЛЬНЫЙ АНАЛИЗ:")
    for reason, count in close_reasons.items():
        reason_positions = [p for p in positions if p.get("reason") == reason]
        reason_pnl = [
            float(p.get("net_pnl", 0)) for p in reason_positions if p.get("net_pnl")
        ]

        if reason_pnl:
            avg_pnl = sum(reason_pnl) / len(reason_pnl)
            print(f"   {reason}: {count} позиций, средний P&L: {avg_pnl:.2f}")
        else:
            print(f"   {reason}: {count} позиций")

    # Анализ SL vs TP соотношения
    sl_count = close_reasons.get("sl_reached", 0) + close_reasons.get("stop_loss", 0)
    tp_count = close_reasons.get("tp_reached", 0) + close_reasons.get("take_profit", 0)

    if sl_count + tp_count > 0:
        sl_ratio = sl_count / (sl_count + tp_count) * 100
        tp_ratio = tp_count / (sl_count + tp_count) * 100

        print(f"\n🎯 СООТНОШЕНИЕ SL/TP:")
        print(f"   Stop Loss: {sl_count} ({sl_ratio:.1f}%)")
        print(f"   Take Profit: {tp_count} ({tp_ratio:.1f}%)")

        if sl_ratio > 70:
            print(f"   ⚠️ КРИТИЧНО: {sl_ratio:.1f}% позиций закрываются по SL!")
            print(f"   💡 Решение: Увеличить TP/SL соотношение или улучшить входы")

    # Анализ по символам
    print(f"\n📊 АНАЛИЗ ПО СИМВОЛАМ:")
    for symbol in symbols:
        symbol_positions = [p for p in positions if p["symbol"] == symbol]
        symbol_reasons = collections.Counter(
            p.get("reason", "unknown") for p in symbol_positions
        )
        print(f"   {symbol}: {dict(symbol_reasons)}")

    # Рекомендации
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    if sl_ratio > 50:
        print(f"   • Основная проблема: слишком много SL ({sl_ratio:.1f}%)")
        print(f"   • Решение: оптимизировать TP/SL соотношение")
        print(f"   • Альтернатива: улучшить качество входов")

    return {
        "total_positions": total_positions,
        "close_reasons": dict(close_reasons),
        "sl_ratio": sl_ratio if "sl_ratio" in locals() else 0,
        "tp_ratio": tp_ratio if "tp_ratio" in locals() else 0,
        "symbols_analysis": {
            symbol: dict(
                collections.Counter(
                    p.get("reason", "unknown")
                    for p in positions
                    if p["symbol"] == symbol
                )
            )
            for symbol in symbols
        },
    }


if __name__ == "__main__":
    from pathlib import Path

    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        analyze_close_reasons(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")
