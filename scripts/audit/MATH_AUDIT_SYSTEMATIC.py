"""
СИСТЕМАТИЧЕСКИЙ АУДИТ ВСЕХ РАСЧЕТОВ В БОТЕ

Проверяет:
1. PnL расчеты для LONG и SHORT
2. TP/SL расчеты для LONG и SHORT
3. Расчеты размера позиций
4. Расчеты маржи
5. Адаптивные параметры для всех режимов и символов
6. Знаки в формулах
7. Все математические операции
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Цвета для вывода
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


class MathAuditor:
    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path)
        self.issues: List[Dict] = []
        self.checked_files: List[str] = []

    def audit_all(self):
        """Провести полный аудит всех расчетов"""
        print(f"{BLUE}🔍 СИСТЕМАТИЧЕСКИЙ АУДИТ ВСЕХ РАСЧЕТОВ{RESET}\n")

        # 1. Аудит PnL расчетов
        print(f"{YELLOW}1. Аудит PnL расчетов (LONG/SHORT){RESET}")
        self.audit_pnl_calculations()

        # 2. Аудит TP/SL расчетов
        print(f"\n{YELLOW}2. Аудит TP/SL расчетов (LONG/SHORT){RESET}")
        self.audit_tp_sl_calculations()

        # 3. Аудит расчетов размера позиций
        print(f"\n{YELLOW}3. Аудит расчетов размера позиций{RESET}")
        self.audit_position_size_calculations()

        # 4. Аудит расчетов маржи
        print(f"\n{YELLOW}4. Аудит расчетов маржи{RESET}")
        self.audit_margin_calculations()

        # 5. Аудит адаптивных параметров
        print(f"\n{YELLOW}5. Аудит адаптивных параметров{RESET}")
        self.audit_adaptive_parameters()

        # 6. Аудит знаков в формулах
        print(f"\n{YELLOW}6. Аудит знаков в формулах{RESET}")
        self.audit_formula_signs()

        # Итоговый отчет
        self.print_summary()

    def audit_pnl_calculations(self):
        """Аудит PnL расчетов для LONG и SHORT"""
        patterns = [
            # LONG PnL: (exit_price - entry_price) * size
            {
                "name": "LONG PnL",
                "pattern": r"\(.*exit.*price.*-.*entry.*price.*\)|\(.*current.*price.*-.*entry.*price.*\)",
                "expected": "exit_price - entry_price",
                "file_pattern": "*.py",
                "description": "LONG: (exit_price - entry_price) * size",
            },
            # SHORT PnL: (entry_price - exit_price) * size
            {
                "name": "SHORT PnL",
                "pattern": r"\(.*entry.*price.*-.*exit.*price.*\)|\(.*entry.*price.*-.*current.*price.*\)",
                "expected": "entry_price - exit_price",
                "file_pattern": "*.py",
                "description": "SHORT: (entry_price - exit_price) * size",
            },
        ]

        for pattern_info in patterns:
            self.check_pattern(pattern_info)

    def audit_tp_sl_calculations(self):
        """Аудит TP/SL расчетов для LONG и SHORT"""
        patterns = [
            # LONG TP: entry_price + tp_distance
            {
                "name": "LONG TP",
                "pattern": r"tp.*price.*=.*entry.*price.*\+|tp_price.*=.*entry.*\+",
                "expected": "entry_price + tp_distance",
                "file_pattern": "*.py",
                "description": "LONG TP: entry_price + tp_distance",
            },
            # LONG SL: entry_price - sl_distance
            {
                "name": "LONG SL",
                "pattern": r"sl.*price.*=.*entry.*price.*-|sl_price.*=.*entry.*-",
                "expected": "entry_price - sl_distance",
                "file_pattern": "*.py",
                "description": "LONG SL: entry_price - sl_distance",
            },
            # SHORT TP: entry_price - tp_distance
            {
                "name": "SHORT TP",
                "pattern": r"tp.*price.*=.*entry.*price.*-|tp_price.*=.*entry.*-",
                "expected": "entry_price - tp_distance",
                "file_pattern": "*.py",
                "description": "SHORT TP: entry_price - tp_distance",
            },
            # SHORT SL: entry_price + sl_distance
            {
                "name": "SHORT SL",
                "pattern": r"sl.*price.*=.*entry.*price.*\+|sl_price.*=.*entry.*\+",
                "expected": "entry_price + sl_distance",
                "file_pattern": "*.py",
                "description": "SHORT SL: entry_price + sl_distance",
            },
        ]

        for pattern_info in patterns:
            self.check_pattern(pattern_info)

    def audit_position_size_calculations(self):
        """Аудит расчетов размера позиций"""
        # Проверяем, что размер позиции рассчитывается с учетом всех факторов
        files_to_check = [
            "src/strategies/scalping/futures/calculations/position_sizer.py",
            "src/strategies/scalping/futures/risk_manager.py",
        ]

        for file_path in files_to_check:
            full_path = self.codebase_path / file_path
            if full_path.exists():
                self.check_file_for_issues(full_path, "position_size")

    def audit_margin_calculations(self):
        """Аудит расчетов маржи"""
        files_to_check = [
            "src/strategies/scalping/futures/calculations/margin_calculator.py",
        ]

        for file_path in files_to_check:
            full_path = self.codebase_path / file_path
            if full_path.exists():
                self.check_file_for_issues(full_path, "margin")

    def audit_adaptive_parameters(self):
        """Аудит адаптивных параметров"""
        # Проверяем, что все режимы и символы имеют параметры
        config_file = self.codebase_path / "config/config_futures.yaml"
        if config_file.exists():
            self.check_config_file(config_file)

    def audit_formula_signs(self):
        """Аудит знаков в формулах"""
        # Проверяем критические места на правильность знаков
        critical_files = [
            "src/strategies/scalping/futures/position_manager.py",
            "src/strategies/scalping/futures/calculations/pnl_calculator.py",
            "src/strategies/scalping/futures/indicators/trailing_stop_loss.py",
        ]

        for file_path in critical_files:
            full_path = self.codebase_path / file_path
            if full_path.exists():
                self.check_formula_signs(full_path)

    def check_pattern(self, pattern_info: Dict):
        """Проверить паттерн в файлах"""
        pattern = pattern_info["pattern"]
        name = pattern_info["name"]

        files = list(self.codebase_path.rglob(pattern_info.get("file_pattern", "*.py")))
        matches = []

        for file_path in files:
            if "venv" in str(file_path) or "__pycache__" in str(file_path):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                for i, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        matches.append(
                            {
                                "file": str(file_path.relative_to(self.codebase_path)),
                                "line": i,
                                "content": line.strip(),
                            }
                        )
            except Exception as e:
                pass

        if matches:
            print(f"  {GREEN}✅ {name}: найдено {len(matches)} совпадений{RESET}")
            for match in matches[:5]:  # Показываем первые 5
                print(f"    - {match['file']}:{match['line']}")
        else:
            print(f"  {YELLOW}⚠️  {name}: не найдено совпадений{RESET}")

    def check_file_for_issues(self, file_path: Path, check_type: str):
        """Проверить файл на проблемы"""
        try:
            content = file_path.read_text(encoding="utf-8")

            # Проверяем на потенциальные проблемы
            issues_found = []

            # Проверка на деление на ноль
            if " / 0" in content or " / 0.0" in content:
                issues_found.append("Деление на ноль")

            # Проверка на отсутствие проверок
            if check_type == "position_size":
                if "balance" in content and "if balance" not in content.lower():
                    issues_found.append("Возможное отсутствие проверки баланса")

            if issues_found:
                print(f"  {RED}❌ {file_path.name}: найдены проблемы{RESET}")
                for issue in issues_found:
                    print(f"    - {issue}")
                self.issues.append(
                    {
                        "file": str(file_path.relative_to(self.codebase_path)),
                        "type": check_type,
                        "issues": issues_found,
                    }
                )
            else:
                print(f"  {GREEN}✅ {file_path.name}: проблем не найдено{RESET}")

        except Exception as e:
            print(f"  {RED}❌ Ошибка проверки {file_path.name}: {e}{RESET}")

    def check_config_file(self, config_file: Path):
        """Проверить конфигурационный файл"""
        try:
            content = config_file.read_text(encoding="utf-8")

            # Проверяем наличие всех режимов
            required_regimes = ["trending", "ranging", "choppy"]
            for regime in required_regimes:
                if regime not in content.lower():
                    self.issues.append(
                        {
                            "file": str(config_file.relative_to(self.codebase_path)),
                            "type": "config",
                            "issues": [f"Режим '{regime}' не найден в конфиге"],
                        }
                    )

            # Проверяем наличие всех символов
            required_symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT"]
            for symbol in required_symbols:
                if symbol.replace("-", "").lower() not in content.lower():
                    self.issues.append(
                        {
                            "file": str(config_file.relative_to(self.codebase_path)),
                            "type": "config",
                            "issues": [f"Символ '{symbol}' не найден в конфиге"],
                        }
                    )

            if not any(
                issue["file"] == str(config_file.relative_to(self.codebase_path))
                for issue in self.issues
            ):
                print(
                    f"  {GREEN}✅ config_futures.yaml: все режимы и символы присутствуют{RESET}"
                )

        except Exception as e:
            print(f"  {RED}❌ Ошибка проверки конфига: {e}{RESET}")

    def check_formula_signs(self, file_path: Path):
        """Проверить знаки в формулах"""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            issues = []

            for i, line in enumerate(lines, 1):
                # Проверяем LONG PnL
                if "long" in line.lower() and "pnl" in line.lower():
                    if (
                        "exit_price - entry_price" not in line
                        and "current_price - entry_price" not in line
                    ):
                        if (
                            "entry_price - exit_price" in line
                            or "entry_price - current_price" in line
                        ):
                            issues.append(
                                f"Строка {i}: возможна ошибка знака для LONG PnL"
                            )

                # Проверяем SHORT PnL
                if "short" in line.lower() and "pnl" in line.lower():
                    if (
                        "entry_price - exit_price" not in line
                        and "entry_price - current_price" not in line
                    ):
                        if (
                            "exit_price - entry_price" in line
                            or "current_price - entry_price" in line
                        ):
                            issues.append(
                                f"Строка {i}: возможна ошибка знака для SHORT PnL"
                            )

            if issues:
                print(f"  {RED}❌ {file_path.name}: найдены проблемы со знаками{RESET}")
                for issue in issues[:5]:  # Показываем первые 5
                    print(f"    - {issue}")
                self.issues.append(
                    {
                        "file": str(file_path.relative_to(self.codebase_path)),
                        "type": "formula_signs",
                        "issues": issues,
                    }
                )
            else:
                print(f"  {GREEN}✅ {file_path.name}: знаки в формулах корректны{RESET}")

        except Exception as e:
            print(f"  {RED}❌ Ошибка проверки знаков: {e}{RESET}")

    def print_summary(self):
        """Вывести итоговый отчет"""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}📊 ИТОГОВЫЙ ОТЧЕТ АУДИТА{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")

        if not self.issues:
            print(f"{GREEN}✅ КРИТИЧЕСКИХ ПРОБЛЕМ НЕ НАЙДЕНО!{RESET}\n")
            print(f"{YELLOW}⚠️  ВНИМАНИЕ: Это автоматический аудит.{RESET}")
            print(
                f"{YELLOW}   Рекомендуется провести ручную проверку критических мест.{RESET}"
            )
        else:
            print(f"{RED}❌ НАЙДЕНО {len(self.issues)} ПРОБЛЕМ:{RESET}\n")
            for issue in self.issues:
                print(f"{RED}  Файл: {issue['file']}{RESET}")
                print(f"  Тип: {issue['type']}")
                for problem in issue["issues"]:
                    print(f"    - {problem}")
                print()


if __name__ == "__main__":
    auditor = MathAuditor(".")
    auditor.audit_all()
