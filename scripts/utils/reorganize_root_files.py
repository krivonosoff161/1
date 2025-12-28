#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для реорганизации файлов в корне проекта
Перемещает MD файлы в docs/archive/root/ по категориям
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

# Корневая директория проекта
ROOT = Path(__file__).parent

# Базовый путь архива
ARCHIVE_BASE = ROOT / "docs" / "archive" / "root"

# Файлы, которые остаются в корне
KEEP_IN_ROOT = {
    "README.md",
    "TECHNICAL_SPECIFICATION.md",
    "ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md",
}

# Категории файлов
ANALYSIS_FILES = [
    "ANALYSIS_CLOSING_PRICE.md",
    "ANALYSIS_DATA_FOR_KIMI.md",
    "ANALYSIS_EXITANALYZER_PARAMETERS.md",
    "ANALYSIS_LIMIT_ORDER_PRICE_PROBLEM.md",
    "ANALYSIS_NEGATIVE_CLOSES_END_SESSION.md",
    "ANALYSIS_REPORT_2025-12-08.md",
    "ANALYSIS_SIGNATURES_INTERPRETATIONS.md",
    "ANALYSIS_SMALL_PROFIT_EARLY_EXIT.md",
    "ANALYSIS_STAGE2_FOR_KIMI.md",
    "ANALYSIS_STRATEGY_PLACEMENT_CLOSING.md",
    "ANALYSIS_TIMEOUT_VS_EXITANALYZER.md",
    "COMPREHENSIVE_ANALYSIS_BROKER_MATH.md",
    "COMPREHENSIVE_ARCHIVE_ANALYSIS.md",
    "COMPREHENSIVE_BOT_ANALYSIS.md",
    "FINAL_COMPREHENSIVE_ANALYSIS.md",
    "PEAK_PROFIT_USD_ANALYSIS.md",
    "SCALPING_STRATEGIES_ANALYSIS.md",
    "TRADING_EXPERT_ANALYSIS.md",
    "TRENDS_METRICS_ECONOMY_2025-12-08.md",
]

FIXES_FILES = [
    "ALL_FIXES_COMPLETED_REPORT.md",
    "FIXES_2025-12-18.md",
    "FIXES_SMALL_PROFIT_EARLY_EXIT.md",
    "FIXES_STRATEGY_OPTIMIZATION.md",
    "SUMMARY_CLOSING_FIXES_APPLIED.md",
    "SUMMARY_EXITANALYZER_FIXES.md",
    "SUMMARY_FIXES_APPLIED.md",
    "SUMMARY_FIXES_INDENTATION.md",
    "SUMMARY_NEGATIVE_CLOSES_FIX.md",
    "SUMMARY_SIGNAL_PRICE_FIX.md",
    "SUMMARY_SYNTAX_FIXES.md",
    "SUMMARY_TRAILING_STOP_LOSS_FIX.md",
    "CORRECTION_SELL_LOGIC.md",
    "SOLUTION_SIGNAL_PRICE_FROM_ORDERBOOK.md",
]

AUDITS_FILES = [
    "AUDIT_BUNDLE_TASK_v1.3.md",
    "AUDIT_SUMMARY_2025-12-08.md",
    "FULL_AUDIT_REPORT_2025-12-08.md",
    "PROJECT_ROOT_AUDIT_REPORT.md",
    "DETAILED_MARKPX_ANALYSIS_2025-12-08.md",
    "UNINITIALIZED_MODULES_REPORT.md",
    "VERIFICATION_REPORT.md",
]

REPORTS_FILES = [
    "ALL_ERRORS_SUMMARY.md",
    "FINAL_AUDIT_DATA_FOR_KIMI.md",
    "FINAL_EXITANALYZER_ANALYSIS.md",
    "FINAL_INTEGRATION_REPORT.md",
    "FINAL_MASTER_PLAN.md",
    "FINAL_SOLUTIONS_PLAN.md",
    "FINAL_SUMMARY_ALL_FIXES.md",
    "LOG_CHECK_2025-12-18_23-00.md",
    "REFACTORING_COMPLETE_REPORT.md",
    "REORGANIZATION_COMPLETED.md",
    "SUMMARY_CLOSING_PRICE_ANALYSIS.md",
    "SUMMARY_EXITANALYZER_CHECK.md",
    "PARAMETERS_UPDATE_SUMMARY.md",
]

PLANS_FILES = [
    "MASTER_PLAN_FIXES.md",
    "MASTER_TODO_ALL_PROBLEMS.md",
    "TODO_MASTER_PLAN.md",
    "QUESTIONS_AND_PLAN.md",
    "RECOMMENDATION_TIMEOUT_REMOVAL.md",
]

MISC_FILES = [
    "SIGNAL_EXECUTION_BLOCKING_ANALYSIS.md",
    "archive_analysis_output.txt",
    "backtest_data_2025-12-17.json",
    "backtest_vs_reality_comparison.json",
    "improved_backtest_results.json",
    "FINAL_CORRECTIONS_2025-12-08.json",
    "signals_sample_50.csv",
    "tatus",
    "tatus --short",
]

PYTHON_SCRIPTS = [
    "analyze_archived_logs.py",
    "analyze_backtest_vs_reality.py",
    "analyze_position_closing_logic.py",
    "manual_log_analysis.py",
    "quick_analyze.py",
    "temp_analyze_today.py",
    "improved_backtest.py",
    "export_backtest_data.py",
]

# Структура папок
FOLDERS = {
    "analysis": ARCHIVE_BASE / "analysis",
    "fixes": ARCHIVE_BASE / "fixes",
    "audits": ARCHIVE_BASE / "audits",
    "reports": ARCHIVE_BASE / "reports",
    "plans": ARCHIVE_BASE / "plans",
    "misc": ARCHIVE_BASE / "misc",
    "python_scripts": ROOT / "scripts" / "analysis" / "root_scripts",
}

# Категории для перемещения
CATEGORIES = {
    "analysis": ANALYSIS_FILES,
    "fixes": FIXES_FILES,
    "audits": AUDITS_FILES,
    "reports": REPORTS_FILES,
    "plans": PLANS_FILES,
    "misc": MISC_FILES,
    "python_scripts": PYTHON_SCRIPTS,
}


def move_file_safe(source_path, dest_path):
    """Безопасно перемещает файл"""
    source = Path(source_path)
    dest = Path(dest_path)

    if not source.exists():
        return {"success": False, "message": f"Not found: {source.name}"}

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        return {"success": True, "message": f"Moved: {source.name}"}
    except Exception as e:
        return {"success": False, "message": f"Error moving {source.name}: {e}"}


def create_readme():
    """Создает README в архиве"""
    readme_content = f"""# ARCHIVE OF ROOT PROJECT FILES

This archive contains files that were moved from the project root during reorganization.

**Reorganization Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Structure

- **analysis/** - Analysis and research files ({len(ANALYSIS_FILES)} files)
- **fixes/** - Fix reports ({len(FIXES_FILES)} files)
- **audits/** - System audits ({len(AUDITS_FILES)} files)
- **reports/** - Work reports ({len(REPORTS_FILES)} files)
- **plans/** - Development plans ({len(PLANS_FILES)} files)
- **misc/** - Miscellaneous files (JSON, CSV, TXT) ({len(MISC_FILES)} files)

## Files that remained in root

- `README.md` - Main project instruction
- `TECHNICAL_SPECIFICATION.md` - Technical specification
- `ПОЛНОЕ_ОПИСАНИЕ_ТОРГОВОГО_БОТА.md` - Full bot description

## Python Scripts

Python analysis scripts were moved to `scripts/analysis/root_scripts/` ({len(PYTHON_SCRIPTS)} files)

## Statistics

- Total files moved: ~{sum(len(files) for files in CATEGORIES.values())}
- MD files: ~{len(ANALYSIS_FILES) + len(FIXES_FILES) + len(AUDITS_FILES) + len(REPORTS_FILES) + len(PLANS_FILES) + 1} (including misc MD)
- Python scripts: {len(PYTHON_SCRIPTS)}
- Data files: {len([f for f in MISC_FILES if f.endswith(('.json', '.csv', '.txt'))])}
"""

    readme_path = ARCHIVE_BASE / "README.md"
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"  [OK] Created README.md in archive")


def main():
    print("\n" + "=" * 60)
    print("  ROOT PROJECT FILES REORGANIZATION")
    print("=" * 60 + "\n")

    # Создаем структуру папок
    print("Creating folder structure...")
    for folder_name, folder_path in FOLDERS.items():
        folder_path.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] Created/verified: {folder_path}")
    print()

    # Перемещаем файлы по категориям
    moved_count = 0
    not_found_count = 0
    error_count = 0

    for category, files in CATEGORIES.items():
        if category == "python_scripts":
            print(f"Moving PYTHON SCRIPTS to scripts/analysis/root_scripts/...")
            dest_folder = FOLDERS[category]
        else:
            print(f"Moving {category.upper()} files...")
            dest_folder = FOLDERS[category]

        for file_name in files:
            source_path = ROOT / file_name
            dest_path = dest_folder / file_name

            result = move_file_safe(source_path, dest_path)
            if result["success"]:
                print(f"  [OK] {result['message']}")
                moved_count += 1
            elif "Not found" in result["message"]:
                print(f"  [SKIP] {result['message']}")
                not_found_count += 1
            else:
                print(f"  [ERROR] {result['message']}")
                error_count += 1
        print()

    # Перемещаем план реорганизации
    plan_file = ROOT / "ROOT_AUDIT_AND_REORGANIZATION_PLAN.md"
    if plan_file.exists():
        result = move_file_safe(plan_file, ARCHIVE_BASE / plan_file.name)
        if result["success"]:
            print(f"[OK] {result['message']}")
            moved_count += 1
        print()

    # Создаем README
    create_readme()

    # Итоговая статистика
    print("\n" + "=" * 60)
    print("  FINAL STATISTICS")
    print("=" * 60)
    print(f"  [OK] Files moved successfully: {moved_count}")
    print(f"  [SKIP] Files not found: {not_found_count}")
    print(f"  [ERROR] Errors: {error_count}")
    print(f"  [INFO] Files remaining in root (docs): {len(KEEP_IN_ROOT)}")
    print("=" * 60 + "\n")

    if error_count == 0:
        print("[SUCCESS] Reorganization completed successfully!")
        print(
            f"[INFO] See detailed plan in: {ARCHIVE_BASE / 'ROOT_AUDIT_AND_REORGANIZATION_PLAN.md'}\n"
        )
    else:
        print("[WARNING] Some errors occurred during reorganization.\n")


if __name__ == "__main__":
    main()
