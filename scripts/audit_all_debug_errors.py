#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Full audit of all DEBUG and ERROR messages in logs
"""

import re
from collections import defaultdict
from pathlib import Path


class DebugErrorAuditor:
    """Audit of all debug and error messages"""

    def __init__(self):
        self.base_path = Path(
            r"c:\Users\krivo\simple trading bot okx\logs\futures\archived\staging_2026-01-08_08-33-22"
        )
        self.error_log = self.base_path / "errors_2026-01-07.log"
        self.all_lines = []

    def load_all_logs(self):
        """Load all logs"""
        print("[*] Search for logs...")

        if self.error_log.exists():
            with open(self.error_log, "r", encoding="utf-8", errors="ignore") as f:
                self.all_lines.extend(f.readlines())
            print(f"[+] Loaded {self.error_log.name}: {len(self.all_lines)} lines")

        log_files = list(self.base_path.glob("*.log"))
        print(f"[+] Found {len(log_files)} log files")
        for log_file in log_files:
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    if log_file.name != "errors_2026-01-07.log":
                        self.all_lines.extend(lines)
                    print(f"    {log_file.name}: {len(lines)} lines")
            except Exception as e:
                print(f"    ERROR {log_file.name}: {e}")

        print(f"\n[+] Total: {len(self.all_lines)} lines loaded\n")

    def analyze_attribute_errors(self):
        """Analyze attribute errors"""
        print("=" * 80)
        print("ATTRIBUTE ERRORS - 'X' has no attribute 'Y'")
        print("=" * 80)

        pattern = r"'(\w+)' object has no attribute '(\w+)'"
        matches = defaultdict(list)

        for i, line in enumerate(self.all_lines):
            m = re.search(pattern, line)
            if m:
                obj_type = m.group(1)
                attr_name = m.group(2)
                key = f"{obj_type}::{attr_name}"

                module_match = re.search(r"\| (.+?):(\w+):(\d+)", line)
                module = module_match.group(1) if module_match else "UNKNOWN"

                matches[key].append({"module": module, "line": line.strip()[:180]})

        if matches:
            print(f"\nFound {len(matches)} unique attribute errors:\n")

            for key in sorted(
                matches.keys(), key=lambda x: len(matches[x]), reverse=True
            ):
                obj_type, attr_name = key.split("::")
                count = len(matches[key])
                module = matches[key][0]["module"]

                print(f"[ATTR] '{obj_type}' has no attribute '{attr_name}'")
                print(f"       Count: {count}, Module: {module}")
                print()

    def analyze_type_errors(self):
        """Analyze type errors"""
        print("=" * 80)
        print("TYPE ERRORS - TypeError, 'str' has no attribute, etc")
        print("=" * 80)

        patterns = [
            (r"'str' object has no attribute", "str has no attribute"),
            (r"'NoneType' object has no attribute", "NoneType has no attribute"),
            (r"'list' object has no attribute", "list has no attribute"),
            (r"'dict' object has no attribute", "dict has no attribute"),
            (r"TypeError:", "TypeError"),
        ]

        type_errors = defaultdict(list)

        for i, line in enumerate(self.all_lines):
            for pattern, error_type in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    module_match = re.search(r"\| (.+?):(\w+):(\d+)", line)
                    module = module_match.group(1) if module_match else "UNKNOWN"
                    type_errors[error_type].append({"module": module})

        if type_errors:
            print(f"\nFound {len(type_errors)} type errors:\n")

            for error_type in sorted(
                type_errors.keys(), key=lambda x: len(type_errors[x]), reverse=True
            ):
                count = len(type_errors[error_type])
                print(f"[TYPE] {error_type}: {count} times")

    def analyze_module_errors(self):
        """Analyze errors by module"""
        print("\n" + "=" * 80)
        print("ERRORS BY MODULE")
        print("=" * 80)

        module_pattern = r"\| (.+?):(\w+):(\d+)"
        modules = defaultdict(int)

        for line in self.all_lines:
            if "ERROR" in line or "WARNING" in line:
                m = re.search(module_pattern, line)
                if m:
                    module = m.group(1)
                    modules[module] += 1

        print(f"\nModules with errors:\n")

        for module in sorted(modules.keys(), key=lambda x: modules[x], reverse=True)[
            :15
        ]:
            count = modules[module]
            print(f"[{count:3d}] {module}")

    def find_specific_issues(self):
        """Find specific issues"""
        print("\n" + "=" * 80)
        print("SPECIFIC ISSUES")
        print("=" * 80)

        issues = {
            "Trailing SL": r"should_close|TrailingStopLoss",
            "Pivot problems": r"Pivot.*XRP|near PP",
            "TCC problems": r"TCC.*Error|trading_control_center",
            "Position Manager": r"close_position_manually",
            "Order execution": r"place_futures_order|order_executor",
        }

        print()

        for issue_name, pattern in issues.items():
            count = sum(
                1 for line in self.all_lines if re.search(pattern, line, re.IGNORECASE)
            )
            if count > 0:
                print(f"[ISSUE] {issue_name}: {count} occurrences")

    def generate_summary(self):
        """Generate summary"""
        print("\n" + "=" * 80)
        print("SUMMARY STATISTICS")
        print("=" * 80)

        error_count = sum(1 for line in self.all_lines if "ERROR" in line)
        warning_count = sum(
            1 for line in self.all_lines if "WARNING" in line or "DEBUG" in line
        )

        print(f"\n[STAT] Total lines: {len(self.all_lines)}")
        print(f"[STAT] ERROR count: {error_count}")
        print(f"[STAT] WARNING/DEBUG count: {warning_count}")
        print(f"[STAT] Total problems: {error_count + warning_count}")

        print(f"\n[FIRST 20 ERRORS]\n")

        count = 0
        for line in self.all_lines:
            if "ERROR" in line:
                time_match = re.search(r"(\d{2}:\d{2}:\d{2})", line)
                time_str = time_match.group(1) if time_match else "UNKNOWN"
                print(f"{count+1:2d}. [{time_str}] {line.strip()[:120]}")
                count += 1
                if count >= 20:
                    break

    def run(self):
        """Run audit"""
        print("\n" + "=" * 80)
        print("FULL AUDIT: ALL DEBUG AND ERROR MESSAGES")
        print("=" * 80 + "\n")

        self.load_all_logs()

        if not self.all_lines:
            print("[ERROR] No logs loaded!")
            return

        self.analyze_attribute_errors()
        self.analyze_type_errors()
        self.analyze_module_errors()
        self.find_specific_issues()
        self.generate_summary()

        print("\n" + "=" * 80)
        print("AUDIT COMPLETED")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    auditor = DebugErrorAuditor()
    auditor.run()
