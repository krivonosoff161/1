"""Проверка уникальных значений баланса"""
import re
from collections import Counter
from pathlib import Path

log_dir = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-01_21-39-44"
)

all_logs = list(log_dir.rglob("*.log"))
print(f"📂 LOG файлов: {len(all_logs)}")

balances = []
pattern = re.compile(r"\$(\d+\.?\d*)")

# Собираем ВСЕ упоминания денежных сумм
for log_file in all_logs:
    try:
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line in lines:
            # Расширяем поиск
            if any(
                x in line.lower()
                for x in ["баланс", "balance", "equity", "available", "margin", "total"]
            ):
                matches = pattern.findall(line)
                for m in matches:
                    val = float(m)
                    if 100 < val < 2000:  # Фильтр по разумному диапазону баланса
                        balances.append(val)
    except:
        pass

# Подсчёт уникальных значений
counter = Counter(balances)
print(f"\n📊 Уникальные значения баланса (100-2000 USDT):")
print("-" * 50)
for val, count in sorted(counter.items(), key=lambda x: -x[1])[:30]:
    print(f"   ${val:.2f} - {count} раз")

print(f"\n📊 Всего записей: {len(balances)}")
print(f"📊 Уникальных значений: {len(counter)}")
