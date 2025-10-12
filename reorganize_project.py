#!/usr/bin/env python3
"""
Скрипт автоматической реорганизации проекта.

Создает новую модульную структуру и перемещает файлы.
"""

import os
import shutil
from pathlib import Path

def create_directory_structure():
    """Создать структуру папок"""
    
    print("📁 Создание структуры папок...")
    
    directories = [
        # Strategies
        "src/strategies/modules",
        
        # Indicators
        "src/indicators/advanced",
        
        # Filters
        "src/filters",
        
        # Risk
        "src/risk",
        
        # Utils
        "src/utils",
        
        # ML
        "src/ml",
        
        # Config
        "config",
        
        # Data
        "data/historical",
        "data/cache",
        
        # Backups
        "backups",
        
        # Tests
        "tests/unit",
        "tests/integration",
        "tests/backtest",
        
        # Scripts
        "scripts",
        
        # Docs
        "docs/current",
        "docs/guides",
        "docs/archive",
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {directory}")
    
    print()

def create_init_files():
    """Создать __init__.py файлы"""
    
    print("📄 Создание __init__.py файлов...")
    
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
        print(f"  ✅ {init_file}")
    
    print()

def move_documentation():
    """Переместить документацию"""
    
    print("📚 Перемещение документации...")
    
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
            print(f"  ✅ {doc} → docs/current/")
    
    # Руководства
    guides = [
        "КАК_РАБОТАТЬ_С_GITHUB.md",
        "GITHUB_DESKTOP_ИНСТРУКЦИЯ.md",
    ]
    
    for guide in guides:
        if Path(guide).exists():
            shutil.move(guide, f"docs/guides/{guide}")
            print(f"  ✅ {guide} → docs/guides/")
    
    # Архив (старая документация)
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
            print(f"  ✅ {doc} → docs/archive/")
    
    print()

def move_config():
    """Переместить конфигурацию"""
    
    print("⚙️ Перемещение конфигурации...")
    
    if Path("config.yaml").exists():
        shutil.copy("config.yaml", "config/config.yaml")
        print("  ✅ config.yaml → config/config.yaml (скопировано)")
        print("  ⚠️ Оригинал оставлен для обратной совместимости")
    
    print()

def move_tests():
    """Переместить тесты"""
    
    print("🧪 Перемещение тестов...")
    
    if Path("test_okx_signature.py").exists():
        shutil.move("test_okx_signature.py", "tests/integration/test_okx_signature.py")
        print("  ✅ test_okx_signature.py → tests/integration/")
    
    print()

def cleanup_junk():
    """Удалить мусорные файлы"""
    
    print("🗑️ Удаление мусора...")
    
    # Дубликат репозитория
    if Path("1").exists():
        print("  ⚠️ Найдена папка '1/' (дубликат репозитория)")
        response = input("    Удалить? (y/n): ")
        if response.lower() == 'y':
            shutil.rmtree("1")
            print("  ✅ Папка '1/' удалена")
    
    # Мусорный файл
    junk_file = "zxcvhgjfhdgsadsgdhfjklj;hgf.txt"
    if Path(junk_file).exists():
        Path(junk_file).unlink()
        print(f"  ✅ {junk_file} удален")
    
    print()

def create_new_configs():
    """Создать новые конфигурационные файлы"""
    
    print("⚙️ Создание новых конфигураций...")
    
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
    print("  ✅ config/features.yaml создан")
    
    print()

def create_gitignore_updates():
    """Обновить .gitignore"""
    
    print("🚫 Обновление .gitignore...")
    
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

# Mypy
.mypy_cache/
"""
    
    with open(".gitignore", "a", encoding="utf-8") as f:
        f.write(additions)
    print("  ✅ .gitignore обновлен")
    
    print()

def print_summary():
    """Вывести итоговую сводку"""
    
    print("=" * 70)
    print("✅ РЕОРГАНИЗАЦИЯ ЗАВЕРШЕНА!")
    print("=" * 70)
    print()
    print("📊 Создано:")
    print("  - 18 новых папок")
    print("  - 11 __init__.py файлов")
    print("  - 1 features.yaml")
    print()
    print("📁 Перемещено:")
    print("  - Документация → docs/ (30+ файлов)")
    print("  - Конфигурация → config/")
    print("  - Тесты → tests/")
    print()
    print("🗑️ Очищено:")
    print("  - Дубликат репозитория (1/)")
    print("  - Мусорные файлы")
    print()
    print("🎯 Следующие шаги:")
    print("  1. Проверить структуру: ls -la src/")
    print("  2. Commit изменения: git add . && git commit -m 'Project reorganization'")
    print("  3. Push на GitHub: git push")
    print("  4. Начать Phase 1: добавление модулей")
    print()
    print("📚 Документация:")
    print("  - CODING_STANDARDS.md - правила кодирования")
    print("  - PROJECT_RULES.md - правила проекта")
    print("  - docs/current/ - актуальная документация")
    print()
    print("🚀 Готово к разработке!")
    print("=" * 70)

def main():
    """Главная функция"""
    
    print()
    print("=" * 70)
    print("🗂️ АВТОМАТИЧЕСКАЯ РЕОРГАНИЗАЦИЯ ПРОЕКТА")
    print("=" * 70)
    print()
    print("⚠️ ВНИМАНИЕ: Скрипт переместит файлы и создаст новые папки!")
    print()
    
    response = input("Продолжить? (y/n): ")
    if response.lower() != 'y':
        print("Отменено.")
        return
    
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
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        print("Реорганизация не завершена!")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

