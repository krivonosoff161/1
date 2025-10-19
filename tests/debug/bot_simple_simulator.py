#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔬 BOT SIMULATOR - Полная имитация цикла торгового бота
Показывает ВСЕ проблемы перед реальным запуском!
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import yaml


class BotSimulator:
    """Симулятор полного цикла бота"""

    def __init__(self):
        self.issues = []
        self.warnings = []
        self.config_dict = None

    def log_issue(self, category: str, message: str):
        """Регистрирует проблему"""
        self.issues.append({"category": category, "message": message})
        print(f"❌ [{category}] {message}")

    def log_warning(self, category: str, message: str):
        """Регистрирует предупреждение"""
        self.warnings.append({"category": category, "message": message})
        print(f"⚠️  [{category}] {message}")

    def log_success(self, message: str):
        """Регистрирует успех"""
        print(f"✅ {message}")

    def log_info(self, message: str):
        """Информация"""
        print(f"ℹ️  {message}")

    async def step_1_load_config(self):
        """ШАГ 1: Загрузка конфигурации"""
        print("\n" + "=" * 80)
        print("📋 ШАГ 1: ЗАГРУЗКА КОНФИГУРАЦИИ")
        print("=" * 80)

        try:
            # Загружаем YAML напрямую
            with open("config.yaml", "r", encoding="utf-8") as f:
                self.config_dict = yaml.safe_load(f)

            self.log_success("Конфигурация загружена из config.yaml")

            # Проверяем ключевые параметры
            print("\n🔍 ПРОВЕРКА ПАРАМЕТРОВ:")

            # ADX базовый
            adx_base = self.config_dict.get("scalping", {}).get("adx_filter", {})
            di_diff_base = adx_base.get("di_difference", "НЕТ")
            print(f"\n📊 ADX Filter (базовый):")
            print(f"   di_difference: {di_diff_base}")
            if di_diff_base == 5.0:
                self.log_issue(
                    "ADX", f"Базовый di_difference = {di_diff_base} (старое значение!)"
                )
            elif di_diff_base == 1.5:
                self.log_success(f"Базовый di_difference = {di_diff_base} (правильно!)")

            # ARM режимы
            arm_config = self.config_dict.get("scalping", {}).get("adaptive_regime", {})

            print(f"\n🧠 ARM РЕЖИМЫ:")
            for regime in ["trending", "ranging", "choppy"]:
                regime_cfg = arm_config.get(regime, {})
                modules = regime_cfg.get("modules", {})
                adx_cfg = modules.get("adx_filter", {})

                di_diff = adx_cfg.get("adx_di_difference", "НЕТ")
                ph_threshold = regime_cfg.get("ph_threshold", "НЕТ")

                print(f"\n   {regime.upper()}:")
                print(f"      adx_di_difference: {di_diff}")
                print(f"      ph_threshold: ${ph_threshold}")

                # Проверяем значения
                expected_di = {"trending": 7.0, "ranging": 1.5, "choppy": 1.0}
                expected_ph = {"trending": 0.10, "ranging": 0.12, "choppy": 0.15}

                if di_diff == expected_di[regime]:
                    self.log_success(f"{regime}: adx_di_difference = {di_diff} ✅")
                else:
                    self.log_issue(
                        "ARM",
                        f"{regime}: adx_di_difference = {di_diff}, ожидалось {expected_di[regime]}",
                    )

                if ph_threshold == expected_ph[regime]:
                    self.log_success(f"{regime}: ph_threshold = ${ph_threshold} ✅")
                else:
                    self.log_issue(
                        "ARM",
                        f"{regime}: ph_threshold = ${ph_threshold}, ожидалось ${expected_ph[regime]}",
                    )

        except Exception as e:
            self.log_issue("CONFIG", f"Ошибка загрузки конфигурации: {e}")
            return False

        return True

    async def step_2_check_orchestrator_params(self):
        """ШАГ 2: Проверка параметров в коде orchestrator.py"""
        print("\n" + "=" * 80)
        print("🔍 ШАГ 2: ПРОВЕРКА КОДА ORCHESTRATOR.PY")
        print("=" * 80)

        try:
            # Читаем файл orchestrator.py
            orch_file = Path("src/strategies/scalping/orchestrator.py")
            if not orch_file.exists():
                self.log_issue("FILE", "orchestrator.py не найден!")
                return False

            with open(orch_file, "r", encoding="utf-8") as f:
                orch_code = f.read()

            # Проверяем строку 225 (базовая инициализация ADX)
            if "di_difference=self.config.adx_filter.get" in orch_code:
                if 'di_difference", 1.5)' in orch_code:
                    self.log_success("Строка 225: di_difference default = 1.5 ✅")
                elif 'di_difference", 5.0)' in orch_code:
                    self.log_issue(
                        "ORCH_225", "Строка 225: di_difference default = 5.0 (старое!)"
                    )

            # Проверяем hardcoded значения ARM
            import re

            trending_di = re.search(
                r"# TRENDING.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if trending_di:
                val = float(trending_di.group(1))
                if val == 7.0:
                    self.log_success(f"TRENDING: adx_di_difference = {val} ✅")
                else:
                    self.log_issue(
                        "ORCH_TREND",
                        f"TRENDING: adx_di_difference = {val} (ожидалось 7.0)",
                    )

            ranging_di = re.search(
                r"# RANGING.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if ranging_di:
                val = float(ranging_di.group(1))
                if val == 1.5:
                    self.log_success(f"RANGING: adx_di_difference = {val} ✅")
                else:
                    self.log_issue(
                        "ORCH_RANG",
                        f"RANGING: adx_di_difference = {val} (ожидалось 1.5)",
                    )

            choppy_di = re.search(
                r"# CHOPPY.*?adx_di_difference\s*=\s*([\d.]+)", orch_code, re.DOTALL
            )
            if choppy_di:
                val = float(choppy_di.group(1))
                if val == 1.0:
                    self.log_success(f"CHOPPY: adx_di_difference = {val} ✅")
                else:
                    self.log_issue(
                        "ORCH_CHOP",
                        f"CHOPPY: adx_di_difference = {val} (ожидалось 1.0)",
                    )

        except Exception as e:
            self.log_issue("ORCH_CHECK", f"Ошибка проверки orchestrator.py: {e}")
            return False

        return True

    async def step_5_test_filters(self):
        """ШАГ 5: Тестирование фильтров"""
        print("\n" + "=" * 80)
        print("🔍 ШАГ 5: ТЕСТИРОВАНИЕ ФИЛЬТРОВ")
        print("=" * 80)

        # Создаем тестовые данные
        test_cases = [
            {
                "name": "BTC LONG (+DI=16.4, -DI=13.9)",
                "plus_di": 16.4,
                "minus_di": 13.9,
                "direction": "LONG",
            },
            {
                "name": "BTC LONG (+DI=12.7, -DI=14.6)",
                "plus_di": 12.7,
                "minus_di": 14.6,
                "direction": "LONG",
            },
            {
                "name": "ETH SHORT (-DI=14.1, +DI=29.5)",
                "plus_di": 29.5,
                "minus_di": 14.1,
                "direction": "SHORT",
            },
        ]

        print("\n📊 ТЕСТОВЫЕ КЕЙСЫ ИЗ ЛОГОВ:\n")

        for test in test_cases:
            print(f"   {test['name']}:")
            plus_di = test["plus_di"]
            minus_di = test["minus_di"]
            direction = test["direction"]

            # Проверяем с разными порогами
            for threshold in [5.0, 1.5, 1.0]:
                if direction == "LONG":
                    diff = plus_di - minus_di
                    passed = diff >= threshold
                else:  # SHORT
                    diff = minus_di - plus_di
                    passed = diff >= threshold

                status = "✅ PASS" if passed else "❌ BLOCK"
                print(f"      Порог {threshold}: diff={diff:.1f} → {status}")
            print()

        return True

    async def run(self):
        """Запуск полной симуляции"""
        print("\n" + "=" * 80)
        print("🔬 BOT SIMULATOR - ПОЛНАЯ ДИАГНОСТИКА")
        print("=" * 80)
        print(f"⏰ Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        steps = [
            ("Загрузка конфигурации", self.step_1_load_config),
            ("Инициализация API", self.step_2_init_client),
            ("Инициализация Orchestrator", self.step_3_init_orchestrator),
            ("Симуляция генерации сигнала", self.step_4_simulate_signal_generation),
            ("Тестирование фильтров", self.step_5_test_filters),
        ]

        for i, (name, step_func) in enumerate(steps, 1):
            try:
                success = await step_func()
                if not success:
                    print(f"\n❌ Остановлено на шаге {i}: {name}")
                    break
            except KeyboardInterrupt:
                print("\n⚠️  Прервано пользователем")
                break
            except Exception as e:
                self.log_issue("FATAL", f"Критическая ошибка на шаге {i} ({name}): {e}")
                import traceback

                traceback.print_exc()
                break

        # Итоги
        print("\n" + "=" * 80)
        print("📋 ИТОГОВЫЙ ОТЧЕТ")
        print("=" * 80)

        print(f"\n❌ ПРОБЛЕМЫ: {len(self.issues)}")
        for issue in self.issues:
            print(f"   [{issue['category']}] {issue['message']}")

        print(f"\n⚠️  ПРЕДУПРЕЖДЕНИЯ: {len(self.warnings)}")
        for warning in self.warnings:
            print(f"   [{warning['category']}] {warning['message']}")

        if not self.issues:
            print("\n✅ ВСЕ ОТЛИЧНО! БОТ ГОТОВ К ЗАПУСКУ!")
        else:
            print(f"\n❌ НАЙДЕНО {len(self.issues)} ПРОБЛЕМ - ИСПРАВЬ ПЕРЕД ЗАПУСКОМ!")

        print("=" * 80)

        # Закрываем соединения
        if self.client:
            await self.client.session.close()


async def main():
    simulator = BotSimulator()
    await simulator.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Выход...")
