#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔬 PARAMETER FLOW TRACER - Трассировка параметров от config.yaml до модулей
Показывает ПОЛНЫЙ путь каждого параметра и все конфликты!
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class ParameterSource:
    """Источник параметра"""

    name: str
    value: Any
    source: str  # 'YAML', 'HARDCODE', 'DEFAULT', 'RUNTIME'
    location: str  # Где определен
    priority: int  # Приоритет (1=высший)


class ParameterFlowTracer:
    """Трассировщик потока параметров"""

    def __init__(self):
        self.parameters: Dict[str, List[ParameterSource]] = {}
        self.conflicts: List[Tuple[str, ParameterSource, ParameterSource]] = []

    def add_source(
        self, param_name: str, value: Any, source: str, location: str, priority: int
    ):
        """Добавляет источник параметра"""
        if param_name not in self.parameters:
            self.parameters[param_name] = []

        self.parameters[param_name].append(
            ParameterSource(param_name, value, source, location, priority)
        )

    def analyze_conflicts(self):
        """Анализирует конфликты между источниками"""
        for param_name, sources in self.parameters.items():
            if len(sources) > 1:
                # Сортируем по приоритету
                sorted_sources = sorted(sources, key=lambda x: x.priority)

                # Проверяем разные значения
                values = set(s.value for s in sorted_sources)
                if len(values) > 1:
                    # Есть конфликт!
                    winner = sorted_sources[0]
                    losers = sorted_sources[1:]
                    for loser in losers:
                        self.conflicts.append((param_name, winner, loser))

    def print_report(self):
        """Печатает полный отчет"""
        print("\n" + "=" * 120)
        print("🔬 PARAMETER FLOW TRACER - ПОЛНЫЙ АНАЛИЗ ПАРАМЕТРОВ")
        print("=" * 120)

        # 1. Все параметры
        print("\n📊 ВСЕ ПАРАМЕТРЫ И ИХ ИСТОЧНИКИ:\n")

        for param_name in sorted(self.parameters.keys()):
            sources = self.parameters[param_name]
            print(f"\n🔹 {param_name}:")

            for i, source in enumerate(sorted(sources, key=lambda x: x.priority), 1):
                priority_mark = "🏆" if i == 1 else "  "
                print(
                    f"  {priority_mark} [{source.source:8}] {source.value:10} | {source.location}"
                )
                print(f"      Priority: {source.priority}")

        # 2. Конфликты
        if self.conflicts:
            print("\n" + "=" * 120)
            print("⚠️  КОНФЛИКТЫ ПАРАМЕТРОВ (Разные значения из разных источников):")
            print("=" * 120 + "\n")

            for param_name, winner, loser in self.conflicts:
                print(f"\n❌ КОНФЛИКТ: {param_name}")
                print(f"  🏆 ИСПОЛЬЗУЕТСЯ: {winner.value}")
                print(f"      Источник: {winner.source} | {winner.location}")
                print(f"      Priority: {winner.priority}")
                print()
                print(f"  ❌ ИГНОРИРУЕТСЯ: {loser.value}")
                print(f"      Источник: {loser.source} | {loser.location}")
                print(f"      Priority: {loser.priority}")
                print(
                    f"  ⚡ ПРОБЛЕМА: Параметр определен в {loser.source}, но перезаписывается в {winner.source}!"
                )
        else:
            print("\n✅ КОНФЛИКТОВ НЕТ - все параметры согласованы!")

        # 3. Рекомендации
        print("\n" + "=" * 120)
        print("💡 РЕКОМЕНДАЦИИ:")
        print("=" * 120 + "\n")

        if self.conflicts:
            print(
                "1. Удалите hardcoded значения из кода - используйте только config.yaml"
            )
            print(
                "2. Если параметр должен быть динамическим (ARM) - читайте его из ARM, а не из базового config"
            )
            print("3. Установите единый источник истины для каждого параметра")
        else:
            print("✅ Все параметры корректно настроены!")


def trace_adx_parameters():
    """Трассирует параметры ADX через всю систему"""
    tracer = ParameterFlowTracer()

    print("🔍 Собираю информацию о параметрах ADX...")

    # 1. config.yaml
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Базовый ADX
        adx_filter = config.get("scalping", {}).get("adx_filter", {})
        if "di_difference" in adx_filter:
            tracer.add_source(
                "adx_di_difference_BASE",
                adx_filter["di_difference"],
                "YAML",
                "config.yaml:61 (scalping.adx_filter.di_difference)",
                priority=2,  # Средний приоритет
            )

        # ARM режимы
        arm = config.get("scalping", {}).get("adaptive_regime", {})

        for regime in ["trending", "ranging", "choppy"]:
            regime_cfg = arm.get(regime, {})
            modules = regime_cfg.get("modules", {})
            adx_module = modules.get("adx_filter", {})

            if "adx_di_difference" in adx_module:
                tracer.add_source(
                    f"adx_di_difference_{regime.upper()}",
                    adx_module["adx_di_difference"],
                    "YAML",
                    f"config.yaml (adaptive_regime.{regime}.modules.adx_filter.adx_di_difference)",
                    priority=1,  # Высший приоритет (ARM динамический)
                )

            if "ph_threshold" in regime_cfg:
                tracer.add_source(
                    f"ph_threshold_{regime.upper()}",
                    regime_cfg["ph_threshold"],
                    "YAML",
                    f"config.yaml (adaptive_regime.{regime}.ph_threshold)",
                    priority=1,
                )

    except Exception as e:
        print(f"❌ Ошибка чтения config.yaml: {e}")

    # 2. orchestrator.py - hardcoded значения
    try:
        orch_file = Path("src/strategies/scalping/orchestrator.py")
        if orch_file.exists():
            with open(orch_file, "r", encoding="utf-8") as f:
                orch_code = f.read()

            # Ищем строку 225 - базовая инициализация
            if 'di_difference", 1.5)' in orch_code:
                tracer.add_source(
                    "adx_di_difference_BASE",
                    1.5,
                    "HARDCODE",
                    "orchestrator.py:225 (default при чтении из config)",
                    priority=3,  # Низкий приоритет (fallback)
                )
            elif 'di_difference", 5.0)' in orch_code:
                tracer.add_source(
                    "adx_di_difference_BASE",
                    5.0,
                    "HARDCODE",
                    "orchestrator.py:225 (default при чтении из config)",
                    priority=3,
                )

            # Ищем ARM режимы (строки 421, 482, 543)
            import re

            # TRENDING
            match = re.search(
                r"# TRENDING.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if match:
                tracer.add_source(
                    "adx_di_difference_TRENDING",
                    float(match.group(1)),
                    "HARDCODE",
                    f"orchestrator.py:~421 (_create_arm_config TRENDING)",
                    priority=2,  # Средний (перезаписывает YAML?)
                )

            # RANGING
            match = re.search(
                r"# RANGING.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if match:
                tracer.add_source(
                    "adx_di_difference_RANGING",
                    float(match.group(1)),
                    "HARDCODE",
                    f"orchestrator.py:~482 (_create_arm_config RANGING)",
                    priority=2,
                )

            # CHOPPY
            match = re.search(
                r"# CHOPPY.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if match:
                tracer.add_source(
                    "adx_di_difference_CHOPPY",
                    float(match.group(1)),
                    "HARDCODE",
                    f"orchestrator.py:~543 (_create_arm_config CHOPPY)",
                    priority=2,
                )

    except Exception as e:
        print(f"⚠️  Ошибка чтения orchestrator.py: {e}")

    # 3. adaptive_regime_manager.py - dataclass defaults
    try:
        arm_file = Path("src/strategies/modules/adaptive_regime_manager.py")
        if arm_file.exists():
            with open(arm_file, "r", encoding="utf-8") as f:
                arm_code = f.read()

            # Ищем строку 71
            import re

            match = re.search(r"adx_di_difference:\s*float\s*=\s*([\d.]+)", arm_code)
            if match:
                tracer.add_source(
                    "adx_di_difference_BASE",
                    float(match.group(1)),
                    "DEFAULT",
                    "adaptive_regime_manager.py:71 (ModuleParameters dataclass default)",
                    priority=4,  # Самый низкий (default fallback)
                )

    except Exception as e:
        print(f"⚠️  Ошибка чтения adaptive_regime_manager.py: {e}")

    # Анализируем конфликты
    tracer.analyze_conflicts()

    # Печатаем отчет
    tracer.print_report()

    return tracer


def trace_profit_harvesting():
    """Трассирует параметры Profit Harvesting"""
    tracer = ParameterFlowTracer()

    print("\n\n🔍 Собираю информацию о параметрах Profit Harvesting...")

    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        arm = config.get("scalping", {}).get("adaptive_regime", {})

        for regime in ["trending", "ranging", "choppy"]:
            regime_cfg = arm.get(regime, {})

            if "ph_enabled" in regime_cfg:
                tracer.add_source(
                    f"ph_enabled_{regime.upper()}",
                    regime_cfg["ph_enabled"],
                    "YAML",
                    f"config.yaml (adaptive_regime.{regime}.ph_enabled)",
                    priority=1,
                )

            if "ph_threshold" in regime_cfg:
                tracer.add_source(
                    f"ph_threshold_{regime.upper()}",
                    regime_cfg["ph_threshold"],
                    "YAML",
                    f"config.yaml (adaptive_regime.{regime}.ph_threshold)",
                    priority=1,
                )

            if "ph_time_limit" in regime_cfg:
                tracer.add_source(
                    f"ph_time_limit_{regime.upper()}",
                    regime_cfg["ph_time_limit"],
                    "YAML",
                    f"config.yaml (adaptive_regime.{regime}.ph_time_limit)",
                    priority=1,
                )

    except Exception as e:
        print(f"❌ Ошибка: {e}")

    # Проверяем defaults в RegimeParameters
    try:
        arm_file = Path("src/strategies/modules/adaptive_regime_manager.py")
        if arm_file.exists():
            with open(arm_file, "r", encoding="utf-8") as f:
                arm_code = f.read()

            import re

            # ph_threshold default
            match = re.search(r"ph_threshold:\s*float\s*=\s*([\d.]+)", arm_code)
            if match:
                tracer.add_source(
                    "ph_threshold_DEFAULT",
                    float(match.group(1)),
                    "DEFAULT",
                    "adaptive_regime_manager.py (RegimeParameters default)",
                    priority=3,
                )

    except Exception as e:
        print(f"⚠️  Ошибка: {e}")

    tracer.analyze_conflicts()
    tracer.print_report()

    return tracer


def trace_order_size():
    """Трассирует параметры размера ордера"""
    tracer = ParameterFlowTracer()

    print("\n\n🔍 Собираю информацию о размерах ордеров...")

    # order_executor.py
    try:
        exec_file = Path("src/strategies/scalping/order_executor.py")
        if exec_file.exists():
            with open(exec_file, "r", encoding="utf-8") as f:
                exec_code = f.read()

            import re

            # min_order_value_usd
            match = re.search(r"self\.min_order_value_usd\s*=\s*([\d.]+)", exec_code)
            if match:
                tracer.add_source(
                    "min_order_value_usd",
                    float(match.group(1)),
                    "HARDCODE",
                    "order_executor.py (__init__)",
                    priority=1,
                )

            # MIN_LONG_OCO
            match = re.search(r"self\.MIN_LONG_OCO\s*=\s*([\d.]+)", exec_code)
            if match:
                tracer.add_source(
                    "MIN_LONG_OCO",
                    float(match.group(1)),
                    "HARDCODE",
                    "order_executor.py (__init__)",
                    priority=1,
                )

            # MIN_SHORT_OCO
            match = re.search(r"self\.MIN_SHORT_OCO\s*=\s*([\d.]+)", exec_code)
            if match:
                tracer.add_source(
                    "MIN_SHORT_OCO",
                    float(match.group(1)),
                    "HARDCODE",
                    "order_executor.py (__init__)",
                    priority=1,
                )

    except Exception as e:
        print(f"⚠️  Ошибка: {e}")

    tracer.analyze_conflicts()
    tracer.print_report()

    return tracer


def main():
    """Главная функция"""
    print("\n" + "=" * 120)
    print("🔬 PARAMETER FLOW TRACER - Трассировка всех параметров бота")
    print("=" * 120)

    # 1. ADX параметры
    print("\n\n" + "🎯" * 40)
    print("РАЗДЕЛ 1: ADX FILTER PARAMETERS")
    print("🎯" * 40)
    trace_adx_parameters()

    # 2. Profit Harvesting
    print("\n\n" + "💰" * 40)
    print("РАЗДЕЛ 2: PROFIT HARVESTING PARAMETERS")
    print("💰" * 40)
    trace_profit_harvesting()

    # 3. Order Size
    print("\n\n" + "📦" * 40)
    print("РАЗДЕЛ 3: ORDER SIZE PARAMETERS")
    print("📦" * 40)
    trace_order_size()

    # Итоговый вывод
    print("\n\n" + "=" * 120)
    print("✅ АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 120)
    print("\n💡 Теперь ты видишь ВСЮ цепочку параметров и все конфликты!")
    print("💡 Используй эту информацию чтобы исправить hardcoded значения!")
    print("\n")


if __name__ == "__main__":
    main()
