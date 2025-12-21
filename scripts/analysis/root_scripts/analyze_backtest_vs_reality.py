"""
Анализ расхождений между backtest и реальными результатами.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


def analyze_real_trades():
    """Анализ реальных сделок из trades.csv"""
    trades_file = Path("logs/trades_2025-12-17.csv")
    if not trades_file.exists():
        return None

    trades = []
    with open(trades_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)

    profitable = [t for t in trades if float(t["net_pnl"]) > 0]
    losing = [t for t in trades if float(t["net_pnl"]) <= 0]

    total_pnl = sum(float(t["net_pnl"]) for t in trades)
    total_commission = sum(float(t["commission"]) for t in trades)

    # Группировка по причинам закрытия
    reasons = {}
    for t in trades:
        reason = t["reason"]
        if reason not in reasons:
            reasons[reason] = {"count": 0, "pnl": 0.0, "trades": []}
        reasons[reason]["count"] += 1
        reasons[reason]["pnl"] += float(t["net_pnl"])
        reasons[reason]["trades"].append(t)

    return {
        "total_trades": len(trades),
        "profitable": len(profitable),
        "losing": len(losing),
        "win_rate": len(profitable) / len(trades) * 100 if trades else 0,
        "total_pnl": total_pnl,
        "total_commission": total_commission,
        "avg_pnl": total_pnl / len(trades) if trades else 0,
        "reasons": reasons,
        "trades": trades,
    }


def create_comparison_report():
    """Создание отчета сравнения backtest vs реальность"""

    real_data = analyze_real_trades()
    if not real_data:
        print("❌ Не найдены реальные сделки")
        return

    # Данные из backtest кими
    backtest_data = {
        "total_trades": 21,
        "profitable": 14,
        "losing": 7,
        "win_rate": 66.7,
        "total_pnl_pct": 7.98,  # В процентах
        "max_drawdown": -1.2,
        "profit_factor": 1.89,
    }

    print("=" * 80)
    print("📊 СРАВНЕНИЕ BACKTEST vs РЕАЛЬНОСТЬ")
    print("=" * 80)
    print()

    print("🔵 BACKTEST (кими):")
    print(f"   Всего сделок: {backtest_data['total_trades']}")
    print(
        f"   Прибыльных: {backtest_data['profitable']} ({backtest_data['win_rate']:.1f}%)"
    )
    print(f"   Убыточных: {backtest_data['losing']}")
    print(f"   Итоговый PnL: +{backtest_data['total_pnl_pct']:.2f}%")
    print(f"   Макс. просадка: {backtest_data['max_drawdown']:.2f}%")
    print(f"   Profit Factor: {backtest_data['profit_factor']:.2f}")
    print()

    print("🔴 РЕАЛЬНОСТЬ (trades.csv):")
    print(f"   Всего сделок: {real_data['total_trades']}")
    print(f"   Прибыльных: {real_data['profitable']} ({real_data['win_rate']:.1f}%)")
    print(f"   Убыточных: {real_data['losing']}")
    print(f"   Итоговый PnL: {real_data['total_pnl']:.2f} USDT")
    print(f"   Комиссии: {real_data['total_commission']:.2f} USDT")
    print(f"   Средний PnL: {real_data['avg_pnl']:.2f} USDT")
    print()

    print("📈 АНАЛИЗ ПО ПРИЧИНАМ ЗАКРЫТИЯ:")
    for reason, data in real_data["reasons"].items():
        avg_pnl = data["pnl"] / data["count"] if data["count"] > 0 else 0
        print(
            f"   {reason}: {data['count']} сделок, PnL: {data['pnl']:.2f} USDT (средний: {avg_pnl:.2f} USDT)"
        )
    print()

    print("⚠️ ВОЗМОЖНЫЕ ПРИЧИНЫ РАСХОЖДЕНИЙ:")
    print()
    print("1. SLIPPAGE (проскальзывание):")
    print("   - Backtest использует close цену свечи")
    print("   - В реальности fill price может отличаться на 0.1-0.5%")
    print("   - Особенно критично для market ордеров")
    print()
    print("2. ИСПОЛНЕНИЕ ОРДЕРОВ:")
    print("   - Backtest предполагает мгновенное исполнение")
    print("   - В реальности могут быть задержки (сеть, биржа)")
    print("   - Limit ордера могут не исполниться вовсе")
    print()
    print("3. MARKPX vs FILL PRICE:")
    print("   - Backtest использует close (или markPx)")
    print("   - В реальности fill price для market ордеров может быть хуже")
    print("   - Разница особенно заметна при высокой волатильности")
    print()
    print("4. РЕЖИМЫ РЫНКА:")
    print("   - Backtest может неправильно определять режим (ranging/trending)")
    print("   - Неправильный режим → неправильные TP/SL")
    print()
    print("5. ФИЛЬТРЫ:")
    print("   - В backtest могут не учитываться все фильтры:")
    print("     * Correlation filter (блокирует коррелированные позиции)")
    print("     * Funding rate filter")
    print("     * Liquidity filter")
    print("     * Order flow filter")
    print()
    print("6. ЧАСТИЧНЫЕ ИСПОЛНЕНИЯ:")
    print("   - Backtest предполагает полное исполнение")
    print("   - В реальности ордер может исполниться частично")
    print()
    print("7. КОМИССИИ:")
    print("   - Backtest: 0.02% maker × 2 × leverage = 0.2%")
    print("   - Реальность: может быть taker (0.05%) если limit не исполнился")
    print()
    print("8. ПСИХОЛОГИЧЕСКИЕ ФАКТОРЫ:")
    print("   - В backtest нет эмоций")
    print("   - В реальности могут быть задержки из-за перегрузки системы")
    print()

    print("✅ РЕКОМЕНДАЦИИ ДЛЯ УЛУЧШЕНИЯ BACKTEST:")
    print()
    print("1. Добавить slippage моделирование:")
    print("   - Для market ордеров: +0.1-0.3% к цене входа/выхода")
    print("   - Для limit ордеров: проверка исполнения по best_bid/best_ask")
    print()
    print("2. Учитывать задержки исполнения:")
    print("   - Добавить случайную задержку 0.5-2 секунды")
    print("   - Проверять, что цена не ушла за это время")
    print()
    print("3. Использовать реальные fill prices:")
    print("   - Если есть логи ордеров, использовать их")
    print("   - Иначе моделировать на основе spread и объема")
    print()
    print("4. Тестировать на более длинном периоде:")
    print("   - 1 день может быть нерепрезентативным")
    print("   - Рекомендуется минимум 7-30 дней")
    print()
    print("5. Учитывать все фильтры:")
    print("   - Correlation filter")
    print("   - Funding rate filter")
    print("   - Liquidity filter")
    print("   - Order flow filter")
    print()
    print("6. Моделировать частичные исполнения:")
    print("   - Проверять ликвидность на момент входа")
    print("   - Если ликвидность низкая - частичное исполнение")
    print()

    # Сохраняем отчет
    report = {
        "backtest": backtest_data,
        "reality": {
            "total_trades": real_data["total_trades"],
            "profitable": real_data["profitable"],
            "losing": real_data["losing"],
            "win_rate": real_data["win_rate"],
            "total_pnl_usd": real_data["total_pnl"],
            "total_commission": real_data["total_commission"],
            "avg_pnl": real_data["avg_pnl"],
            "reasons": {
                k: {"count": v["count"], "pnl": v["pnl"]}
                for k, v in real_data["reasons"].items()
            },
        },
        "discrepancies": {
            "win_rate_diff": backtest_data["win_rate"] - real_data["win_rate"],
            "note": "Backtest показывает лучшие результаты из-за идеальных условий (нет slippage, мгновенное исполнение, close цена)",
        },
    }

    with open("backtest_vs_reality_comparison.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("=" * 80)
    print("✅ Отчет сохранен в backtest_vs_reality_comparison.json")
    print("=" * 80)


if __name__ == "__main__":
    create_comparison_report()
