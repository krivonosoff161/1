#!/usr/bin/env python3
"""
Скрипт для исправления импортов в тестах
"""

import os
import re


def fix_imports_in_file(filepath):
    """Исправляет импорты в одном файле"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Проверяем есть ли импорт src
        if "from src." in content and "sys.path.insert" not in content:
            print(f"Исправляем импорты в {os.path.basename(filepath)}")

            # Добавляем sys.path в начало
            new_content = (
                '''"""
Unit tests
"""

import sys
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

'''
                + content
            )

            # Записываем обратно
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True
        else:
            print(f"Пропускаем {os.path.basename(filepath)} - импорты уже исправлены")
            return False
    except Exception as e:
        print(f"Ошибка в {filepath}: {e}")
        return False


def fix_imports_in_directory(directory):
    """Исправляет импорты во всех файлах в папке"""
    fixed_count = 0

    for filename in os.listdir(directory):
        if filename.endswith(".py") and filename != "__init__.py":
            filepath = os.path.join(directory, filename)
            if fix_imports_in_file(filepath):
                fixed_count += 1

    return fixed_count


if __name__ == "__main__":
    # Исправляем unit тесты
    print("Исправляем unit тесты...")
    unit_fixed = fix_imports_in_directory("tests/unit")
    print(f"Исправлено {unit_fixed} unit тестов")

    # Исправляем integration тесты
    print("\nИсправляем integration тесты...")
    integration_fixed = fix_imports_in_directory("tests/integration")
    print(f"Исправлено {integration_fixed} integration тестов")

    print(f"\nВсего исправлено: {unit_fixed + integration_fixed} файлов")
