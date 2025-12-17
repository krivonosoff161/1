"""
Анализ логики закрытия позиций: почему маленькие прибыли закрываются, а убытки растут.
"""

import csv
from collections import defaultdict

# Читаем сделки
trades = []
with open("logs/trades_2025-12-17.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        trades.append(row)

# Группируем по причинам
by_reason = defaultdict(list)
for t in trades:
    by_reason[t["reason"]].append(t)

print("=" * 80)
print("АНАЛИЗ ЛОГИКИ ЗАКРЫТИЯ ПОЗИЦИЙ")
print("=" * 80)
print()

# Анализ partial_tp
partial_tp = by_reason["partial_tp"]
if partial_tp:
    pnl_values = [float(t["net_pnl"]) for t in partial_tp]
    print(f"PARTIAL_TP сделки: {len(partial_tp)}")
    print(f"  Средний PnL: {sum(pnl_values)/len(pnl_values):.4f} USDT")
    print(f"  Макс: {max(pnl_values):.4f} USDT")
    print(f"  Мин: {min(pnl_values):.4f} USDT")
    print(f"  Всего прибыль: {sum(pnl_values):.4f} USDT")
    print()

# Анализ sl_reached
sl_reached = by_reason["sl_reached"]
if sl_reached:
    pnl_values = [float(t["net_pnl"]) for t in sl_reached]
    print(f"SL_REACHED сделки: {len(sl_reached)}")
    print(f"  Средний PnL: {sum(pnl_values)/len(pnl_values):.4f} USDT")
    print(f"  Макс: {max(pnl_values):.4f} USDT")
    print(f"  Мин: {min(pnl_values):.4f} USDT")
    print(f"  Всего убыток: {sum(pnl_values):.4f} USDT")
    print()

# Анализ profit_drawdown
profit_drawdown = by_reason["profit_drawdown"]
if profit_drawdown:
    pnl_values = [float(t["net_pnl"]) for t in profit_drawdown]
    print(f"PROFIT_DRAWDOWN сделки: {len(profit_drawdown)}")
    print(f"  Средний PnL: {sum(pnl_values)/len(pnl_values):.4f} USDT")
    print(f"  Макс: {max(pnl_values):.4f} USDT")
    print(f"  Мин: {min(pnl_values):.4f} USDT")
    print()

print("=" * 80)
print("ПРОБЛЕМЫ:")
print("=" * 80)
print()
print("1. SL = 0.8% слишком маленький:")
print("   - Не дает возможности для разворота")
print("   - Срабатывает слишком быстро")
print("   - Рекомендация: увеличить до 1.2-1.5%")
print()
print("2. Partial TP закрывает 60% при 1.2% прибыли:")
print("   - Оставшиеся 40% остаются открытыми")
print("   - Могут уйти в убыток, если цена развернется")
print("   - Рекомендация: после partial TP защитить оставшуюся позицию")
print()
print("3. После partial TP peak_profit пересчитывается:")
print("   - Но SL остается прежним (0.8%)")
print("   - Рекомендация: после partial TP использовать более мягкий SL")
print()
print("4. Profit Drawdown может закрывать слишком рано:")
print("   - Текущий threshold: 65% * 1.2 = 78%")
print("   - Может закрывать позиции, которые еще могут вырасти")
print()

print("=" * 80)
print("РЕКОМЕНДАЦИИ:")
print("=" * 80)
print()
print("1. Увеличить SL для ranging режима:")
print("   - Было: 0.8%")
print("   - Стало: 1.2-1.5% (дать больше места для разворота)")
print()
print("2. После partial TP использовать более мягкий SL:")
print("   - Для оставшейся позиции: SL = 1.5-2.0%")
print("   - Или использовать break-even (закрывать только при убытке)")
print()
print("3. Улучшить profit_drawdown:")
print("   - Увеличить threshold до 80-85%")
print("   - Или использовать адаптивный threshold на основе волатильности")
print()
print("4. Добавить защиту после partial TP:")
print("   - После partial TP установить break-even stop")
print("   - Или использовать trailing stop для оставшейся позиции")
print()
