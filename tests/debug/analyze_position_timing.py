"""
Тест для анализа тайминга позиций
Определяет, почему позиции закрываются слишком быстро (3-5 минут)
"""

import csv
from datetime import datetime
from typing import Dict, List


def analyze_position_timing(log_file_path: str) -> Dict:
    """Анализ тайминга позиций"""

    print("⏱️ АНАЛИЗ ТАЙМИНГА ПОЗИЦИЙ")
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

    # Анализ продолжительности позиций
    durations = []
    for pos in positions:
        try:
            # Используем duration_sec если есть, иначе считаем из timestamp
            if pos.get("duration_sec"):
                duration_minutes = float(pos["duration_sec"]) / 60
            else:
                # Fallback на расчет из timestamp (если есть открытие и закрытие)
                duration_minutes = 0  # placeholder
            durations.append(duration_minutes)
        except (KeyError, ValueError):
            continue

    if not durations:
        print("❌ Нет данных о продолжительности позиций")
        return {}

    print(f"📈 Всего позиций с таймингом: {len(durations)}")
    print(
        f"⏱️ Продолжительность: min={min(durations):.1f} мин, max={max(durations):.1f} мин, avg={sum(durations)/len(durations):.1f} мин"
    )

    print(f"📈 Всего позиций с таймингом: {len(durations)}")
    print(
        f"⏱️ Продолжительность: min={min(durations):.1f} мин, max={max(durations):.1f} мин, avg={sum(durations)/len(durations):.1f} мин"
    )

    # Анализ распределения по времени удержания
    quick_closes = len([d for d in durations if d <= 5])  # 5 минут
    medium_closes = len([d for d in durations if 5 < d <= 30])  # 5-30 минут
    long_closes = len([d for d in durations if d > 30])  # >30 минут

    print(f"\n📊 РАСПРЕДЕЛЕНИЕ ПО ВРЕМЕНИ:")
    print(
        f"   ⚡ Быстрые (≤5 мин): {quick_closes} ({quick_closes/len(durations)*100:.1f}%)"
    )
    print(
        f"   🕐 Средние (5-30 мин): {medium_closes} ({medium_closes/len(durations)*100:.1f}%)"
    )
    print(
        f"   🕛 Долгие (>30 мин): {long_closes} ({long_closes/len(durations)*100:.1f}%)"
    )

    # Анализ быстрых закрытий
    if quick_closes > 0:
        print(f"\n⚡ АНАЛИЗ БЫСТРЫХ ЗАКРЫТИЙ:")
        quick_positions = []
        for pos in positions:
            try:
                open_time = datetime.fromisoformat(
                    pos["open_time"].replace("Z", "+00:00")
                )
                close_time = datetime.fromisoformat(
                    pos["close_time"].replace("Z", "+00:00")
                )
                duration = (close_time - open_time).total_seconds() / 60
                if duration <= 5:
                    quick_positions.append(pos)
            except:
                continue

        quick_reasons = {}
        for pos in quick_positions:
            reason = pos.get("close_reason", "unknown")
            quick_reasons[reason] = quick_reasons.get(reason, 0) + 1

        print(f"   Причины быстрых закрытий: {quick_reasons}")

        if quick_closes / len(durations) > 0.5:
            print(
                f"   ⚠️ КРИТИЧНО: {quick_closes/len(durations)*100:.1f}% позиций закрываются за ≤5 минут!"
            )
            print(f"   💡 Решение: Увеличить таймауты или улучшить фильтры входа")

    # Анализ по времени суток
    hourly_distribution = {}
    for pos in positions:
        try:
            open_time = datetime.fromisoformat(pos["open_time"].replace("Z", "+00:00"))
            hour = open_time.hour
            hourly_distribution[hour] = hourly_distribution.get(hour, 0) + 1
        except:
            continue

    if hourly_distribution:
        print(f"\n🕐 РАСПРЕДЕЛЕНИЕ ПО ЧАСАМ:")
        for hour in sorted(hourly_distribution.keys()):
            count = hourly_distribution[hour]
            print(f"   {hour:02d}:00: {count} позиций")

    # Анализ выходных дней
    weekend_positions = 0
    weekday_positions = 0
    for pos in positions:
        try:
            open_time = datetime.fromisoformat(pos["open_time"].replace("Z", "+00:00"))
            if open_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
                weekend_positions += 1
            else:
                weekday_positions += 1
        except:
            continue

    if weekend_positions + weekday_positions > 0:
        print(f"\n📅 РАСПРЕДЕЛЕНИЕ ПО ДНЯМ НЕДЕЛИ:")
        print(
            f"   Будни: {weekday_positions} ({weekday_positions/(weekday_positions+weekend_positions)*100:.1f}%)"
        )
        print(
            f"   Выходные: {weekend_positions} ({weekend_positions/(weekday_positions+weekend_positions)*100:.1f}%)"
        )

    # Рекомендации
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    avg_duration = sum(durations) / len(durations)
    if avg_duration < 10:
        print(f"   • Средняя продолжительность слишком мала: {avg_duration:.1f} мин")
        print(f"   • Решение: Увеличить минимальное время удержания позиции")
    elif avg_duration > 60:
        print(f"   • Средняя продолжительность приемлемая: {avg_duration:.1f} мин")

    return {
        "total_positions": len(durations),
        "avg_duration": sum(durations) / len(durations),
        "quick_closes_ratio": quick_closes / len(durations) * 100,
        "hourly_distribution": hourly_distribution,
        "weekend_ratio": weekend_positions
        / (weekend_positions + weekday_positions)
        * 100
        if weekend_positions + weekday_positions > 0
        else 0,
    }


if __name__ == "__main__":
    from pathlib import Path

    log_file = "logs/futures/archived/logs_2026-01-05_19-12-19/all_data_2026-01-05.csv"
    if Path(log_file).exists():
        analyze_position_timing(log_file)
    else:
        print(f"❌ Файл {log_file} не найден")
