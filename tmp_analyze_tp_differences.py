#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Анализ различий в TP для разных пар"""

print("="*80)
print("АНАЛИЗ: Различия в TP для разных пар")
print("="*80)

# Параметры
balance = 1018.0
leverage = 5
base_size = 50.0 + ((balance - 500.0) / 1000.0) * 100.0  # $101.80

# Per-symbol multipliers
multipliers = {
    "BTC-USDT": 1.2,
    "ETH-USDT": 1.0,
    "SOL-USDT": 0.9,
    "DOGE-USDT": 0.8,
    "XRP-USDT": 0.8,
}

# Текущий TP (одинаковый для всех)
tp_percent_global = 1.0

print(f"\n💰 Баланс: ${balance}")
print(f"   Leverage: {leverage}x")
print(f"   Базовый размер: ${base_size:.2f}")
print(f"   TP (глобальный): {tp_percent_global}% от маржи\n")

print("="*80)
print("ТЕКУЩАЯ СИТУАЦИЯ (одинаковый TP 1.0% для всех пар)")
print("="*80)

results = []
for symbol, multiplier in multipliers.items():
    position_size = base_size * multiplier
    margin = position_size / leverage
    tp_absolute = margin * (tp_percent_global / 100)
    
    results.append({
        "symbol": symbol,
        "multiplier": multiplier,
        "position_size": position_size,
        "margin": margin,
        "tp_percent": tp_percent_global,
        "tp_absolute": tp_absolute
    })
    
    print(f"\n{symbol}:")
    print(f"   Multiplier: {multiplier}x")
    print(f"   Размер позиции: ${position_size:.2f}")
    print(f"   Маржа: ${margin:.2f}")
    print(f"   TP: {tp_percent_global}% = ${tp_absolute:.4f}")
    print(f"   Разница с BTC: ${tp_absolute - results[0]['tp_absolute']:.4f}")

print("\n" + "="*80)
print("АНАЛИЗ РАЗЛИЧИЙ")
print("="*80)

btc_tp = results[0]["tp_absolute"]
max_tp = max(r["tp_absolute"] for r in results)
min_tp = min(r["tp_absolute"] for r in results)

print(f"\n📊 Статистика:")
print(f"   Максимальный TP (BTC): ${max_tp:.4f}")
print(f"   Минимальный TP (DOGE/XRP): ${min_tp:.4f}")
print(f"   Разница: ${max_tp - min_tp:.4f} ({((max_tp / min_tp - 1) * 100):.1f}% больше)")
print(f"\n   BTC vs SOL: ${results[0]['tp_absolute'] - results[2]['tp_absolute']:.4f} ({(results[0]['tp_absolute'] / results[2]['tp_absolute'] - 1) * 100:.1f}% больше)")

print("\n" + "="*80)
print("ВАРИАНТ 1: Одинаковая абсолютная прибыль для всех пар")
print("="*80)

# Целевая абсолютная прибыль (например, средняя)
target_absolute_tp = sum(r["tp_absolute"] for r in results) / len(results)

print(f"\n🎯 Целевая абсолютная прибыль: ${target_absolute_tp:.4f}")

for r in results:
    required_tp_percent = (target_absolute_tp / r["margin"]) * 100
    print(f"\n{r['symbol']}:")
    print(f"   Маржа: ${r['margin']:.2f}")
    print(f"   Требуемый TP: {required_tp_percent:.2f}% (для ${target_absolute_tp:.4f})")
    print(f"   Текущий TP: {r['tp_percent']:.2f}% (дает ${r['tp_absolute']:.4f})")

print("\n" + "="*80)
print("ВАРИАНТ 2: Пропорциональный TP (больше для больших позиций)")
print("="*80)

# TP пропорционален размеру позиции (например, 1.0% для BTC, 0.9% для SOL)
print("\n📊 Предложение:")
print("   BTC-USDT: 1.0% (высокая ликвидность, большая позиция)")
print("   ETH-USDT: 0.95% (стандарт)")
print("   SOL-USDT: 0.9% (средняя ликвидность)")
print("   DOGE-USDT: 0.85% (низкая ликвидность)")
print("   XRP-USDT: 0.85% (низкая ликвидность)")

tp_percent_proportional = {
    "BTC-USDT": 1.0,
    "ETH-USDT": 0.95,
    "SOL-USDT": 0.9,
    "DOGE-USDT": 0.85,
    "XRP-USDT": 0.85,
}

for r in results:
    symbol = r["symbol"]
    tp_pct = tp_percent_proportional.get(symbol, 1.0)
    tp_abs = r["margin"] * (tp_pct / 100)
    print(f"\n{symbol}:")
    print(f"   TP: {tp_pct:.2f}% = ${tp_abs:.4f}")
    print(f"   Разница с текущим: ${tp_abs - r['tp_absolute']:.4f}")

print("\n" + "="*80)
print("ВАРИАНТ 3: Обратно пропорциональный TP (меньше для больших позиций)")
print("="*80)

# Меньше TP для больших позиций (меньше риск, больше стабильность)
print("\n📊 Предложение:")
print("   BTC-USDT: 0.9% (большая позиция, меньше риск)")
print("   ETH-USDT: 1.0% (стандарт)")
print("   SOL-USDT: 1.1% (средняя позиция, можно больше рисковать)")
print("   DOGE-USDT: 1.2% (маленькая позиция, можно больше рисковать)")
print("   XRP-USDT: 1.2% (маленькая позиция, можно больше рисковать)")

tp_percent_inverse = {
    "BTC-USDT": 0.9,
    "ETH-USDT": 1.0,
    "SOL-USDT": 1.1,
    "DOGE-USDT": 1.2,
    "XRP-USDT": 1.2,
}

for r in results:
    symbol = r["symbol"]
    tp_pct = tp_percent_inverse.get(symbol, 1.0)
    tp_abs = r["margin"] * (tp_pct / 100)
    print(f"\n{symbol}:")
    print(f"   TP: {tp_pct:.2f}% = ${tp_abs:.4f}")
    print(f"   Разница с текущим: ${tp_abs - r['tp_absolute']:.4f}")

print("\n" + "="*80)
print("РЕКОМЕНДАЦИИ")
print("="*80)

print("\n✅ ВАРИАНТ 2 (Пропорциональный) - РЕКОМЕНДУЕТСЯ:")
print("   - Больше TP для больших позиций (BTC, ETH)")
print("   - Меньше TP для маленьких позиций (DOGE, XRP)")
print("   - Учитывает ликвидность и размер позиции")
print("   - Более консервативный подход")

print("\n✅ ВАРИАНТ 3 (Обратно пропорциональный) - АЛЬТЕРНАТИВА:")
print("   - Меньше TP для больших позиций (меньше риск)")
print("   - Больше TP для маленьких позиций (больше риск)")
print("   - Более агрессивный подход для маленьких позиций")

print("\n⚠️ ВАРИАНТ 1 (Одинаковая абсолютная прибыль) - НЕ РЕКОМЕНДУЕТСЯ:")
print("   - Слишком разные проценты для разных пар")
print("   - Может быть неоптимально для скальпинга")

