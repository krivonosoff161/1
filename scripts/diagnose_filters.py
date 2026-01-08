#!/usr/bin/env python3
"""
Диагностика работы фильтров сигналов.

Анализирует, почему 100% сигналов проходят все фильтры (статистически невозможно!).
"""

import json
import re
from collections import defaultdict
from pathlib import Path


def analyze_filter_logs():
    """Анализирует логи для выявления проблем с фильтрами."""

    log_dir = Path("logs/futures/archived")
    if not log_dir.exists():
        print(f"❌ Директория логов не найдена: {log_dir}")
        return

    # Найдем последнюю директорию логов
    log_folders = list(log_dir.glob("staging_*"))
    if not log_folders:
        print("❌ Логи не найдены")
        return

    latest_logs = sorted(log_folders)[-1]
    print(f"📁 Анализирую логи в: {latest_logs}")

    # Паттерны для поиска
    filter_patterns = {
        "ADX_PASSED": r"\[FILTER\].*ADX Filter - PASSED",
        "ADX_BLOCKED": r"\[FILTER\].*ADX Filter - BLOCKED",
        "MTF_PASSED": r"\[FILTER\].*MTF Filter - PASSED",
        "MTF_BLOCKED": r"\[FILTER\].*MTF Filter - BLOCKED",
        "PIVOT_PASSED": r"\[FILTER\].*Pivot Points Filter - PASSED",
        "PIVOT_BLOCKED": r"\[FILTER\].*Pivot Points Filter - BLOCKED",
        "CORRELATION_PASSED": r"\[FILTER\].*Correlation Filter - PASSED",
        "CORRELATION_BLOCKED": r"\[FILTER\].*Correlation Filter - BLOCKED",
        "VOLUME_PASSED": r"\[FILTER\].*Volume Profile Filter - PASSED",
        "VOLUME_BLOCKED": r"\[FILTER\].*Volume Profile Filter - BLOCKED",
        "VOLATILITY_PASSED": r"\[FILTER\].*Volatility Filter - PASSED",
        "VOLATILITY_BLOCKED": r"\[FILTER\].*Volatility Filter - BLOCKED",
        "LIQUIDITY_PASSED": r"\[FILTER\].*Liquidity Filter - PASSED",
        "LIQUIDITY_BLOCKED": r"\[FILTER\].*Liquidity Filter - BLOCKED",
        "ORDER_FLOW_PASSED": r"\[FILTER\].*Order Flow Filter - PASSED",
        "ORDER_FLOW_BLOCKED": r"\[FILTER\].*Order Flow Filter - BLOCKED",
    }

    stats = defaultdict(int)
    regime_stats = defaultdict(lambda: defaultdict(int))

    # Ищем в основном лог файле
    main_log = latest_logs / "futures_main.log"
    if main_log.exists():
        print(f"📄 Чтение {main_log.name}...")
        with open(main_log, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                for pattern_name, pattern in filter_patterns.items():
                    if re.search(pattern, line):
                        stats[pattern_name] += 1

                        # Извлекаем режим
                        regime_match = re.search(r"Режим: (\w+)", line)
                        if regime_match:
                            regime = regime_match.group(1)
                            regime_stats[regime][pattern_name] += 1

    # Выводим результаты
    print("\n" + "=" * 80)
    print("📊 СТАТИСТИКА ФИЛЬТРОВ")
    print("=" * 80)

    # Группируем по фильтрам
    filters_to_check = {
        "ADX": ("ADX_PASSED", "ADX_BLOCKED"),
        "MTF": ("MTF_PASSED", "MTF_BLOCKED"),
        "PIVOT": ("PIVOT_PASSED", "PIVOT_BLOCKED"),
        "CORRELATION": ("CORRELATION_PASSED", "CORRELATION_BLOCKED"),
        "VOLUME_PROFILE": ("VOLUME_PASSED", "VOLUME_BLOCKED"),
        "VOLATILITY": ("VOLATILITY_PASSED", "VOLATILITY_BLOCKED"),
        "LIQUIDITY": ("LIQUIDITY_PASSED", "LIQUIDITY_BLOCKED"),
        "ORDER_FLOW": ("ORDER_FLOW_PASSED", "ORDER_FLOW_BLOCKED"),
    }

    for filter_name, (passed_key, blocked_key) in filters_to_check.items():
        passed = stats[passed_key]
        blocked = stats[blocked_key]
        total = passed + blocked

        if total > 0:
            pass_rate = (passed / total) * 100
            if pass_rate > 95:
                status = "⚠️ КРИТИЧНО"
            elif pass_rate > 80:
                status = "🟡 ВЫСОКО"
            else:
                status = "✅ НОРМАЛЬНО"

            print(f"\n{status} {filter_name}:")
            print(f"  Пропущено: {passed}")
            print(f"  Заблокировано: {blocked}")
            print(f"  Pass Rate: {pass_rate:.1f}%")

    # По режимам
    print("\n" + "=" * 80)
    print("📊 СТАТИСТИКА ПО РЕЖИМАМ")
    print("=" * 80)

    for regime in ["ranging", "trending", "choppy"]:
        print(f"\n🔍 РЕЖИМ: {regime}")
        regime_data = regime_stats.get(regime, {})

        if not regime_data:
            print("  ❌ Нет данных")
            continue

        for filter_name, (passed_key, blocked_key) in filters_to_check.items():
            passed = regime_data.get(passed_key, 0)
            blocked = regime_data.get(blocked_key, 0)
            total = passed + blocked

            if total > 0:
                pass_rate = (passed / total) * 100
                print(f"  {filter_name}: {pass_rate:.1f}% PASSED ({passed}/{total})")

    # ДИАГНОСТИКА ПРОБЛЕМ
    print("\n" + "=" * 80)
    print("🔴 ДИАГНОСТИКА ПРОБЛЕМ")
    print("=" * 80)

    issues_found = []

    # Проблема 1: ADX фильтр пропускает в ranging режиме
    adx_ranging = regime_stats.get("ranging", {}).get("ADX_PASSED", 0)
    if adx_ranging > 0:
        issues_found.append(
            f"❌ ADX фильтр НЕ БЛОКИРУЕТ в RANGING режиме ({adx_ranging} пропущено)\n"
            f'   Причина: ADX считается "нормально низким" для ranging\n'
            f"   Решение: Нужна дополнительная фильтрация в ranging режиме"
        )

    # Проблема 2: MTF фильтр пропускает много
    mtf_stats = stats["MTF_PASSED"] + stats["MTF_BLOCKED"]
    if mtf_stats > 0:
        mtf_rate = (stats["MTF_PASSED"] / mtf_stats) * 100
        if mtf_rate > 90:
            issues_found.append(
                f"❌ MTF фильтр ПРОПУСКАЕТ {mtf_rate:.1f}% сигналов\n"
                f"   Причина: Пороги слишком низкие или фильтр не работает\n"
                f"   Проверить: MultiTimeframeFilter.check()"
            )

    # Проблема 3: Pivot Points ошибки
    if stats["PIVOT_BLOCKED"] == 0 and stats["PIVOT_PASSED"] > 0:
        issues_found.append(
            f"❌ Pivot Points НИКОГДА НЕ БЛОКИРУЕТ сигналы\n"
            f"   Статус: {stats['PIVOT_PASSED']} пропущено, 0 заблокировано\n"
            f"   Вероятно: Ошибка расчета или отключен фильтр"
        )

    # Проблема 4: Correlation фильтр
    corr_stats = stats["CORRELATION_PASSED"] + stats["CORRELATION_BLOCKED"]
    if corr_stats > 0:
        corr_rate = (stats["CORRELATION_PASSED"] / corr_stats) * 100
        if corr_rate > 95:
            issues_found.append(
                f"❌ Correlation фильтр ПРОПУСКАЕТ {corr_rate:.1f}% сигналов\n"
                f"   Вероятно: Пара не имеет коррелированных позиций или пороги не работают"
            )

    if issues_found:
        for i, issue in enumerate(issues_found, 1):
            print(f"\nПРОБЛЕМА #{i}:")
            print(issue)
    else:
        print("✅ Критичных проблем не обнаружено")

    # КРАТКАЯ СВОДКА
    print("\n" + "=" * 80)
    print("📋 КРАТКАЯ СВОДКА")
    print("=" * 80)

    total_signals = sum(stats[k] for k in stats if "PASSED" in k)
    total_blocked = sum(stats[k] for k in stats if "BLOCKED" in k)

    print(f"Всего сигналов прошло: {total_signals}")
    print(f"Всего сигналов заблокировано: {total_blocked}")

    if total_signals > 0:
        avg_pass_rate = (total_signals / (total_signals + total_blocked)) * 100
        print(f"Средний pass rate: {avg_pass_rate:.1f}%")

        if avg_pass_rate > 95:
            print("\n🚨 КРИТИЧНО: Фильтры фактически не работают!")
        elif avg_pass_rate > 80:
            print("\n⚠️ ВЫСОКИЙ pass rate: Фильтры работают слабо")
        else:
            print("\n✅ Фильтры работают нормально")


if __name__ == "__main__":
    analyze_filter_logs()
