"""
АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ

Поиск всех мест, где индикаторы сохраняются и читаются,
и проверка единообразия форматов данных.
"""

import os
import re
from collections import defaultdict
from pathlib import Path

# Индикаторы, которые должны быть dict
COMPLEX_INDICATORS = ["macd", "bollinger_bands", "bb"]

# Индикаторы, которые должны быть scalar
SIMPLE_INDICATORS = [
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
]

ALL_INDICATORS = COMPLEX_INDICATORS + SIMPLE_INDICATORS


def find_files(root_dir: str) -> list:
    """Найти все Python файлы"""
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [
            d
            for d in dirs
            if d not in ("__pycache__", ".git", "venv", ".venv", "tests")
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def analyze_file(file_path: str) -> dict:
    """Анализ одного файла"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

        result = {
            "file": file_path,
            "saves": [],
            "reads": [],
            "direct_access": [],
        }

        # Поиск update_indicators
        for i, line in enumerate(lines, 1):
            if "update_indicators" in line:
                # Ищем ключи в следующей строке или в этой
                context = "\n".join(lines[max(0, i - 3) : min(len(lines), i + 3)])
                keys = extract_keys_from_dict(context)
                result["saves"].append(
                    {
                        "line": i,
                        "method": "update_indicators",
                        "keys": keys,
                        "code": context,
                    }
                )

            # Поиск update_indicator
            if "update_indicator" in line:
                key = extract_indicator_name(line)
                if key:
                    context = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 2)])
                    result["saves"].append(
                        {
                            "line": i,
                            "method": "update_indicator",
                            "keys": [key],
                            "code": context,
                        }
                    )

            # Поиск get_indicators / get_indicator
            if "get_indicators" in line or "get_indicator" in line:
                context = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 2)])
                result["reads"].append({"line": i, "code": context})

            # Поиск прямого доступа к индикаторам
            for indicator in ALL_INDICATORS:
                # indicators.get("macd")
                pattern1 = rf'\.get\(["\']{indicator}["\']'
                # indicators["macd"]
                pattern2 = rf'\[["\']{indicator}["\']'
                # indicators.get('macd_histogram')
                pattern3 = rf'\.get\(["\']{indicator}_[^"\']+["\']'

                if (
                    re.search(pattern1, line)
                    or re.search(pattern2, line)
                    or re.search(pattern3, line)
                ):
                    context = "\n".join(lines[max(0, i - 2) : min(len(lines), i + 2)])
                    result["direct_access"].append(
                        {
                            "line": i,
                            "indicator": indicator,
                            "code": context,
                        }
                    )

        return result

    except Exception as e:
        return {"file": file_path, "error": str(e)}


def extract_keys_from_dict(text: str) -> list:
    """Извлечь ключи из словаря в тексте"""
    keys = []
    # Ищем паттерны типа "key": value
    pattern = r'["\']([^"\']+)["\']\s*:'
    matches = re.findall(pattern, text)
    for match in matches:
        if any(ind in match.lower() for ind in ALL_INDICATORS):
            keys.append(match)
    return keys


def extract_indicator_name(line: str) -> str:
    """Извлечь имя индикатора из строки update_indicator"""
    # update_indicator(symbol, "adx", value)
    pattern = r'update_indicator\([^,]+,\s*["\']([^"\']+)["\']'
    match = re.search(pattern, line)
    if match:
        return match.group(1)
    return ""


def check_macd_consistency(results: list) -> list:
    """Проверка консистентности MACD"""
    issues = []

    for result in results:
        file = result["file"]
        if "error" in result:
            continue

        # Проверяем сохранение MACD
        for save in result.get("saves", []):
            keys = save.get("keys", [])
            # Если сохраняются отдельные значения macd, macd_signal, macd_histogram
            if "macd" in keys and "macd_signal" in keys:
                issues.append(
                    {
                        "file": file,
                        "line": save["line"],
                        "issue": "MACD сохраняется как отдельные значения (macd, macd_signal, macd_histogram) вместо dict",
                        "severity": "HIGH",
                        "code": save.get("code", "")[:300],
                    }
                )

        # Проверяем чтение MACD
        for access in result.get("direct_access", []):
            if access.get("indicator") == "macd":
                code = access.get("code", "")
                # Если ожидается dict (isinstance или .get("histogram"))
                if "isinstance" in code and "dict" in code:
                    issues.append(
                        {
                            "file": file,
                            "line": access["line"],
                            "issue": "MACD читается как dict, но может быть сохранен как scalar",
                            "severity": "HIGH",
                            "code": code[:300],
                        }
                    )
                elif ".get(" in code and "histogram" in code:
                    issues.append(
                        {
                            "file": file,
                            "line": access["line"],
                            "issue": "MACD читается как dict с histogram, но может быть сохранен как отдельные значения",
                            "severity": "HIGH",
                            "code": code[:300],
                        }
                    )

    return issues


def check_adx_consistency(results: list) -> list:
    """Проверка консистентности ADX"""
    issues = []
    adx_keys = set()

    for result in results:
        if "error" in result:
            continue

        for save in result.get("saves", []):
            for key in save.get("keys", []):
                if "adx" in key.lower():
                    adx_keys.add(key)

    if len(adx_keys) > 1:
        issues.append(
            {
                "issue": f"ADX сохраняется с разными ключами: {sorted(adx_keys)}",
                "severity": "MEDIUM",
                "recommendation": "Унифицировать ключи: использовать только 'adx'",
            }
        )

    return issues


def main():
    """Главная функция"""
    print("АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ\n")
    print("=" * 80)

    root_dir = "src/strategies/scalping/futures"
    if not os.path.exists(root_dir):
        print(f"ОШИБКА: Директория {root_dir} не найдена!")
        return

    files = find_files(root_dir)
    print(f"Найдено файлов: {len(files)}\n")

    results = []
    for file_path in files:
        print(f"Анализ: {os.path.basename(file_path)}")
        result = analyze_file(file_path)
        results.append(result)

    print("\n" + "=" * 80)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("=" * 80 + "\n")

    # Проверка MACD
    macd_issues = check_macd_consistency(results)
    if macd_issues:
        print("ПРОБЛЕМЫ С MACD:")
        print("-" * 80)
        for issue in macd_issues:
            print(f"\nФайл: {issue['file']}")
            print(f"Строка: {issue['line']}")
            print(f"Проблема: {issue['issue']}")
            print(f"Серьезность: {issue['severity']}")
            code = issue["code"].encode("ascii", "ignore").decode("ascii")
            print(f"Код:\n{code}")
        print("\n")
    else:
        print("MACD: проблем не найдено\n")

    # Проверка ADX
    adx_issues = check_adx_consistency(results)
    if adx_issues:
        print("ПРОБЛЕМЫ С ADX:")
        print("-" * 80)
        for issue in adx_issues:
            print(f"\nПроблема: {issue['issue']}")
            print(f"Серьезность: {issue['severity']}")
            print(f"Рекомендация: {issue['recommendation']}")
        print("\n")
    else:
        print("ADX: проблем не найдено\n")

    # Статистика
    print("СТАТИСТИКА:")
    print("-" * 80)
    total_saves = sum(len(r.get("saves", [])) for r in results)
    total_reads = sum(len(r.get("reads", [])) for r in results)
    total_access = sum(len(r.get("direct_access", [])) for r in results)

    print(f"Операций сохранения: {total_saves}")
    print(f"Операций чтения: {total_reads}")
    print(f"Прямых обращений: {total_access}")

    # Сохраняем отчет
    report_file = "docs/analysis/reports/2026-01/АНАЛИЗ_КОНСИСТЕНТНОСТИ_ИНДИКАТОРОВ.md"
    os.makedirs(os.path.dirname(report_file), exist_ok=True)

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# АНАЛИЗ КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ\n\n")
        f.write(
            f"**Дата:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

        f.write("## ПРОБЛЕМЫ С MACD\n\n")
        if macd_issues:
            for issue in macd_issues:
                f.write(f"### {os.path.basename(issue['file'])}:{issue['line']}\n\n")
                f.write(f"**Проблема:** {issue['issue']}\n\n")
                f.write(f"**Серьезность:** {issue['severity']}\n\n")
                f.write(f"```python\n{issue['code']}\n```\n\n")
        else:
            f.write("Проблем не найдено.\n\n")

        f.write("## ПРОБЛЕМЫ С ADX\n\n")
        if adx_issues:
            for issue in adx_issues:
                f.write(f"**Проблема:** {issue['issue']}\n\n")
                f.write(f"**Рекомендация:** {issue['recommendation']}\n\n")
        else:
            f.write("Проблем не найдено.\n\n")

        f.write("## СТАТИСТИКА\n\n")
        f.write(f"- Операций сохранения: {total_saves}\n")
        f.write(f"- Операций чтения: {total_reads}\n")
        f.write(f"- Прямых обращений: {total_access}\n")

    print(f"\nОтчет сохранен: {report_file}")


if __name__ == "__main__":
    main()
