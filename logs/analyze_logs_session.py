#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ логов за сессию 18:03-23:06
"""
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logs_dir = Path("logs/extracted")
time_pattern = re.compile(r"2025-11-03 (?:18:0[3-9]|19:|20:|21:|22:|23:0[0-6]):")

# Паттерны для поиска
patterns = {
    "real_signals": re.compile(r"РЕАЛЬНЫЙ СИГНАЛ"),
    "positions_opened": re.compile(r"✅.*Позиция.*открыт|✅.*исполнен"),
    "orders_placed": re.compile(r"Лимитный ордер размещен|Рыночный ордер размещен"),
    "errors": re.compile(r"ERROR|Exception|Traceback|Ошибка", re.I),
    "blocked_duplicates": re.compile(
        r"Уже есть.*позиция|пропускаем открытие|активных ордеров"
    ),
    "position_safety": re.compile(r"Проверка безопасности позиции|margin_ratio"),
}

stats = defaultdict(int)
events = defaultdict(list)

print("📊 Анализ логов за период 18:03-23:06...")
print("=" * 80)

# Читаем все файлы
log_files = sorted(logs_dir.glob("*.log"))
print(f"Найдено файлов: {len(log_files)}\n")

for log_file in log_files:
    print(f"Обработка: {log_file.name}")
    try:
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line_num, line in enumerate(f, 1):
                # Проверяем время
                if not time_pattern.search(line):
                    continue

                # Проверяем паттерны
                for pattern_name, pattern in patterns.items():
                    if pattern.search(line):
                        stats[pattern_name] += 1
                        if pattern_name in [
                            "real_signals",
                            "positions_opened",
                            "orders_placed",
                            "errors",
                        ]:
                            # Извлекаем время и краткую информацию
                            time_match = re.search(
                                r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line
                            )
                            if time_match:
                                events[pattern_name].append(
                                    {
                                        "time": time_match.group(1),
                                        "line": line.strip()[:150],
                                    }
                                )
                                if (
                                    len(events[pattern_name]) > 100
                                ):  # Ограничиваем размер
                                    events[pattern_name] = events[pattern_name][-100:]
    except Exception as e:
        print(f"  ⚠️ Ошибка при чтении {log_file.name}: {e}")

print("\n" + "=" * 80)
print("📈 СТАТИСТИКА ЗА ПЕРИОД 18:03-23:06")
print("=" * 80)

print(f"\n✅ Реальных сигналов: {stats['real_signals']}")
print(f"✅ Открытых позиций/исполнений: {stats['positions_opened']}")
print(f"📝 Размещенных ордеров: {stats['orders_placed']}")
print(f"❌ Ошибок: {stats['errors']}")
print(f"🚫 Заблокированных дубликатов: {stats['blocked_duplicates']}")
print(f"🔒 Проверок безопасности: {stats['position_safety']}")

# Показываем примеры событий
print("\n" + "=" * 80)
print("📋 ПРИМЕРЫ СОБЫТИЙ")
print("=" * 80)

for event_type in ["real_signals", "positions_opened", "orders_placed", "errors"]:
    if events[event_type]:
        print(f"\n🔹 {event_type.upper()} (первые 10):")
        for event in events[event_type][:10]:
            print(f"  {event['time']} | {event['line'][:120]}")

# Сохраняем полный отчет
report_file = Path("logs/session_report_18-03_23-06.txt")
with open(report_file, "w", encoding="utf-8") as f:
    f.write("=" * 80 + "\n")
    f.write("ОТЧЕТ ПО СЕССИИ: 18:03 - 23:06\n")
    f.write("=" * 80 + "\n\n")

    f.write("СТАТИСТИКА:\n")
    for key, value in stats.items():
        f.write(f"  {key}: {value}\n")

    f.write("\n\nДЕТАЛЬНЫЕ СОБЫТИЯ:\n")
    for event_type, event_list in events.items():
        if event_list:
            f.write(f"\n{event_type.upper()}:\n")
            for event in event_list:
                f.write(f"  {event['time']} | {event['line']}\n")

print(f"\n💾 Полный отчет сохранен: {report_file}")
