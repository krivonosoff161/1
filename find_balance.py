"""Поиск начального и конечного баланса"""
import re
from pathlib import Path

log_dir = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-01_21-39-44"
)
main_log = log_dir / "futures_main_2025-12-01.log"

content = main_log.read_text(encoding="utf-8", errors="ignore")
lines = content.split("\n")

# Ищем все упоминания баланса
balances = []
pattern = re.compile(r"\$(\d+\.?\d*)")

for line in lines:
    if "Баланс получен из DataRegistry" in line or "Обновлен баланс:" in line:
        m = pattern.search(line)
        if m:
            balances.append((line[:50], float(m.group(1))))

# Первый и последний баланс
print("=" * 60)
print("📊 АНАЛИЗ БАЛАНСА ИЗ ЛОГОВ")
print("=" * 60)

if balances:
    print(f"Найдено записей о балансе: {len(balances)}")
    print("")
    print(f"Первая запись: {balances[0][0]}")
    print(f"Последняя запись: {balances[-1][0]}")
    print("")
    print(f"💰 Начальный баланс: ${balances[0][1]:.2f}")
    print(f"💰 Конечный баланс: ${balances[-1][1]:.2f}")
    print(f"")
    change = balances[-1][1] - balances[0][1]
    print(f"📈 Изменение баланса: ${change:+.2f}")

    if change > 0:
        print(f"   ✅ ПРИБЫЛЬ: +{change/balances[0][1]*100:.2f}%")
    else:
        print(f"   ❌ УБЫТОК: {change/balances[0][1]*100:.2f}%")
else:
    print("❌ Записи о балансе не найдены!")
