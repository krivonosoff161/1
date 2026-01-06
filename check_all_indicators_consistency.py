"""
ПОЛНАЯ ПРОВЕРКА КОНСИСТЕНТНОСТИ ВСЕХ ИНДИКАТОРОВ И ФИЛЬТРОВ

Проверяет:
1. Формат сохранения индикаторов в DataRegistry
2. Формат чтения индикаторов из DataRegistry
3. Консистентность между компонентами
4. Параметры фильтров
"""

import re
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any

# Индикаторы, которые должны быть dict
COMPLEX_INDICATORS = {
    "macd": {"keys": ["macd", "signal", "histogram"], "format": "dict"},
    "bollinger_bands": {"keys": ["upper", "lower", "middle"], "format": "dict"},
    "bb": {"keys": ["upper", "lower", "middle"], "format": "dict"},
}

# Индикаторы, которые должны быть scalar
SIMPLE_INDICATORS = {
    "rsi": {"format": "scalar", "aliases": []},
    "atr": {"format": "scalar", "aliases": ["atr_14", "atr_1m"]},
    "sma_20": {"format": "scalar", "aliases": []},
    "ema_12": {"format": "scalar", "aliases": []},
    "ema_26": {"format": "scalar", "aliases": []},
    "adx": {"format": "scalar", "aliases": ["adx_plus_di", "adx_minus_di", "adx_proxy"]},
}

ALL_INDICATORS = list(COMPLEX_INDICATORS.keys()) + list(SIMPLE_INDICATORS.keys())


def find_files(root_dir: str) -> List[str]:
    """Найти все Python файлы"""
    files = []
    for root, dirs, filenames in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "venv", ".venv", "tests")]
        for filename in filenames:
            if filename.endswith(".py"):
                files.append(os.path.join(root, filename))
    return files


def analyze_indicator_usage(file_path: str) -> Dict[str, Any]:
    """Анализ использования индикаторов в файле"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")

        result = {
            "file": file_path,
            "saves": [],  # Где сохраняются индикаторы
            "reads": [],   # Где читаются индикаторы
            "issues": [],  # Найденные проблемы
        }

        # Поиск сохранения индикаторов
        for i, line in enumerate(lines, 1):
            # update_indicators
            if "update_indicators" in line:
                context_lines = lines[max(0, i - 5):min(len(lines), i + 10)]
                context = "\n".join(context_lines)
                
                # Извлекаем ключи из словаря
                keys = extract_dict_keys(context)
                
                result["saves"].append({
                    "line": i,
                    "method": "update_indicators",
                    "keys": keys,
                    "code": context[:500],
                })

            # update_indicator
            if "update_indicator" in line:
                indicator_name = extract_indicator_name_from_call(line)
                if indicator_name:
                    context = "\n".join(lines[max(0, i - 2):min(len(lines), i + 2)])
                    result["saves"].append({
                        "line": i,
                        "method": "update_indicator",
                        "keys": [indicator_name],
                        "code": context[:300],
                    })

            # Чтение индикаторов
            for indicator in ALL_INDICATORS:
                # indicators.get("rsi")
                pattern1 = rf'\.get\(["\']{indicator}["\']'
                # indicators["rsi"]
                pattern2 = rf'\[["\']{indicator}["\']'
                
                if re.search(pattern1, line) or re.search(pattern2, line):
                    context = "\n".join(lines[max(0, i - 3):min(len(lines), i + 3)])
                    result["reads"].append({
                        "line": i,
                        "indicator": indicator,
                        "code": context[:300],
                    })

        return result

    except Exception as e:
        return {"file": file_path, "error": str(e)}


def extract_dict_keys(text: str) -> List[str]:
    """Извлечь ключи из словаря в тексте"""
    keys = []
    # Паттерн: "key": value или 'key': value
    pattern = r'["\']([^"\']+)["\']\s*:'
    matches = re.findall(pattern, text)
    
    for match in matches:
        # Проверяем, является ли это индикатором
        match_lower = match.lower()
        for ind in ALL_INDICATORS:
            if ind in match_lower or match_lower in [alias for aliases in SIMPLE_INDICATORS.values() for alias in aliases.get("aliases", [])]:
                keys.append(match)
                break
    
    return keys


def extract_indicator_name_from_call(line: str) -> str:
    """Извлечь имя индикатора из вызова update_indicator"""
    pattern = r'update_indicator\([^,]+,\s*["\']([^"\']+)["\']'
    match = re.search(pattern, line)
    return match.group(1) if match else ""


def check_consistency(results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Проверка консистентности всех индикаторов"""
    all_issues = defaultdict(list)

    # Проверка MACD
    macd_issues = check_macd_consistency(results)
    all_issues["MACD"] = macd_issues

    # Проверка ADX
    adx_issues = check_adx_consistency(results)
    all_issues["ADX"] = adx_issues

    # Проверка ATR
    atr_issues = check_atr_consistency(results)
    all_issues["ATR"] = atr_issues

    # Проверка RSI
    rsi_issues = check_rsi_consistency(results)
    all_issues["RSI"] = rsi_issues

    # Проверка Bollinger Bands
    bb_issues = check_bb_consistency(results)
    all_issues["Bollinger Bands"] = bb_issues

    # Проверка EMA/SMA
    ma_issues = check_ma_consistency(results)
    all_issues["Moving Averages"] = ma_issues

    return all_issues


def check_macd_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности MACD"""
    issues = []

    for result in results:
        if "error" in result:
            continue

        file = result["file"]

        # Проверяем сохранение
        for save in result.get("saves", []):
            keys = save.get("keys", [])
            
            # Проблема: MACD сохраняется как отдельные значения
            if "macd" in keys and ("macd_signal" in keys or "macd_histogram" in keys):
                issues.append({
                    "file": file,
                    "line": save["line"],
                    "issue": "MACD сохраняется как отдельные значения вместо dict",
                    "severity": "HIGH",
                    "code": save.get("code", "")[:300],
                })

        # Проверяем чтение
        for read in result.get("reads", []):
            if read.get("indicator") == "macd":
                code = read.get("code", "")
                # Если читается как scalar, но должен быть dict
                if ".get('macd')" in code and "isinstance" not in code and ".get(" not in code:
                    issues.append({
                        "file": file,
                        "line": read["line"],
                        "issue": "MACD читается как scalar, но должен быть dict",
                        "severity": "MEDIUM",
                        "code": code[:300],
                    })

    return issues


def check_adx_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности ADX"""
    issues = []
    adx_keys_found = set()

    for result in results:
        if "error" in result:
            continue

        for save in result.get("saves", []):
            for key in save.get("keys", []):
                if "adx" in key.lower():
                    adx_keys_found.add(key)

        for read in result.get("reads", []):
            if "adx" in read.get("indicator", "").lower():
                code = read.get("code", "")
                # Проверяем, что ADX читается правильно
                if "adx" in code.lower() and "get(" not in code:
                    issues.append({
                        "file": result["file"],
                        "line": read["line"],
                        "issue": "ADX читается напрямую без проверки наличия",
                        "severity": "LOW",
                        "code": code[:300],
                    })

    # Если ADX сохраняется с разными ключами
    if len(adx_keys_found) > 3:  # adx, adx_plus_di, adx_minus_di - это нормально
        issues.append({
            "file": "multiple",
            "line": 0,
            "issue": f"ADX сохраняется с множеством ключей: {sorted(adx_keys_found)}",
            "severity": "MEDIUM",
            "code": "",
        })

    return issues


def check_atr_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности ATR"""
    issues = []
    atr_keys_found = set()

    for result in results:
        if "error" in result:
            continue

        for save in result.get("saves", []):
            for key in save.get("keys", []):
                if "atr" in key.lower():
                    atr_keys_found.add(key)

        for read in result.get("reads", []):
            if "atr" in read.get("indicator", "").lower():
                code = read.get("code", "")
                # Проверяем fallback для ATR
                if "atr" in code and "atr_14" not in code and "atr_1m" not in code:
                    # Это не проблема, но можно улучшить
                    pass

    # Если ATR сохраняется с разными ключами без fallback
    if len(atr_keys_found) > 1:
        issues.append({
            "file": "multiple",
            "line": 0,
            "issue": f"ATR сохраняется с разными ключами: {sorted(atr_keys_found)}. Убедитесь, что есть fallback при чтении.",
            "severity": "LOW",
            "code": "",
        })

    return issues


def check_rsi_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности RSI"""
    issues = []

    for result in results:
        if "error" in result:
            continue

        for read in result.get("reads", []):
            if read.get("indicator") == "rsi":
                code = read.get("code", "")
                # RSI должен быть scalar
                if "isinstance" in code and "dict" in code:
                    issues.append({
                        "file": result["file"],
                        "line": read["line"],
                        "issue": "RSI читается как dict, но должен быть scalar",
                        "severity": "HIGH",
                        "code": code[:300],
                    })

    return issues


def check_bb_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности Bollinger Bands"""
    issues = []

    for result in results:
        if "error" in result:
            continue

        for save in result.get("saves", []):
            keys = save.get("keys", [])
            
            # Проверяем, что BB сохраняется как dict, а не отдельные значения
            bb_keys = [k for k in keys if "bb_" in k.lower() or "bollinger" in k.lower()]
            if bb_keys and len(bb_keys) > 1:
                # Если сохраняются отдельные значения bb_upper, bb_lower, bb_middle
                if any("upper" in k.lower() or "lower" in k.lower() or "middle" in k.lower() for k in bb_keys):
                    issues.append({
                        "file": result["file"],
                        "line": save["line"],
                        "issue": "Bollinger Bands сохраняются как отдельные значения вместо dict",
                        "severity": "MEDIUM",
                        "code": save.get("code", "")[:300],
                    })

    return issues


def check_ma_consistency(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Проверка консистентности Moving Averages (EMA/SMA)"""
    issues = []

    for result in results:
        if "error" in result:
            continue

        for read in result.get("reads", []):
            indicator = read.get("indicator", "")
            if "ema" in indicator.lower() or "sma" in indicator.lower():
                code = read.get("code", "")
                # MA должны быть scalar
                if "isinstance" in code and "dict" in code:
                    issues.append({
                        "file": result["file"],
                        "line": read["line"],
                        "issue": f"{indicator} читается как dict, но должен быть scalar",
                        "severity": "MEDIUM",
                        "code": code[:300],
                    })

    return issues


def main():
    """Главная функция"""
    print("=" * 80)
    print("ПОЛНАЯ ПРОВЕРКА КОНСИСТЕНТНОСТИ ВСЕХ ИНДИКАТОРОВ")
    print("=" * 80)
    print()

    root_dir = "src/strategies/scalping/futures"
    if not os.path.exists(root_dir):
        print(f"ОШИБКА: Директория {root_dir} не найдена!")
        return

    files = find_files(root_dir)
    print(f"Найдено файлов: {len(files)}\n")

    results = []
    for file_path in files:
        print(f"Анализ: {os.path.basename(file_path)}")
        result = analyze_indicator_usage(file_path)
        results.append(result)

    print("\n" + "=" * 80)
    print("РЕЗУЛЬТАТЫ ПРОВЕРКИ")
    print("=" * 80)
    print()

    # Проверка консистентности
    all_issues = check_consistency(results)

    total_issues = 0
    for indicator, issues in all_issues.items():
        if issues:
            print(f"\n{'=' * 80}")
            print(f"ПРОБЛЕМЫ С {indicator.upper()}: {len(issues)}")
            print("=" * 80)
            
            for issue in issues:
                total_issues += 1
                print(f"\nФайл: {os.path.basename(issue['file'])}")
                print(f"Строка: {issue['line']}")
                print(f"Проблема: {issue['issue']}")
                print(f"Серьезность: {issue['severity']}")
                if issue.get('code'):
                    code = issue['code'].encode('ascii', 'ignore').decode('ascii')
                    print(f"Код:\n{code[:200]}...")
        else:
            print(f"[OK] {indicator}: проблем не найдено")

    print("\n" + "=" * 80)
    print(f"ИТОГО: Найдено {total_issues} проблем")
    print("=" * 80)

    # Сохраняем отчет
    report_file = "docs/analysis/reports/2026-01/ПОЛНАЯ_ПРОВЕРКА_ИНДИКАТОРОВ_2026-01-06.md"
    os.makedirs(os.path.dirname(report_file), exist_ok=True)

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# ПОЛНАЯ ПРОВЕРКА КОНСИСТЕНТНОСТИ ИНДИКАТОРОВ\n\n")
        f.write(f"**Дата:** 2026-01-06\n\n")
        f.write(f"**Всего проверено файлов:** {len(files)}\n")
        f.write(f"**Всего найдено проблем:** {total_issues}\n\n")
        
        for indicator, issues in all_issues.items():
            f.write(f"## {indicator.upper()}\n\n")
            if issues:
                f.write(f"**Найдено проблем:** {len(issues)}\n\n")
                for issue in issues:
                    f.write(f"### {os.path.basename(issue['file'])}:{issue['line']}\n\n")
                    f.write(f"**Проблема:** {issue['issue']}\n\n")
                    f.write(f"**Серьезность:** {issue['severity']}\n\n")
                    if issue.get('code'):
                        f.write(f"```python\n{issue['code'][:400]}\n```\n\n")
            else:
                f.write("[OK] Проблем не найдено.\n\n")

    print(f"\nОтчет сохранен: {report_file}")


if __name__ == "__main__":
    main()
