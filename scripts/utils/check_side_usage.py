"""
ПРОВЕРКА ВСЕХ МЕСТ ИСПОЛЬЗОВАНИЯ side, position_side, posSide

Проверяет:
1. Все места, где используется side без .lower()
2. Согласованность side, position_side, posSide
3. Потенциальные проблемы с нормализацией
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


class SideUsageChecker:
    def __init__(self, codebase_path: str):
        self.codebase_path = Path(codebase_path)
        self.issues: List[Dict] = []
        self.safe_places: List[Dict] = []

    def check_all(self):
        """Проверить все места использования side"""
        print(f"{BLUE}🔍 ПРОВЕРКА ИСПОЛЬЗОВАНИЯ side, position_side, posSide{RESET}\n")

        # Проверяем все Python файлы
        files = list(
            self.codebase_path.rglob("src/strategies/scalping/futures/**/*.py")
        )

        for file_path in files:
            if "venv" in str(file_path) or "__pycache__" in str(file_path):
                continue

            self.check_file(file_path)

        self.print_summary()

    def check_file(self, file_path: Path):
        """Проверить файл на проблемы с side"""
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            for i, line in enumerate(lines, 1):
                # Проверка 1: side без .lower() в сравнениях
                if re.search(r'\bside\s*==\s*["\'](long|short|LONG|SHORT)', line):
                    if (
                        ".lower()" not in line
                        and "side.lower()" not in lines[max(0, i - 3) : i]
                    ):
                        # Проверяем, нормализован ли side выше
                        is_safe = self._check_if_side_normalized_above(lines, i)
                        if not is_safe:
                            self.issues.append(
                                {
                                    "file": str(
                                        file_path.relative_to(self.codebase_path)
                                    ),
                                    "line": i,
                                    "content": line.strip(),
                                    "issue": "side используется без .lower() в сравнении",
                                }
                            )
                        else:
                            self.safe_places.append(
                                {
                                    "file": str(
                                        file_path.relative_to(self.codebase_path)
                                    ),
                                    "line": i,
                                    "content": line.strip(),
                                    "reason": "side нормализован выше",
                                }
                            )

                # Проверка 2: position_side без .lower() в сравнениях
                if re.search(
                    r'\bposition_side\s*==\s*["\'](long|short|LONG|SHORT)', line
                ):
                    if ".lower()" not in line:
                        # Проверяем, нормализован ли position_side выше
                        is_safe = self._check_if_position_side_normalized_above(
                            lines, i
                        )
                        if not is_safe:
                            self.issues.append(
                                {
                                    "file": str(
                                        file_path.relative_to(self.codebase_path)
                                    ),
                                    "line": i,
                                    "content": line.strip(),
                                    "issue": "position_side используется без .lower() в сравнении",
                                }
                            )
                        else:
                            self.safe_places.append(
                                {
                                    "file": str(
                                        file_path.relative_to(self.codebase_path)
                                    ),
                                    "line": i,
                                    "content": line.strip(),
                                    "reason": "position_side нормализован выше",
                                }
                            )

                # Проверка 3: posSide из API без .lower()
                if re.search(r'\.get\(["\']posSide', line):
                    # Проверяем, используется ли .lower() на следующей строке или в этой
                    if ".lower()" not in line and i < len(lines):
                        next_lines = lines[i : min(i + 3, len(lines))]
                        if not any(".lower()" in nl for nl in next_lines):
                            # Проверяем, используется ли в безопасном контексте
                            if not self._is_safe_context(line, next_lines):
                                self.issues.append(
                                    {
                                        "file": str(
                                            file_path.relative_to(self.codebase_path)
                                        ),
                                        "line": i,
                                        "content": line.strip(),
                                        "issue": "posSide из API может быть не нормализован",
                                    }
                                )

        except Exception as e:
            print(f"{RED}❌ Ошибка проверки {file_path.name}: {e}{RESET}")

    def _check_if_side_normalized_above(
        self, lines: List[str], current_line: int
    ) -> bool:
        """Проверить, нормализован ли side выше"""
        # Проверяем 10 строк выше
        start = max(0, current_line - 10)
        for i in range(start, current_line):
            if "side" in lines[i] and ".lower()" in lines[i]:
                return True
        return False

    def _check_if_position_side_normalized_above(
        self, lines: List[str], current_line: int
    ) -> bool:
        """Проверить, нормализован ли position_side выше"""
        # Проверяем 10 строк выше
        start = max(0, current_line - 10)
        for i in range(start, current_line):
            if "position_side" in lines[i] and ".lower()" in lines[i]:
                return True
        return False

    def _is_safe_context(self, line: str, next_lines: List[str]) -> bool:
        """Проверить, безопасен ли контекст использования"""
        # Если используется в присваивании с .lower() ниже - безопасно
        for nl in next_lines:
            if ".lower()" in nl and ("side" in nl or "position_side" in nl):
                return True
        return False

    def print_summary(self):
        """Вывести итоговый отчет"""
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{BLUE}📊 ИТОГОВЫЙ ОТЧЕТ{RESET}")
        print(f"{BLUE}{'='*60}{RESET}\n")

        if not self.issues:
            print(f"{GREEN}✅ КРИТИЧЕСКИХ ПРОБЛЕМ НЕ НАЙДЕНО!{RESET}\n")
            print(
                f"{YELLOW}⚠️  Найдено {len(self.safe_places)} безопасных использований{RESET}"
            )
        else:
            print(f"{RED}❌ НАЙДЕНО {len(self.issues)} ПОТЕНЦИАЛЬНЫХ ПРОБЛЕМ:{RESET}\n")
            for issue in self.issues:
                print(f"{RED}  Файл: {issue['file']}:{issue['line']}{RESET}")
                print(f"  Проблема: {issue['issue']}")
                print(f"  Код: {issue['content'][:80]}...")
                print()


if __name__ == "__main__":
    checker = SideUsageChecker(".")
    checker.check_all()
