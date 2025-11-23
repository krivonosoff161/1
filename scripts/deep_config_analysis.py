#!/usr/bin/env python3
"""
Глубокий анализ конфигурационных файлов на структурные проблемы.
Проверяет:
1. Дублирование ключей на всех уровнях
2. Порядок ключей (enabled должен быть перед вложенными секциями)
3. Соответствие структуры ожиданиям кода
4. Неправильное расположение секций
"""

import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple
import yaml
from collections import OrderedDict

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class DeepConfigAnalyzer:
    """Глубокий анализатор конфигураций"""
    
    def __init__(self):
        self.issues: List[Dict[str, Any]] = []
        self.checked_files: List[str] = []
    
    def analyze_yaml_structure(self, file_path: Path, content: Dict, path: str = "") -> None:
        """Рекурсивный анализ структуры YAML"""
        if not isinstance(content, dict):
            return
        
        # Проверяем порядок ключей
        keys = list(content.keys())
        enabled_idx = None
        nested_sections = []
        
        for i, key in enumerate(keys):
            value = content[key]
            if key == "enabled":
                enabled_idx = i
            elif isinstance(value, dict):
                nested_sections.append((i, key))
        
        # Если enabled идет ПОСЛЕ вложенных секций - это потенциальная проблема
        if enabled_idx is not None:
            for nested_idx, nested_key in nested_sections:
                if nested_idx < enabled_idx:
                    # Проверяем, есть ли enabled во вложенной секции
                    nested_dict = content[nested_key]
                    if isinstance(nested_dict, dict) and "enabled" in nested_dict:
                        full_path = f"{path}.{nested_key}" if path else nested_key
                        self.issues.append({
                            "file": str(file_path),
                            "type": "enabled_order",
                            "severity": "warning",
                            "path": full_path,
                            "message": f"Ключ 'enabled' находится после вложенной секции '{nested_key}' с собственным 'enabled'. Рекомендуется разместить 'enabled' перед вложенными секциями."
                        })
        
        # Рекурсивно проверяем вложенные словари
        for key, value in content.items():
            if isinstance(value, dict):
                new_path = f"{path}.{key}" if path else key
                self.analyze_yaml_structure(file_path, value, new_path)
    
    def check_code_expectations(self, file_path: Path, content: Dict) -> None:
        """Проверка соответствия ожиданиям кода"""
        if file_path.name != "config_futures.yaml":
            return
        
        # Проверяем position_manager
        if "scalping" in content:
            scalping = content["scalping"]
            if isinstance(scalping, dict):
                # Код ожидает scalping.position_manager
                if "position_manager" not in scalping:
                    # Проверяем другие возможные расположения
                    if "position_manager" in content:
                        self.issues.append({
                            "file": str(file_path),
                            "type": "wrong_location",
                            "severity": "error",
                            "path": "position_manager",
                            "message": "position_manager находится на верхнем уровне, но код ожидает scalping.position_manager"
                        })
                    elif "futures_modules" in content:
                        futures_modules = content["futures_modules"]
                        if isinstance(futures_modules, dict) and "position_manager" in futures_modules:
                            self.issues.append({
                                "file": str(file_path),
                                "type": "wrong_location",
                                "severity": "error",
                                "path": "futures_modules.position_manager",
                                "message": "position_manager находится в futures_modules, но код ожидает scalping.position_manager"
                            })
        
        # Проверяем order_executor
        if "scalping" in content:
            scalping = content["scalping"]
            if isinstance(scalping, dict):
                if "order_executor" not in scalping:
                    if "order_executor" in content:
                        self.issues.append({
                            "file": str(file_path),
                            "type": "wrong_location",
                            "severity": "error",
                            "path": "order_executor",
                            "message": "order_executor находится на верхнем уровне, но код ожидает scalping.order_executor"
                        })
                    elif "futures_modules" in content:
                        futures_modules = content["futures_modules"]
                        if isinstance(futures_modules, dict) and "order_executor" in futures_modules:
                            self.issues.append({
                                "file": str(file_path),
                                "type": "wrong_location",
                                "severity": "warning",
                                "path": "futures_modules.order_executor",
                                "message": "order_executor находится в futures_modules, но код ожидает scalping.order_executor"
                            })
    
    def check_duplicate_keys(self, file_path: Path) -> List[Dict]:
        """Проверка дублирования ключей через парсинг сырого текста"""
        issues = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Простая проверка на дублирование ключей на одном уровне отступов
            stack = []  # Стек уровней вложенности
            seen_keys = {}  # Словарь: уровень -> множество ключей
            
            for line_num, line in enumerate(lines, 1):
                stripped = line.lstrip()
                if not stripped or stripped.startswith('#'):
                    continue
                
                # Определяем уровень вложенности по отступам
                indent = len(line) - len(stripped)
                level = indent // 2  # Предполагаем 2 пробела на уровень
                
                # Извлекаем ключ (до двоеточия)
                if ':' in stripped:
                    key = stripped.split(':')[0].strip()
                    if key:
                        if level not in seen_keys:
                            seen_keys[level] = {}
                        
                        # Проверяем дублирование на текущем уровне
                        if key in seen_keys[level]:
                            prev_line = seen_keys[level][key]
                            issues.append({
                                "file": str(file_path),
                                "type": "duplicate_key",
                                "severity": "error",
                                "path": f"line {line_num}",
                                "message": f"Дублирование ключа '{key}' на уровне {level} (первое вхождение: строка {prev_line}, второе: строка {line_num})"
                            })
                        else:
                            seen_keys[level][key] = line_num
        except Exception as e:
            issues.append({
                "file": str(file_path),
                "type": "analysis_error",
                "severity": "warning",
                "path": "",
                "message": f"Ошибка анализа файла: {e}"
            })
        
        return issues
    
    def analyze_file(self, file_path: Path) -> bool:
        """Анализ одного файла"""
        self.checked_files.append(str(file_path))
        
        # Загружаем YAML
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f)
        except Exception as e:
            self.issues.append({
                "file": str(file_path),
                "type": "yaml_error",
                "severity": "error",
                "path": "",
                "message": f"Ошибка парсинга YAML: {e}"
            })
            return False
        
        if not isinstance(content, dict):
            return True
        
        # Проверка дублирования ключей
        duplicate_issues = self.check_duplicate_keys(file_path)
        self.issues.extend(duplicate_issues)
        
        # Анализ структуры
        self.analyze_yaml_structure(file_path, content)
        
        # Проверка соответствия ожиданиям кода
        self.check_code_expectations(file_path, content)
        
        return len([i for i in duplicate_issues if i["severity"] == "error"]) == 0
    
    def analyze_all(self, config_dir: Path = None) -> bool:
        """Анализ всех YAML файлов"""
        if config_dir is None:
            config_dir = project_root / "config"
        
        if not config_dir.exists():
            print(f"❌ Директория {config_dir} не найдена")
            return False
        
        yaml_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        
        if not yaml_files:
            print(f"⚠️ YAML файлы не найдены в {config_dir}")
            return True
        
        print(f"🔍 Глубокий анализ {len(yaml_files)} YAML файлов...\n")
        
        all_valid = True
        for yaml_file in sorted(yaml_files):
            print(f"  Анализ {yaml_file.name}...", end=" ")
            is_valid = self.analyze_file(yaml_file)
            if is_valid:
                print("✅")
            else:
                print("❌")
                all_valid = False
        
        return all_valid
    
    def print_report(self):
        """Вывод отчета"""
        print("\n" + "="*80)
        print("📊 ОТЧЕТ О ГЛУБОКОМ АНАЛИЗЕ КОНФИГУРАЦИЙ")
        print("="*80)
        
        print(f"\n✅ Проверено файлов: {len(self.checked_files)}")
        
        errors = [i for i in self.issues if i["severity"] == "error"]
        warnings = [i for i in self.issues if i["severity"] == "warning"]
        
        print(f"❌ Ошибок: {len(errors)}")
        print(f"⚠️  Предупреждений: {len(warnings)}")
        
        if errors:
            print("\n" + "="*80)
            print("❌ КРИТИЧЕСКИЕ ОШИБКИ:")
            print("="*80)
            for i, error in enumerate(errors, 1):
                print(f"\n{i}. {error['file']}")
                print(f"   Тип: {error['type']}")
                print(f"   Путь: {error['path']}")
                print(f"   Сообщение: {error['message']}")
        
        if warnings:
            print("\n" + "="*80)
            print("⚠️  ПРЕДУПРЕЖДЕНИЯ:")
            print("="*80)
            for i, warning in enumerate(warnings, 1):
                print(f"\n{i}. {warning['file']}")
                print(f"   Тип: {warning['type']}")
                print(f"   Путь: {warning['path']}")
                print(f"   Сообщение: {warning['message']}")
        
        if not errors and not warnings:
            print("\n✅ Все конфигурационные файлы прошли глубокий анализ!")
        else:
            print(f"\n📋 Итого найдено проблем: {len(errors)} ошибок, {len(warnings)} предупреждений")
        
        print("\n" + "="*80)


def main():
    """Главная функция"""
    analyzer = DeepConfigAnalyzer()
    
    config_dir = project_root / "config"
    is_valid = analyzer.analyze_all(config_dir)
    
    analyzer.print_report()
    
    sys.exit(0 if is_valid and len([i for i in analyzer.issues if i["severity"] == "error"]) == 0 else 1)


if __name__ == "__main__":
    main()

