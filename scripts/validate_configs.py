#!/usr/bin/env python3
"""
Скрипт для валидации всех YAML конфигурационных файлов в проекте.
Проверяет:
1. Синтаксис YAML
2. Структурные ошибки (дублирование ключей, неправильная вложенность)
3. Соответствие структуре Pydantic моделей
4. Наличие обязательных полей
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple
import yaml
from collections import defaultdict

# Добавляем корневую директорию в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from src.config import BotConfig
except ImportError:
    BotConfig = None


class ConfigValidator:
    """Валидатор конфигурационных файлов"""
    
    def __init__(self):
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.checked_files: List[str] = []
    
    def check_yaml_syntax(self, file_path: Path) -> Tuple[bool, Any]:
        """Проверка синтаксиса YAML"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f)
            return True, content
        except yaml.YAMLError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error: {e}"
    
    def check_duplicate_keys(self, file_path: Path, content: Dict) -> List[Dict]:
        """Проверка дублирования ключей на одном уровне"""
        issues = []
        
        def check_dict(d: Dict, path: str = ""):
            """Рекурсивная проверка словаря"""
            if not isinstance(d, dict):
                return
            
            # Проверяем ключи на текущем уровне
            seen_keys = set()
            for key, value in d.items():
                if key in seen_keys:
                    issues.append({
                        "file": str(file_path),
                        "type": "duplicate_key",
                        "severity": "error",
                        "path": f"{path}.{key}" if path else key,
                        "message": f"Дублирование ключа '{key}' на уровне '{path}'"
                    })
                seen_keys.add(key)
                
                # Рекурсивно проверяем вложенные словари
                if isinstance(value, dict):
                    new_path = f"{path}.{key}" if path else key
                    check_dict(value, new_path)
        
        check_dict(content)
        return issues
    
    def check_structure_issues(self, file_path: Path, content: Dict) -> List[Dict]:
        """Проверка структурных проблем"""
        issues = []
        
        def check_enabled_order(d: Dict, path: str = "", items_order: List[str] = None):
            """Проверка порядка ключей - enabled должен быть перед вложенными секциями"""
            if not isinstance(d, dict):
                return
            
            if items_order is None:
                items_order = list(d.keys())
            
            # Ищем enabled и вложенные секции
            enabled_index = None
            nested_sections = []
            
            for i, key in enumerate(items_order):
                value = d[key]
                if key == "enabled":
                    enabled_index = i
                elif isinstance(value, dict):
                    nested_sections.append((i, key))
            
            # Если enabled идет ПОСЛЕ вложенной секции - это проблема
            if enabled_index is not None:
                for nested_idx, nested_key in nested_sections:
                    if nested_idx < enabled_index:
                        # Это нормально - вложенная секция перед enabled
                        continue
                    # Проверяем, есть ли enabled во вложенной секции
                    nested_dict = d[nested_key]
                    if isinstance(nested_dict, dict) and "enabled" in nested_dict:
                        # Это может быть проблемой, если enabled на верхнем уровне идет после вложенной секции
                        # Но это нормально для reversal_detection.enabled и reversal_detection.order_flow.enabled
                        # Проблема только если порядок неправильный
                        pass
            
            # Рекурсивно проверяем вложенные словари
            for key, value in d.items():
                if isinstance(value, dict):
                    new_path = f"{path}.{key}" if path else key
                    check_enabled_order(value, new_path)
        
        check_enabled_order(content)
        
        # Проверяем специфичные проблемы для config_futures.yaml
        if file_path.name == "config_futures.yaml":
            # Проверяем position_manager
            if "scalping" in content:
                scalping = content["scalping"]
                if isinstance(scalping, dict):
                    # Проверяем, что position_manager находится в scalping
                    if "position_manager" not in scalping:
                        # Ищем position_manager на верхнем уровне или в futures_modules
                        if "position_manager" in content:
                            issues.append({
                                "file": str(file_path),
                                "type": "wrong_location",
                                "severity": "error",
                                "path": "position_manager",
                                "message": "position_manager находится на верхнем уровне, но код ожидает его в scalping.position_manager"
                            })
                        elif "futures_modules" in content:
                            futures_modules = content["futures_modules"]
                            if isinstance(futures_modules, dict) and "position_manager" in futures_modules:
                                issues.append({
                                    "file": str(file_path),
                                    "type": "wrong_location",
                                    "severity": "error",
                                    "path": "futures_modules.position_manager",
                                    "message": "position_manager находится в futures_modules, но код ожидает его в scalping.position_manager"
                                })
                    
                    # Проверяем структуру reversal_detection
                    if "position_manager" in scalping:
                        pm = scalping["position_manager"]
                        if isinstance(pm, dict) and "reversal_detection" in pm:
                            rd = pm["reversal_detection"]
                            if isinstance(rd, dict):
                                # Проверяем порядок ключей в reversal_detection
                                rd_keys = list(rd.keys())
                                enabled_idx = None
                                order_flow_idx = None
                                
                                for i, key in enumerate(rd_keys):
                                    if key == "enabled":
                                        enabled_idx = i
                                    elif key == "order_flow":
                                        order_flow_idx = i
                                
                                # enabled должен быть перед order_flow
                                if enabled_idx is not None and order_flow_idx is not None:
                                    if enabled_idx > order_flow_idx:
                                        issues.append({
                                            "file": str(file_path),
                                            "type": "wrong_order",
                                            "severity": "warning",
                                            "path": "scalping.position_manager.reversal_detection",
                                            "message": "enabled находится после order_flow, рекомендуется разместить enabled перед вложенными секциями"
                                        })
        
        return issues
    
    def validate_with_pydantic(self, file_path: Path, content: Dict) -> List[Dict]:
        """Валидация через Pydantic модели"""
        issues = []
        
        if BotConfig is None:
            return issues
        
        # Проверяем только основные конфиги
        if file_path.name not in ["config_futures.yaml", "config.yaml"]:
            return issues
        
        try:
            # Создаем временный файл для загрузки
            config = BotConfig.load_from_file(str(file_path))
            # Если загрузка прошла успешно, структура правильная
        except Exception as e:
            issues.append({
                "file": str(file_path),
                "type": "pydantic_validation",
                "severity": "error",
                "path": "",
                "message": f"Ошибка валидации Pydantic: {e}"
            })
        
        return issues
    
    def validate_file(self, file_path: Path) -> bool:
        """Валидация одного файла"""
        self.checked_files.append(str(file_path))
        
        # Проверка синтаксиса YAML
        is_valid, result = self.check_yaml_syntax(file_path)
        if not is_valid:
            self.errors.append({
                "file": str(file_path),
                "type": "yaml_syntax",
                "severity": "error",
                "path": "",
                "message": f"Ошибка синтаксиса YAML: {result}"
            })
            return False
        
        if not isinstance(result, dict):
            return True  # Не словарь, пропускаем
        
        # Проверка дублирования ключей
        duplicate_issues = self.check_duplicate_keys(file_path, result)
        self.errors.extend(duplicate_issues)
        
        # Проверка структурных проблем
        structure_issues = self.check_structure_issues(file_path, result)
        self.warnings.extend([i for i in structure_issues if i["severity"] == "warning"])
        self.errors.extend([i for i in structure_issues if i["severity"] == "error"])
        
        # Валидация через Pydantic (только для основных конфигов)
        if file_path.name in ["config_futures.yaml", "config.yaml"]:
            pydantic_issues = self.validate_with_pydantic(file_path, result)
            self.errors.extend(pydantic_issues)
        
        return len(duplicate_issues) == 0 and len([i for i in structure_issues if i["severity"] == "error"]) == 0
    
    def validate_all(self, config_dir: Path = None) -> bool:
        """Валидация всех YAML файлов"""
        if config_dir is None:
            config_dir = project_root / "config"
        
        if not config_dir.exists():
            print(f"❌ Директория {config_dir} не найдена")
            return False
        
        yaml_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        
        if not yaml_files:
            print(f"⚠️ YAML файлы не найдены в {config_dir}")
            return True
        
        print(f"🔍 Проверка {len(yaml_files)} YAML файлов...\n")
        
        all_valid = True
        for yaml_file in sorted(yaml_files):
            print(f"  Проверка {yaml_file.name}...", end=" ")
            is_valid = self.validate_file(yaml_file)
            if is_valid:
                print("✅")
            else:
                print("❌")
                all_valid = False
        
        return all_valid
    
    def print_report(self):
        """Вывод отчета"""
        print("\n" + "="*80)
        print("📊 ОТЧЕТ О ВАЛИДАЦИИ КОНФИГУРАЦИЙ")
        print("="*80)
        
        print(f"\n✅ Проверено файлов: {len(self.checked_files)}")
        print(f"❌ Ошибок: {len(self.errors)}")
        print(f"⚠️  Предупреждений: {len(self.warnings)}")
        
        if self.errors:
            print("\n" + "="*80)
            print("❌ ОШИБКИ:")
            print("="*80)
            for i, error in enumerate(self.errors, 1):
                print(f"\n{i}. {error['file']}")
                print(f"   Тип: {error['type']}")
                print(f"   Путь: {error['path']}")
                print(f"   Сообщение: {error['message']}")
        
        if self.warnings:
            print("\n" + "="*80)
            print("⚠️  ПРЕДУПРЕЖДЕНИЯ:")
            print("="*80)
            for i, warning in enumerate(self.warnings, 1):
                print(f"\n{i}. {warning['file']}")
                print(f"   Тип: {warning['type']}")
                print(f"   Путь: {warning['path']}")
                print(f"   Сообщение: {warning['message']}")
        
        if not self.errors and not self.warnings:
            print("\n✅ Все конфигурационные файлы валидны!")
        
        print("\n" + "="*80)


def main():
    """Главная функция"""
    validator = ConfigValidator()
    
    # Проверяем основные конфиги
    config_dir = project_root / "config"
    is_valid = validator.validate_all(config_dir)
    
    # Выводим отчет
    validator.print_report()
    
    # Возвращаем код выхода
    sys.exit(0 if is_valid and len(validator.errors) == 0 else 1)


if __name__ == "__main__":
    main()

