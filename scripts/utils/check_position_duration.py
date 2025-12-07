#!/usr/bin/env python3
"""
Проверка времени удержания позиций
"""

from datetime import datetime

# Время открытия позиций (из логов)
open_time = datetime(2025, 11, 28, 23, 31, 17)

# Текущее время
current_time = datetime.now()

# Вычисляем длительность
duration = current_time - open_time

hours = duration.total_seconds() / 3600
minutes = (duration.total_seconds() % 3600) / 60
seconds = duration.total_seconds() % 60

print("=" * 60)
print("⏰ ВРЕМЯ УДЕРЖАНИЯ ПОЗИЦИЙ")
print("=" * 60)
print(f"Время открытия: {open_time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Текущее время: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
print()
print(f"Длительность: {int(hours)}ч {int(minutes)}м {int(seconds)}с")
print(f"Всего часов: {hours:.2f}")
print("=" * 60)

