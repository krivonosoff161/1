# -*- coding: utf-8 -*-
"""
Скрипт автоматической реорганизации проекта.
Создает новую модульную структуру и перемещает файлы.
"""

import os
import shutil
from pathlib import Path


def create_directory_structure():
    """Создать структуру папок"""

    print("\n[1/8] Создание структуры папок...")

    directories = [
        "src/strategies/modules",
        "src/indicators/advanced",
        "src/filters",
        "src/risk",
        "src/utils",
        "src/ml",
        "config",
        "data/historical",
        "data/cache",
        "backups",
        "tests/unit",
        "tests/integration",
        "tests/backtest",
        "scripts",
        "docs/current",
        "docs/guides",
        "docs/archive",
    ]

    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"  [OK] {directory}")

    print("  Создано: 18 папок\n")


def create_init_files():
    """Создать __init__.py файлы"""

    print("[2/8] Создание __init__.py файлов...")

    init_files = [
        "src/strategies/modules/__init__.py",
        "src/indicators/__init__.py",
        "src/indicators/advanced/__init__.py",
        "src/filters/__init__.py",
        "src/risk/__init__.py",
        "src/utils/__init__.py",
        "src/ml/__init__.py",
        "tests/__init__.py",
        "tests/unit/__init__.py",
        "tests/integration/__init__.py",
        "tests/backtest/__init__.py",
    ]

    for init_file in init_files:
        Path(init_file).touch()
        print(f"  [OK] {init_file}")

    print(f"  Создано: {len(init_files)} файлов\n")


def move_documentation():
    """Переместить документацию"""

    print("[3/8] Перемещение документации...")

    moved_count = 0

    # Актуальная документация
    current_docs = [
        "ГЛУБОКИЙ_АНАЛИЗ_СТРАТЕГИИ.md",
        "КОНЦЕПЦИЯ_ГИБРИДНОГО_БОТА.md",
        "ДЕТАЛЬНОЕ_ОПИСАНИЕ_МОДУЛЕЙ.md",
        "ПЛАН_МОДЕРНИЗАЦИИ_СТРАТЕГИИ.md",
        "СРАВНЕНИЕ_ДВУХ_ПРОЕКТОВ.md",
        "АРХИТЕКТУРА_ГИБРИДНОГО_ПРОЕКТА.md",
        "СХЕМА_АРХИТЕКТУРЫ_С_ОПИСАНИЯМИ.txt",
        "БЕЗОПАСНОСТЬ_DASHBOARD.md",
        "CHANGELOG_КРИТИЧЕСКИЕ_ИСПРАВЛЕНИЯ.md",
        "ИНСТРУКЦИЯ_ПОСЛЕ_ИСПРАВЛЕНИЙ.md",
        "ПЛАН_РЕОРГАНИЗАЦИИ_ПРОЕКТА.md",
    ]

    for doc in current_docs:
        if Path(doc).exists():
            shutil.move(doc, f"docs/current/{doc}")
            print(f"  [OK] {doc} -> docs/current/")
            moved_count += 1

    # Руководства
    guides = [
        "КАК_РАБОТАТЬ_С_GITHUB.md",
        "GITHUB_DESKTOP_ИНСТРУКЦИЯ.md",
    ]

    for guide in guides:
        if Path(guide).exists():
            shutil.move(guide, f"docs/guides/{guide}")
            print(f"  [OK] {guide} -> docs/guides/")
            moved_count += 1

    # Архив
    archive_docs = [
        "enhanced-trading-system.md",
        "implementation-roadmap.md",
        "installation-guide.md",
        "security-system.md",
        "strategy-documentation.md",
        "enhanced-scalping-strategy.py",
        "QUICK_START.txt",
        "SUMMARY_ИСПРАВЛЕНИЙ.txt",
        "БЫСТРЫЙ_СТАРТ.txt",
        "ИНСТРУКЦИЯ_ЗАПУСКА.md",
        "ИСПРАВЛЕНИЕ_ТОРГОВЛИ.md",
        "КАК_ИСПОЛЬЗОВАТЬ_BAT_ФАЙЛЫ.md",
        "НАСТРОЙКА_ЧАСТОТЫ_ТОРГОВЛИ.md",
        "НОВЫЙ_ФОРМАТ_ЛОГОВ.txt",
        "ПОЧЕМУ_SOLANA_ХОРОША.md",
        "ПРОВЕРКА_GITHUB.md",
        "ТЕКУЩИЕ_НАСТРОЙКИ.md",
        "ТОРГОВЫЕ_СЕССИИ.txt",
    ]

    for doc in archive_docs:
        if Path(doc).exists():
            shutil.move(doc, f"docs/archive/{doc}")
            print(f"  [OK] {doc} -> docs/archive/")
            moved_count += 1

    print(f"  Перемещено: {moved_count} файлов\n")


def move_config():
    """Переместить конфигурацию"""

    print("[4/8] Перемещение конфигурации...")

    if Path("config.yaml").exists():
        shutil.copy("config.yaml", "config/config.yaml")
        print("  [OK] config.yaml -> config/config.yaml (скопировано)")
        print("  [INFO] Оригинал оставлен для обратной совместимости")

    print()


def move_tests():
    """Переместить тесты"""

    print("[5/8] Перемещение тестов...")

    if Path("test_okx_signature.py").exists():
        shutil.move("test_okx_signature.py", "tests/integration/test_okx_signature.py")
        print("  [OK] test_okx_signature.py -> tests/integration/")
    else:
        print("  [INFO] test_okx_signature.py не найден")

    print()


def cleanup_junk():
    """Удалить мусорные файлы"""

    print("[6/8] Cleanup junk files...")

    # Дубликат репозитория (автоматически удаляем)
    if Path("1").exists() and Path("1").is_dir():
        print("  [WARN] Found folder '1/' (duplicate repository)")
        print("  [INFO] Removing automatically...")
        try:
            shutil.rmtree("1")
            print("  [OK] Folder '1/' removed")
        except Exception as e:
            print(f"  [ERROR] Could not remove '1/': {e}")

    # Мусорный файл
    junk_files = [
        "zxcvhgjfhdgsadsgdhfjklj;hgf.txt",
    ]

    for junk_file in junk_files:
        if Path(junk_file).exists():
            Path(junk_file).unlink()
            print(f"  [OK] {junk_file} удален")

    print()


def create_new_configs():
    """Создать новые конфигурационные файлы"""

    print("[7/8] Создание новых конфигураций...")

    # features.yaml
    features_content = """# Feature Flags - управление модулями

# Phase 1: Базовые улучшения
multi_timeframe_enabled: false
correlation_filter_enabled: false
time_based_filter_enabled: false
volatility_modes_enabled: false
pivot_points_enabled: false
volume_profile_enabled: false

# Phase 2: Продвинутые
order_book_enabled: false
liquidity_zones_enabled: false

# Phase 3: ML
kelly_criterion_enabled: false
rl_agent_enabled: false

# Phase 4: Гибрид
hybrid_mode_enabled: false
grid_trading_enabled: false

# Опционально
web_dashboard_enabled: false
auto_backups_enabled: false
"""

    with open("config/features.yaml", "w", encoding="utf-8") as f:
        f.write(features_content)
    print("  [OK] config/features.yaml создан")

    print()


def create_gitignore_updates():
    """Обновить .gitignore"""

    print("[8/8] Обновление .gitignore...")

    additions = """
# Data
data/cache/
data/historical/
*.db
*.db-journal

# Backups
backups/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Pytest
.pytest_cache/
htmlcov/
.coverage
"""

    # Проверяем что еще не добавлено
    with open(".gitignore", "r", encoding="utf-8") as f:
        current_content = f.read()

    if "data/cache/" not in current_content:
        with open(".gitignore", "a", encoding="utf-8") as f:
            f.write(additions)
        print("  [OK] .gitignore обновлен")
    else:
        print("  [SKIP] .gitignore уже содержит дополнения")

    print()


def print_summary():
    """Вывести итоговую сводку"""

    print("=" * 70)
    print("РЕОРГАНИЗАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 70)
    print()
    print("Создано:")
    print("  - 18 новых папок")
    print("  - 11 __init__.py файлов")
    print("  - config/features.yaml")
    print()
    print("Перемещено:")
    print("  - Документация -> docs/ (30+ файлов)")
    print("  - Конфигурация -> config/")
    print("  - Тесты -> tests/")
    print()
    print("Очищено:")
    print("  - Дубликат репозитория (1/)")
    print("  - Мусорные файлы")
    print()
    print("Следующие шаги:")
    print("  1. Проверить структуру: dir src (Windows) или ls -la src/ (Linux)")
    print("  2. Проверить бот: python run_bot.py")
    print("  3. Commit: git add . && git commit -m 'Project reorganization'")
    print("  4. Push: git push")
    print()
    print("Документация:")
    print("  - CODING_STANDARDS.md - правила кодирования")
    print("  - PROJECT_RULES.md - правила проекта")
    print("  - docs/current/ - актуальная документация")
    print()
    print("Готово к разработке!")
    print("=" * 70)


def main():
    """Главная функция"""

    print()
    print("=" * 70)
    print("REORGANIZACIJA PROEKTA")
    print("=" * 70)
    print()
    print("Starting automatic project reorganization...")
    print()

    try:
        # Шаг 1: Создание структуры
        create_directory_structure()

        # Шаг 2: __init__.py файлы
        create_init_files()

        # Шаг 3: Перемещение документации
        move_documentation()

        # Шаг 4: Конфигурация
        move_config()

        # Шаг 5: Тесты
        move_tests()

        # Шаг 6: Новые конфиги
        create_new_configs()

        # Шаг 7: .gitignore
        create_gitignore_updates()

        # Шаг 8: Очистка (опционально)
        cleanup_junk()

        # Итоговая сводка
        print_summary()

        return 0

    except Exception as e:
        print(f"\n[ERROR] Ошибка: {e}")
        print("Реорганизация не завершена!")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
