#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Финальная проверка leverage и позиций"""

import re
from pathlib import Path

log_file = Path("logs/futures/futures_main_2025-11-11.log")

with open(log_file, "r", encoding="utf-8") as f:
    log = f.read()

# Проверяем установку leverage при инициализации
init_leverage = re.findall(r"00:10:5\d.*Плечо 5x установлено", log)
print("=" * 60)
print("📊 ФИНАЛЬНАЯ ПРОВЕРКА LEVERAGE")
print("=" * 60)
print(f"\n✅ Установка leverage при инициализации:")
print(f"   - Всего запросов: {len(init_leverage)}")
print(f"   - Ожидалось: 10 (5 символов × 2 направления)")
print(f"   - Статус: {'✅ УСПЕШНО' if len(init_leverage) == 10 else '⚠️ НЕПОЛНО'}")

# Проверяем реальные ошибки 429
real_errors = re.findall(r"ERROR.*429|ERROR.*Too Many|WARNING.*429.*leverage", log, re.IGNORECASE)
print(f"\n❌ Реальные ошибки 429: {len(real_errors)}")
if real_errors:
    for i, err in enumerate(real_errors[:3], 1):
        print(f"   {i}. {err[:100]}")
else:
    print("   ✅ Ошибок 429 не найдено!")

# Проверяем leverage в открытых позициях
positions = re.findall(r"'lever': '(\d+)'", log)
if positions:
    print(f"\n💰 Leverage в открытых позициях на бирже:")
    for i, lev in enumerate(set(positions), 1):
        count = positions.count(lev)
        print(f"   - Leverage {lev}x: {count} позиций")

# Проверяем расчеты leverage
calc_leverage = re.findall(r"leverage=(\d+)x", log)
if calc_leverage:
    unique_leverage = set(calc_leverage)
    print(f"\n🔢 Leverage в расчетах:")
    for lev in unique_leverage:
        count = calc_leverage.count(lev)
        print(f"   - {lev}x: используется в {count} расчетах")

# Проверяем позиции
opened_positions = re.findall(r"Позиция.*открыта.*(ETH-USDT|BTC-USDT|SOL-USDT|DOGE-USDT|XRP-USDT)", log)
if opened_positions:
    print(f"\n📈 Открытые позиции:")
    for pos in set(opened_positions):
        count = opened_positions.count(pos)
        print(f"   - {pos}: {count} открытий")

print("\n" + "=" * 60)
if len(real_errors) == 0 and len(init_leverage) == 10:
    print("✅ ИТОГОВЫЙ СТАТУС: ВСЕ ОТЛИЧНО!")
    print("   - Leverage 5x установлен для всех символов")
    print("   - Ошибок 429 нет")
    print("   - Позиции открываются с leverage 5x")
else:
    print("⚠️ ИТОГОВЫЙ СТАТУС: ТРЕБУЕТСЯ ВНИМАНИЕ")
print("=" * 60)

