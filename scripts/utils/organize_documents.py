#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для организации документов в проекте согласно плану
Дата: 27.12.2025
"""

import os
import shutil
from pathlib import Path

# Корневая директория проекта
ROOT_DIR = Path(__file__).parent.parent.parent

def create_directories():
    """Создает все необходимые папки"""
    dirs_to_create = [
        "docs/analysis/reports/2025-12",
        "docs/analysis/logs/2025-12",
        "docs/analysis/qa",
        "docs/analysis/leverage",
        "docs/fixes/completed/2025-12/implementation",
        "docs/fixes/completed/2025-12/checks",
        "docs/fixes/completed/2025-12/optimization",
        "docs/plans/2025-12",
        "docs/reports/2025-12",
        "docs/reports/status",
        "docs/audit/2025-12",
        "docs/reference",
        "docs/development",
    ]
    
    for dir_path in dirs_to_create:
        full_path = ROOT_DIR / dir_path
        full_path.mkdir(parents=True, exist_ok=True)
        print(f"[OK] Создана папка: {dir_path}")

def move_file(source, destination):
    """Безопасно перемещает файл"""
    source_path = ROOT_DIR / source
    dest_path = ROOT_DIR / destination
    
    if not source_path.exists():
        print(f"[WARN] Файл не найден: {source}")
        return False
    
    if dest_path.exists():
        print(f"[WARN] Файл уже существует: {destination}, пропускаем")
        return False
    
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(dest_path))
    print(f"[OK] Перемещен: {source} -> {destination}")
    return True

def organize_documents():
    """Основная функция организации документов"""
    print("=" * 60)
    print("ОРГАНИЗАЦИЯ ДОКУМЕНТОВ ПРОЕКТА")
    print("=" * 60)
    print()
    
    # Создаем папки
    print("1. Создание папок...")
    create_directories()
    print()
    
    # Перемещение файлов
    print("2. Перемещение файлов...")
    
    # Анализы (декабрь 2025)
    analysis_files = [
        "АНАЛИЗ_6_ЧАСОВ_РАБОТЫ_2025-12-21.md",
        "АНАЛИЗ_ЛОГОВ_2025-12-23.md",
        "АНАЛИЗ_ЛОГОВ_ЗАПУСКА_26_12_2025.md",
        "АНАЛИЗ_ЛОГОВ_ЗАПУСКА_26_12_2025_15_40.md",
        "АНАЛИЗ_ЛОГОВ_ЗАПУСКА_26_12_2025_16_51.md",
        "АНАЛИЗ_ЛОГОВ_И_ДОХОДНОСТИ_26_12_2025.md",
        "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ЗАПУСКА.md",
        "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ОТКРЫТИЯ_ПОЗИЦИИ.md",
        "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ПЕРЕЗАПУСКА_23_12_2025.md",
        "АНАЛИЗ_ЛОГОВ_ПОСЛЕ_ПЕРЕЗАПУСКА.md",
        "АНАЛИЗ_ПОЗИЦИИ_SOL_USDT_26_12_2025.md",
        "АНАЛИЗ_ПРИЧИН_УБЫТОЧНОСТИ_26_12_2025.md",
        "АНАЛИЗ_ПРОБЛЕМ_ИНИЦИАЛИЗАЦИИ_И_РЕЖИМОВ_26_12_2025.md",
        "АНАЛИЗ_ПРОБЛЕМ_ФИЛЬТРОВ_26_12_2025.md",
        "АНАЛИЗ_РЕКОМЕНДАЦИЙ_КИМИ_26_12_2025.md",
        "АНАЛИЗ_СИСТЕМЫ_ЛОГИРОВАНИЯ_26_12_2025.md",
        "АНАЛИЗ_ЦЕПОЧЕК_FALLBACK_25_12_2025.md",
        "АНАЛИЗ_FALLBACK_ЗНАЧЕНИЙ_25_12_2025.md",
        "АНАЛИЗ_TA_LIB_2025-12-21.md",
        "АНАЛИЗ_ADX_FILTER.md",
        "АНАЛИЗ_PnL_ПОЗИЦИЙ.md",
        "АНАЛИЗ_ДЛЯ_КИМИ.md",
        "АНАЛИЗ_ЗАКРЫТИЯ_DOGE_21_12_2025.md",
        "АНАЛИЗ_ЗАКРЫТИЯ_XRP_И_SOL.md",
        "АНАЛИЗ_ЗАКРЫТИЯ_И_LEVERAGE.md",
        "АНАЛИЗ_ЗАМЕЧАНИЙ_SONNET.md",
        "АНАЛИЗ_МЕДЛЕННОЙ_ГЕНЕРАЦИИ_СИГНАЛОВ.md",
        "АНАЛИЗ_ОТВЕТА_SONNET.md",
        "АНАЛИЗ_ОТСУТСТВИЯ_СИГНАЛОВ.md",
        "АНАЛИЗ_ПРОБЛЕМ_ЗАКРЫТИЯ_ПОЗИЦИЙ.md",
        "АНАЛИЗ_ПРОБЛЕМ_ОТ_ГРОКА_2025-12-21.md",
        "АНАЛИЗ_ПРОИЗВОДИТЕЛЬНОСТИ_ПОСЛЕ_ОПТИМИЗАЦИЙ_2025-12-21.md",
        "АНАЛИЗ_РЕКОМЕНДАЦИЙ_ГРОКА_2025-12-21.md",
        "АНАЛИЗ_СИСТЕМЫ_SCORE.md",
        "АНАЛИЗ_СИСТЕМЫ_SCORE_ОБНОВЛЕНО.md",
        "АНАЛИЗ_ТОРГОВЛИ_24Ч_2025-12-21.md",
        "АНАЛИЗ_ТОРГОВОГО_БОТА_OKX.md",
        "АНАЛИЗ_УСПЕХОВ_ЗАКРЫТИЯ_DOGE_ОТ_ГРОКА.md",
        "АНАЛИЗ_ФИЛЬТРОВ_И_ЗАХАРДКОЖЕННЫХ_ПАРАМЕТРОВ.md",
        "КРИТИЧЕСКИЙ_АНАЛИЗ_ЛОГОВ_26_12_2025.md",
        "ПОЛНЫЙ_АНАЛИЗ_БОТА_ПО_ГРОКУ_2025-12-21.md",
        "ПОЛНЫЙ_АНАЛИЗ_БОТА_ТРЕЙДЕР_ПРОГРАММИСТ.md",
        "ПОЛНЫЙ_АНАЛИЗ_И_ИСПРАВЛЕНИЯ.md",
        "ПОЛНЫЙ_АНАЛИЗ_ПРОЕКТА_26_12_2025.md",
        "ПОЛНЫЙ_АНАЛИЗ_СИСТЕМЫ_SCORE.md",
        "ПОЛНЫЙ_КОД_ПРОЕКТА_26_12_2025.md",
        "УГЛУБЛЕННЫЙ_АНАЛИЗ_ВСЕХ_ВОПРОСОВ_26_12_2025.md",
    ]
    
    for file in analysis_files:
        move_file(file, f"docs/analysis/reports/2025-12/{file}")
    
    # Анализы логики
    logic_analysis = [
        "ANALYSIS_BOT_LOGIC_AND_DATA_FLOW.md",
        "DETAILED_ANALYSIS_POSITION_SCALING_AND_FIXES.md",
    ]
    
    for file in logic_analysis:
        move_file(file, f"docs/analysis/other/{file}")
    
    # Исправления и отчеты
    fixes_files = [
        "ОТЧЕТ_ИСПРАВЛЕНИЙ_26_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЙ_FALLBACK_25_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЙ_АДАПТИВНЫХ_ФИЛЬТРОВ_26_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЙ_ИНИЦИАЛИЗАЦИИ_И_РЕЖИМОВ_26_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЙ_ОШИБОК_26_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЯ_DATETIME_ERROR_26_12_2025.md",
        "ОТЧЕТ_ИСПРАВЛЕНИЯ_EXIT_PARAMS_26_12_2025.md",
        "ОТЧЕТ_УБИРАНИЯ_FALLBACK_РЕЖИМОВ_26_12_2025.md",
        "ОТЧЕТ_УЛУЧШЕНИЯ_ЛОГИРОВАНИЯ_26_12_2025.md",
        "ОТЧЕТ_ИНТЕГРАЦИИ_26_12_2025.md",
        "ОТЧЕТ_ПРОБЛЕМ_ПАРАМЕТРОВ.md",
        "ОТЧЕТ_ПРОВЕРКИ_ОПИСАНИЯ_БОТА.md",
        "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЙ_2025-12-23.md",
        "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЙ_24_12_2025.md",
        "ИТОГОВЫЙ_ОТЧЕТ_ИСПРАВЛЕНИЯ_SL.md",
        "ИТОГОВЫЙ_ОТЧЕТ_ВЫПОЛНЕНИЯ_ПРАВОК.md",
        "ПОЛНЫЙ_ОТЧЕТ_ИЗМЕНЕНИЙ_26_12_2025.md",
        "РЕЗЮМЕ_ИСПРАВЛЕНИЙ_27_12_2025.md",
        "ПРОВЕРКА_ИНДИКАТОРОВ_27_12_2025.md",
    ]
    
    for file in fixes_files:
        move_file(file, f"docs/fixes/completed/2025-12/{file}")
    
    # Исправления (отдельные файлы)
    fixes_individual = [
        "ИСПРАВЛЕНИЕ_CSV_И_АРХИВАЦИИ.md",
        "ИСПРАВЛЕНИЕ_КРИТИЧЕСКИХ_БАГОВ.md",
        "ИСПРАВЛЕНИЕ_ОШИБОК_АДАПТИВНЫХ_ФИЛЬТРОВ.md",
        "ИСПРАВЛЕНИЕ_ОШИБОК_ИЗ_ЛОГОВ.md",
        "ИСПРАВЛЕНИЕ_ЧТЕНИЯ_SL_ИЗ_КОНФИГА.md",
        "ИСПРАВЛЕНИЯ_DATETIME_2025-12-23.md",
        "ИСПРАВЛЕНИЯ_КРИТИЧЕСКИХ_ПРОБЛЕМ_ЛОГИРОВАНИЯ.md",
        "ИСПРАВЛЕНИЯ_ПО_РЕКОМЕНДАЦИЯМ_ГРОКА.md",
        "АНАЛИЗ_IMPROVEMENTS_AND_FIXES.md",
    ]
    
    for file in fixes_individual:
        move_file(file, f"docs/fixes/completed/2025-12/{file}")
    
    # Планы
    plans_files = [
        "ПЛАН_АНАЛИЗА_ПОСЛЕ_6_ЧАСОВ_РАБОТЫ.md",
        "ПЛАН_ИСПРАВЛЕНИЙ_28_ПРАВОК.md",
        "ПЛАН_ИСПРАВЛЕНИЙ_КРИТИЧЕСКИХ_ПРОБЛЕМ.md",
        "ПЛАН_ИСПРАВЛЕНИЙ_ПО_АНАЛИЗУ_SONNET.md",
        "ПЛАН_ИСПРАВЛЕНИЙ_СИСТЕМНЫХ_ПРОБЛЕМ_26_12_2025.md",
        "ПЛАН_ОПТИМИЗАЦИИ_ГЕНЕРАЦИИ_СИГНАЛОВ.md",
        "ПЛАН_УЛУЧШЕНИЯ_ЛОГИРОВАНИЯ.md",
        "ТОЧНЫЙ_ПЛАН_ИСПРАВЛЕНИЙ.md",
        "ФИНАЛЬНЫЙ_ТОЧНЫЙ_ПЛАН.md",
        "TODO_АРХИТЕКТУРНЫЕ_ИЗМЕНЕНИЯ_26_12_2025.md",
        "FINAL_TASK_LIST.md",
    ]
    
    for file in plans_files:
        move_file(file, f"docs/plans/2025-12/{file}")
    
    # Архитектура
    architecture_files = [
        "АРХИТЕКТУРА_АДАПТИВНОЙ_СИСТЕМЫ_ФИЛЬТРОВ.md",
        "АРХИТЕКТУРА_АДАПТИВНОЙ_СИСТЕМЫ_ФИЛЬТРОВ_V2.md",
        "СХЕМА_АРХИТЕКТУРНЫХ_ИЗМЕНЕНИЙ_26_12_2025.md",
        "СХЕМА_СТРУКТУРЫ_ЛОГОВ.md",
        "TECHNICAL_SPECIFICATION.md",
    ]
    
    for file in architecture_files:
        move_file(file, f"docs/architecture/{file}")
    
    # Реализация
    implementation_files = [
        "РЕАЛИЗАЦИЯ_АДАПТИВНОЙ_СИСТЕМЫ_ФИЛЬТРОВ.md",
        "РЕАЛИЗАЦИЯ_АДАПТИВНЫХ_PH_И_PROFIT_DRAWDOWN.md",
        "РЕАЛИЗАЦИЯ_КОМПРОМИССОВ_ГРОКА_2025-12-21.md",
        "РЕАЛИЗАЦИЯ_КРИТИЧЕСКИХ_УЛУЧШЕНИЙ_ЛОГИРОВАНИЯ.md",
        "РЕАЛИЗАЦИЯ_ОПТИМИЗАЦИИ_TCC_2025-12-21.md",
        "РЕАЛИЗАЦИЯ_ОПТИМИЗАЦИИ_ГЕНЕРАЦИИ_СИГНАЛОВ.md",
        "РЕАЛИЗАЦИЯ_ОПТИМИЗАЦИЙ_ГРОКА_2025-12-21.md",
        "РЕАЛИЗАЦИЯ_ФИКСОВ_ГРОКА_ПРОСКАЛЬЗЫВАНИЕ_2025-12-21.md",
        "РЕАЛИЗОВАНО_КРИТИЧЕСКИЕ_УЛУЧШЕНИЯ_ЛОГИРОВАНИЯ.md",
    ]
    
    for file in implementation_files:
        move_file(file, f"docs/fixes/completed/2025-12/implementation/{file}")
    
    # Отчеты
    reports_files = [
        "ИТОГОВОЕ_РЕЗЮМЕ_ИСПРАВЛЕНИЙ_21_12_2025.md",
        "ИТОГОВЫЙ_ОТЧЕТ_ОПТИМИЗАЦИЙ_TCC_2025-12-21.md",
        "РЕЗУЛЬТАТЫ_ОПТИМИЗАЦИИ_ПРОИЗВОДИТЕЛЬНОСТИ.md",
        "РЕЗЮМЕ_ИСПРАВЛЕНИЙ_21_12_2025.md",
        "РЕЗЮМЕ_ИСПРАВЛЕНИЙ_ПО_ГРОКУ_2025-12-21.md",
        "СПИСОК_ИСПРАВЛЕНИЙ_26_12_2025.md",
        "СТАТУС_ИСПРАВЛЕНИЙ.md",
        "EXIT_DECISIONS_2025-12-21.md",
        "РЕОРГАНИЗАЦИЯ_SUCCESS_REPORT.md",
    ]
    
    for file in reports_files:
        move_file(file, f"docs/reports/2025-12/{file}")
    
    # Проверки
    checks_files = [
        "ПРОВЕРКА_АНАЛИЗА_ГРОКА_ADX.md",
        "ПРОВЕРКА_АНАЛИЗА_ГРОКА_ПОЛНЫЙ.md",
        "ПРОВЕРКА_ВСЕХ_ИСПРАВЛЕНИЙ_26_12_2025.md",
        "ПРОВЕРКА_КОНФИГА_25_12_2025.md",
        "ПРОВЕРКА_ЛОГИКИ_РЕЖИМОВ_26_12_2025.md",
        "ПРОВЕРКА_НОВЫХ_ЛОГОВ_ПОСЛЕ_ОТКРЫТИЯ.md",
        "ПРОВЕРКА_РЕКОМЕНДАЦИЙ_ГРОКА_2025-12-21.md",
        "ПРОВЕРКА_ЧЕКЛИСТА_ГРОКА_2025-12-21.md",
        "ФИНАЛЬНАЯ_ПРОВЕРКА_ПЕРЕД_ЗАПУСКОМ_2025-12-21.md",
    ]
    
    for file in checks_files:
        move_file(file, f"docs/fixes/completed/2025-12/checks/{file}")
    
    # Оптимизация
    optimization_files = [
        "ОПТИМИЗАЦИЯ_TCC_CYCLE_2025-12-21.md",
        "УЛУЧШЕНИЕ_АДАПТИВНОСТИ_SL_TP_2025-12-21.md",
    ]
    
    for file in optimization_files:
        move_file(file, f"docs/fixes/completed/2025-12/optimization/{file}")
    
    # Справочники
    reference_files = [
        "СПИСОК_ФАЙЛОВ_ДЛЯ_АНАЛИЗА.md",
        "КЛЮЧЕВЫЕ_ФРАГМЕНТЫ_КОДА.md",
    ]
    
    for file in reference_files:
        move_file(file, f"docs/reference/{file}")
    
    # Логи
    logs_files = [
        "ЛОГИ_ДЛЯ_ГРОКА_2025-12-21.md",
        "ЛОГИ_ПОСЛЕДНИЙ_ЧАС_ДЛЯ_КИМИ.md",
        "ЛОГИРОВАНИЕ_TA_LIB_2025-12-21.md",
    ]
    
    for file in logs_files:
        move_file(file, f"docs/analysis/logs/2025-12/{file}")
    
    # Инструкции
    instruction_files = [
        "ИНСТРУКЦИЯ_ПОСЛЕ_ИСПРАВЛЕНИЙ.md",
    ]
    
    for file in instruction_files:
        move_file(file, f"docs/guides/{file}")
    
    # Q&A
    qa_files = [
        "ВОПРОСЫ_ПО_РЕКОМЕНДАЦИЯМ.md",
        "ОТВЕТ_НА_ДОПОЛНЕНИЕ_ГРОКА_ЛЕСТНИЦА.md",
        "ОТВЕТ_НА_ФИНАЛЬНЫЙ_АНАЛИЗ_ГРОКА.md",
    ]
    
    for file in qa_files:
        move_file(file, f"docs/analysis/qa/{file}")
    
    # Leverage
    leverage_files = [
        "LEVERAGE_SELECTION_MATH_AND_LOGGING.md",
        "LEVERAGE_UNIFICATION_AND_POSITION_SCALING.md",
        "LEVERAGE_VALIDATION_AND_ROUNDING.md",
        "PROBLEMS_ANALYSIS_LEVERAGE_DRIFT.md",
    ]
    
    for file in leverage_files:
        move_file(file, f"docs/analysis/leverage/{file}")
    
    # Аудиты
    audit_files = [
        "АУДИТ_ДЛЯ_ГРОКА_4.1.md",
        "КРИТИЧЕСКИЕ_ИСПРАВЛЕНИЯ_ПО_ЛОГАМ.md",
    ]
    
    for file in audit_files:
        move_file(file, f"docs/audit/2025-12/{file}")
    
    # Статусы
    status_files = [
        "СТАТУС_BTC_ПОЗИЦИИ.md",
    ]
    
    for file in status_files:
        move_file(file, f"docs/reports/status/{file}")
    
    # Python скрипты
    python_scripts = [
        "analyze_pnl_positions.py",
        "extract_and_analyze_logs.py",
    ]
    
    for file in python_scripts:
        move_file(file, f"scripts/analysis/{file}")
    
    # Утилиты
    utils_scripts = [
        "reorganize_root_files.py",
    ]
    
    for file in utils_scripts:
        move_file(file, f"scripts/utils/{file}")
    
    # Текстовые файлы
    text_files = [
        "project_structure.txt",
    ]
    
    for file in text_files:
        move_file(file, f"docs/architecture/{file}")
    
    # Изображения
    image_files = [
        "mathematical_expectancy.png",
        "pairs_comparison.png",
        "problems_analysis.png",
        "risk_analysis.png",
    ]
    
    for file in image_files:
        move_file(file, f"docs/analysis/{file}")
    
    # Курсор промпты
    cursor_files = [
        "cursor_analysis_prompt.md",
    ]
    
    for file in cursor_files:
        move_file(file, f"docs/development/{file}")
    
    print()
    print("=" * 60)
    print("ОРГАНИЗАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 60)

if __name__ == "__main__":
    organize_documents()

