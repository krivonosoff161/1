"""
🔍 АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ

Скрипт для поиска всех мест, где индикаторы сохраняются и читаются,
и проверки единообразия форматов данных (dict vs scalar, ключи).
"""

import ast
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Индикаторы, которые должны быть dict (сложные)
COMPLEX_INDICATORS = {
    "macd": {"macd", "signal", "histogram"},
    "bollinger_bands": {"upper", "lower", "middle"},
    "bb": {"upper", "lower", "middle"},
}

# Индикаторы, которые должны быть scalar (простые)
SIMPLE_INDICATORS = {
    "rsi",
    "atr",
    "atr_14",
    "sma_20",
    "ema_12",
    "ema_26",
    "adx",
    "adx_plus_di",
    "adx_minus_di",
    "adx_proxy",
}

# Все возможные ключи индикаторов
ALL_INDICATOR_KEYS = SIMPLE_INDICATORS | set(COMPLEX_INDICATORS.keys())


class IndicatorAnalyzer(ast.NodeVisitor):
    """AST анализатор для поиска использования индикаторов"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.save_operations: List[Dict] = []  # update_indicators, update_indicator
        self.read_operations: List[Dict] = []  # get_indicators, get_indicator
        self.direct_access: List[Dict] = []  # .get("macd"), indicators["rsi"]
        self.current_line = 0

    def visit_Call(self, node):
        """Обработка вызовов функций"""
        self.current_line = node.lineno

        # Поиск update_indicators / update_indicator
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in ("update_indicators", "update_indicator"):
                self._analyze_save_operation(node)

            # Поиск get_indicators / get_indicator
            elif node.func.attr in ("get_indicators", "get_indicator"):
                self._analyze_read_operation(node)

            # Обработка .get() вызовов
            elif node.func.attr == "get":
                if isinstance(node.func.value, ast.Name):
                    var_name = node.func.value.id
                    if var_name in (
                        "indicators",
                        "indicators_from_registry",
                        "market_data",
                    ):
                        if node.args and isinstance(node.args[0], ast.Constant):
                            key = node.args[0].value
                            if isinstance(key, str) and any(
                                ind in key.lower() for ind in ALL_INDICATOR_KEYS
                            ):
                                self.direct_access.append(
                                    {
                                        "line": node.lineno,
                                        "type": "get",
                                        "key": key,
                                        "context": self._get_context(node),
                                    }
                                )

        self.generic_visit(node)

    def visit_Subscript(self, node):
        """Обработка обращений к словарям: indicators["key"]"""
        self.current_line = node.lineno

        if isinstance(node.value, ast.Name):
            if node.value.id in (
                "indicators",
                "indicators_from_registry",
                "market_data",
            ):
                if isinstance(node.slice, ast.Constant):
                    key = node.slice.value
                    if isinstance(key, str) and any(
                        ind in key.lower() for ind in ALL_INDICATOR_KEYS
                    ):
                        self.direct_access.append(
                            {
                                "line": node.lineno,
                                "type": "subscript",
                                "key": key,
                                "context": self._get_context(node),
                            }
                        )

        self.generic_visit(node)

    def _analyze_save_operation(self, node):
        """Анализ операций сохранения индикаторов"""
        if node.func.attr == "update_indicators":
            # update_indicators(symbol, indicators_dict)
            if len(node.args) >= 2:
                indicators_arg = node.args[1]
                keys = self._extract_dict_keys(indicators_arg)
                self.save_operations.append(
                    {
                        "line": node.lineno,
                        "method": "update_indicators",
                        "keys": keys,
                        "code": self._get_code_snippet(node),
                    }
                )
        elif node.func.attr == "update_indicator":
            # update_indicator(symbol, indicator_name, value)
            if len(node.args) >= 2:
                indicator_name = self._extract_string_value(node.args[1])
                self.save_operations.append(
                    {
                        "line": node.lineno,
                        "method": "update_indicator",
                        "keys": [indicator_name] if indicator_name else [],
                        "code": self._get_code_snippet(node),
                    }
                )

    def _analyze_read_operation(self, node):
        """Анализ операций чтения индикаторов"""
        self.read_operations.append(
            {
                "line": node.lineno,
                "method": node.func.attr,
                "code": self._get_code_snippet(node),
            }
        )

    def _extract_dict_keys(self, node) -> List[str]:
        """Извлечение ключей из dict"""
        keys = []
        if isinstance(node, ast.Dict):
            for key_node in node.keys:
                if isinstance(key_node, ast.Constant):
                    keys.append(key_node.value)
        elif isinstance(node, ast.Name):
            # Переменная - не можем определить ключи статически
            keys.append(f"<variable: {node.id}>")
        return keys

    def _extract_string_value(self, node) -> str:
        """Извлечение строкового значения"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return ""

    def _get_code_snippet(self, node, context_lines=2) -> str:
        """Получение фрагмента кода"""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                start = max(0, node.lineno - context_lines - 1)
                end = min(len(lines), node.lineno + context_lines)
                return "".join(lines[start:end])
        except:
            return ""

    def _get_context(self, node) -> str:
        """Получение контекста использования"""
        return self._get_code_snippet(node, context_lines=1)


def analyze_file(file_path: str) -> Dict:
    """Анализ одного файла"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content)
            analyzer = IndicatorAnalyzer(file_path)
            analyzer.visit(tree)

            return {
                "file": file_path,
                "saves": analyzer.save_operations,
                "reads": analyzer.read_operations,
                "direct_access": analyzer.direct_access,
            }
    except Exception as e:
        return {"file": file_path, "error": str(e)}


def find_all_python_files(root_dir: str) -> List[str]:
    """Поиск всех Python файлов"""
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        # Пропускаем служебные директории
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "venv", ".venv")]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def check_consistency(results: List[Dict]) -> Dict:
    """Проверка консистентности использования индикаторов"""
    issues = []

    # Собираем все ключи, которые сохраняются
    saved_keys: Dict[str, Set[str]] = defaultdict(set)
    for result in results:
        if "saves" in result:
            for save in result["saves"]:
                for key in save.get("keys", []):
                    if isinstance(key, str) and key:
                        saved_keys[result["file"]].add(key)

    # Собираем все ключи, которые читаются
    read_keys: Dict[str, Set[str]] = defaultdict(set)
    for result in results:
        if "direct_access" in result:
            for access in result["direct_access"]:
                key = access.get("key", "")
                if key:
                    read_keys[result["file"]].add(key)

    # Проверка MACD: должен быть dict, но может сохраняться как отдельные значения
    macd_issues = []
    for result in results:
        file = result["file"]
        # Проверяем сохранение MACD
        for save in result.get("saves", []):
            keys = save.get("keys", [])
            if "macd" in keys and "macd_signal" in keys and "macd_histogram" in keys:
                macd_issues.append(
                    {
                        "file": file,
                        "line": save["line"],
                        "issue": "MACD сохраняется как отдельные значения вместо dict",
                        "severity": "HIGH",
                        "code": save.get("code", "")[:200],
                    }
                )

        # Проверяем чтение MACD
        for access in result.get("direct_access", []):
            key = access.get("key", "")
            if key == "macd":
                # Проверяем, ожидается ли dict
                context = access.get("context", "")
                if "isinstance" in context and "dict" in context:
                    # Ожидается dict - это нормально
                    pass
                elif ".get(" in context and "histogram" in context:
                    macd_issues.append(
                        {
                            "file": file,
                            "line": access["line"],
                            "issue": "MACD читается как dict, но может быть сохранен как scalar",
                            "severity": "HIGH",
                            "code": context[:200],
                        }
                    )

    # Проверка ADX: должен быть единый ключ
    adx_keys_found = set()
    for result in results:
        for save in result.get("saves", []):
            for key in save.get("keys", []):
                if "adx" in key.lower():
                    adx_keys_found.add(key)

    adx_issues = []
    if len(adx_keys_found) > 1:
        adx_issues.append(
            {
                "issue": f"ADX сохраняется с разными ключами: {adx_keys_found}",
                "severity": "MEDIUM",
                "recommendation": "Унифицировать ключи: использовать только 'adx'",
            }
        )

    return {
        "macd_issues": macd_issues,
        "adx_issues": adx_issues,
        "saved_keys": dict(saved_keys),
        "read_keys": dict(read_keys),
    }


def main():
    """Главная функция"""
    print("🔍 АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ\n")

    # Ищем все Python файлы в src/strategies/scalping/futures
    root_dir = "src/strategies/scalping/futures"
    if not os.path.exists(root_dir):
        print(f"❌ Директория {root_dir} не найдена!")
        return

    files = find_all_python_files(root_dir)
    print(f"📁 Найдено файлов: {len(files)}\n")

    # Анализируем каждый файл
    results = []
    for file_path in files:
        print(f"🔎 Анализ: {file_path}")
        result = analyze_file(file_path)
        results.append(result)

    # Проверяем консистентность
    print("\n" + "=" * 80)
    print("📊 РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("=" * 80 + "\n")

    consistency = check_consistency(results)

    # Выводим проблемы с MACD
    if consistency["macd_issues"]:
        print("❌ ПРОБЛЕМЫ С MACD:")
        print("-" * 80)
        for issue in consistency["macd_issues"]:
            print(f"\n📄 Файл: {issue['file']}")
            print(f"   Строка: {issue['line']}")
            print(f"   Проблема: {issue['issue']}")
            print(f"   Серьезность: {issue['severity']}")
            print(f"   Код:\n{issue['code']}")
        print("\n")

    # Выводим проблемы с ADX
    if consistency["adx_issues"]:
        print("⚠️ ПРОБЛЕМЫ С ADX:")
        print("-" * 80)
        for issue in consistency["adx_issues"]:
            print(f"\n   Проблема: {issue['issue']}")
            print(f"   Серьезность: {issue['severity']}")
            print(f"   Рекомендация: {issue['recommendation']}")
        print("\n")

    # Статистика
    print("📈 СТАТИСТИКА:")
    print("-" * 80)
    total_saves = sum(len(r.get("saves", [])) for r in results)
    total_reads = sum(len(r.get("reads", [])) for r in results)
    total_access = sum(len(r.get("direct_access", [])) for r in results)

    print(f"   Операций сохранения: {total_saves}")
    print(f"   Операций чтения: {total_reads}")
    print(f"   Прямых обращений: {total_access}")

    # Сохраняем отчет
    report_file = "docs/analysis/reports/2026-01/АНАЛИЗ_КОНСИСТЕНТНОСТИ_ИНДИКАТОРОВ.md"
    os.makedirs(os.path.dirname(report_file), exist_ok=True)

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# 🔍 АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ\n\n")
        f.write(
            f"**Дата:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
        f.write("## ❌ ПРОБЛЕМЫ С MACD\n\n")
        for issue in consistency["macd_issues"]:
            f.write(f"### {issue['file']}:{issue['line']}\n\n")
            f.write(f"**Проблема:** {issue['issue']}\n\n")
            f.write(f"**Серьезность:** {issue['severity']}\n\n")
            f.write(f"```python\n{issue['code']}\n```\n\n")

        f.write("## ⚠️ ПРОБЛЕМЫ С ADX\n\n")
        for issue in consistency["adx_issues"]:
            f.write(f"**Проблема:** {issue['issue']}\n\n")
            f.write(f"**Рекомендация:** {issue['recommendation']}\n\n")

    print(f"\n✅ Отчет сохранен: {report_file}")


if __name__ == "__main__":
    main()
