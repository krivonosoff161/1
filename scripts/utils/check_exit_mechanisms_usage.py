#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка использования всех механизмов закрытия позиций ботом
Анализирует реальные сделки и определяет, какие механизмы использовались
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class ExitMechanismsChecker:
    """Проверяет использование всех механизмов закрытия позиций"""

    def __init__(self):
        self.positions = []
        self.mechanisms_usage = defaultdict(int)
        self.mechanisms_details = defaultdict(list)

    def load_positions(self, filepath: Path):
        """Загружает позиции из JSON"""
        print(f"📂 Загружаю позиции из {filepath.name}...")
        with open(filepath, "r", encoding="utf-8") as f:
            self.positions = json.load(f)
        print(f"✅ Загружено {len(self.positions)} позиций")

    def analyze_exit_mechanisms(self):
        """Анализирует, какие механизмы закрытия использовались"""
        print(f"\n🔍 Анализирую механизмы закрытия...")

        for pos in self.positions:
            mechanism = self._determine_exit_mechanism(pos)
            if mechanism:
                self.mechanisms_usage[mechanism] += 1
                self.mechanisms_details[mechanism].append(pos)

        print(f"✅ Анализ завершен")

    def _determine_exit_mechanism(self, position: Dict) -> Optional[str]:
        """Определяет механизм закрытия на основе данных позиции"""
        entry_price = position.get("entry_price", 0)
        exit_price = position.get("exit_price", 0)
        size = position.get("size", 0)
        entry_time = datetime.fromisoformat(position.get("entry_time", ""))
        exit_time = datetime.fromisoformat(position.get("exit_time", ""))
        duration_sec = (exit_time - entry_time).total_seconds()
        duration_min = duration_sec / 60

        # Рассчитываем PnL
        side = position.get("side", "long")
        if side == "long":
            price_change = exit_price - entry_price
            pnl_pct = (price_change / entry_price) * 100 if entry_price > 0 else 0
        else:
            price_change = entry_price - exit_price
            pnl_pct = (price_change / entry_price) * 100 if entry_price > 0 else 0

        # Получаем PnL от биржи (если есть)
        exchange_pnl = position.get("exchange_pnl")
        if exchange_pnl is not None:
            position_value = entry_price * size
            pnl_pct_from_exchange = (
                (exchange_pnl / position_value) * 100 if position_value > 0 else 0
            )
        else:
            pnl_pct_from_exchange = pnl_pct

        # Определяем механизм закрытия на основе характеристик

        # 1. Take Profit (TP) - высокая прибыль, достаточное время удержания
        # TP обычно: 2.4-4.0% для ranging, выше для trending
        if pnl_pct_from_exchange >= 2.0 and duration_min >= 5:
            return "TP"

        # 2. Profit Harvesting (PH) - быстрая прибыль за короткое время
        # PH: $0.10-0.20 за 60-180 сек
        if duration_min <= 3 and pnl_pct_from_exchange > 0.5:
            # Проверяем абсолютную прибыль
            if exchange_pnl and exchange_pnl >= 0.10:
                return "PH"

        # 3. Trailing Stop Loss (TSL) - прибыль была выше, но закрылось ниже
        # Сложно определить без данных о максимальной прибыли
        # Но если прибыль была положительной и закрылось не на максимуме
        if pnl_pct_from_exchange > 0.1 and pnl_pct_from_exchange < 1.5:
            # Возможно TSL сработал
            return "TSL"

        # 4. Stop Loss (SL) - убыток в пределах SL
        # SL обычно: -1.2% до -2.0%
        if -2.5 <= pnl_pct_from_exchange <= -0.5:
            return "SL"

        # 5. Loss Cut - большой убыток
        # Loss Cut: -4.0% и более
        if pnl_pct_from_exchange <= -3.5:
            return "LOSS_CUT"

        # 6. Timeout - долгое удержание, небольшая прибыль/убыток
        if duration_min >= 60 and abs(pnl_pct_from_exchange) < 1.0:
            return "TIMEOUT"

        # 7. Emergency Close - критический margin_ratio
        # Сложно определить без данных о марже, но если очень быстрый убыток
        if duration_min < 1 and pnl_pct_from_exchange < -2.0:
            return "EMERGENCY"

        # 8. Exit Analyzer - интеллектуальное закрытие
        # Сложно определить без логов, но если закрытие в оптимальный момент
        # (прибыль есть, но не максимальная, время среднее)
        if 0.5 <= pnl_pct_from_exchange <= 2.0 and 5 <= duration_min <= 30:
            return "EXIT_ANALYZER"

        return "UNKNOWN"

    def check_mechanisms_coverage(self):
        """Проверяет покрытие всех механизмов"""
        print(f"\n📊 ПРОВЕРКА ИСПОЛЬЗОВАНИЯ МЕХАНИЗМОВ ЗАКРЫТИЯ")
        print("=" * 80)

        total = len(self.positions)

        # Ожидаемые механизмы (из документации)
        expected_mechanisms = {
            "TP": "Take Profit - закрытие при достижении целевой прибыли",
            "PH": "Profit Harvesting - быстрое закрытие при высокой прибыли",
            "TSL": "Trailing Stop Loss - защита прибыли при откате",
            "SL": "Stop Loss - защита от убытков",
            "LOSS_CUT": "Loss Cut - принудительное закрытие при большом убытке",
            "TIMEOUT": "Timeout - закрытие по времени",
            "EMERGENCY": "Emergency Close - критическая ситуация",
            "EXIT_ANALYZER": "Exit Analyzer - интеллектуальное закрытие",
        }

        print(f"\n📈 СТАТИСТИКА ПО МЕХАНИЗМАМ:")
        print(f"   Всего позиций: {total}\n")

        for mechanism, description in expected_mechanisms.items():
            count = self.mechanisms_usage.get(mechanism, 0)
            percent = (count / total * 100) if total > 0 else 0
            status = "✅" if count > 0 else "❌"

            print(f"   {status} {mechanism}: {count} ({percent:.1f}%)")
            print(f"      {description}")

        # Проверяем использование всех механизмов
        print(f"\n🔍 АНАЛИЗ ПОКРЫТИЯ:")

        used_mechanisms = set(self.mechanisms_usage.keys())
        expected_set = set(expected_mechanisms.keys())

        missing = expected_set - used_mechanisms
        if missing:
            print(f"   ⚠️ Неиспользуемые механизмы: {', '.join(missing)}")
        else:
            print(f"   ✅ Все механизмы используются")

        # Проверяем распределение
        print(f"\n📊 РАСПРЕДЕЛЕНИЕ:")
        sorted_mechs = sorted(
            self.mechanisms_usage.items(), key=lambda x: x[1], reverse=True
        )
        for mechanism, count in sorted_mechs[:5]:
            percent = (count / total * 100) if total > 0 else 0
            print(f"   {mechanism}: {count} ({percent:.1f}%)")

    def analyze_exit_quality(self):
        """Анализирует качество закрытия позиций"""
        print(f"\n📊 АНАЛИЗ КАЧЕСТВА ЗАКРЫТИЯ")
        print("=" * 80)

        # Группируем по механизмам
        for mechanism, positions in self.mechanisms_details.items():
            if not positions:
                continue

            print(f"\n{mechanism} ({len(positions)} позиций):")

            # Статистика по PnL
            pnls = []
            durations = []

            for pos in positions:
                if pos.get("exchange_pnl") is not None:
                    pnls.append(pos["exchange_pnl"])
                elif pos.get("net_pnl") is not None:
                    pnls.append(pos["net_pnl"])

                entry_time = datetime.fromisoformat(pos.get("entry_time", ""))
                exit_time = datetime.fromisoformat(pos.get("exit_time", ""))
                duration = (exit_time - entry_time).total_seconds() / 60
                durations.append(duration)

            if pnls:
                avg_pnl = sum(pnls) / len(pnls)
                profitable = sum(1 for p in pnls if p > 0)
                print(f"   Средний PnL: ${avg_pnl:.2f}")
                print(
                    f"   Прибыльных: {profitable}/{len(pnls)} ({profitable/len(pnls)*100:.1f}%)"
                )

            if durations:
                avg_duration = sum(durations) / len(durations)
                print(f"   Средняя длительность: {avg_duration:.1f} мин")

    def generate_report(self) -> str:
        """Генерирует отчет"""
        report = []
        report.append("=" * 80)
        report.append("📊 ОТЧЕТ: ИСПОЛЬЗОВАНИЕ МЕХАНИЗМОВ ЗАКРЫТИЯ ПОЗИЦИЙ")
        report.append("=" * 80)
        report.append("")

        total = len(self.positions)

        report.append(f"Всего позиций: {total}")
        report.append("")

        report.append("СТАТИСТИКА ПО МЕХАНИЗМАМ:")
        sorted_mechs = sorted(
            self.mechanisms_usage.items(), key=lambda x: x[1], reverse=True
        )
        for mechanism, count in sorted_mechs:
            percent = (count / total * 100) if total > 0 else 0
            report.append(f"  {mechanism}: {count} ({percent:.1f}%)")

        report.append("")
        report.append("=" * 80)

        return "\n".join(report)


def main():
    """Главная функция"""
    print("=" * 80)
    print("🔍 ПРОВЕРКА ИСПОЛЬЗОВАНИЯ МЕХАНИЗМОВ ЗАКРЫТИЯ ПОЗИЦИЙ")
    print("=" * 80)

    checker = ExitMechanismsChecker()

    # Загружаем позиции
    positions_file = Path("exchange_positions.json")
    if not positions_file.exists():
        print("❌ Файл exchange_positions.json не найден!")
        print("   Запустите сначала analyze_exchange_trades_correctness.py")
        return

    checker.load_positions(positions_file)

    # Анализируем механизмы
    checker.analyze_exit_mechanisms()

    # Проверяем покрытие
    checker.check_mechanisms_coverage()

    # Анализируем качество
    checker.analyze_exit_quality()

    # Генерируем отчет
    report = checker.generate_report()

    # Сохраняем отчет
    report_file = Path("exit_mechanisms_report.md")
    report_file.write_text(report, encoding="utf-8")
    print(f"\n💾 Отчет сохранен в {report_file}")


if __name__ == "__main__":
    main()
