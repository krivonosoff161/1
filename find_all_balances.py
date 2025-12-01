"""Поиск баланса по ВСЕМ логам"""
import re
from datetime import datetime
from pathlib import Path

log_dir = Path(
    r"C:\Users\krivo\simple trading bot okx\logs\futures\archived\logs_2025-12-01_21-39-44"
)

# Собираем все лог файлы
all_logs = list(log_dir.rglob("*.log"))
print(f"📂 Всего LOG файлов: {len(all_logs)}")

balances = []
pattern = re.compile(r"\$(\d+\.?\d*)")
time_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

for log_file in all_logs:
    try:
        content = log_file.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")

        for line in lines:
            if "Баланс получен из DataRegistry" in line or "Обновлен баланс:" in line:
                m = pattern.search(line)
                tm = time_pattern.search(line)
                if m and tm:
                    balances.append(
                        {
                            "time": tm.group(1),
                            "balance": float(m.group(1)),
                            "line": line[:80],
                        }
                    )
    except Exception as e:
        pass

# Сортируем по времени
balances.sort(key=lambda x: x["time"])

print(f"📊 Найдено записей о балансе: {len(balances)}")
print("")

if balances:
    print("=" * 80)
    print("ПЕРВЫЕ 10 ЗАПИСЕЙ (НАЧАЛО ДНЯ):")
    print("-" * 80)
    for b in balances[:10]:
        print(f"   {b['time']} | ${b['balance']:.2f}")

    print("")
    print("ПОСЛЕДНИЕ 10 ЗАПИСЕЙ (КОНЕЦ ДНЯ):")
    print("-" * 80)
    for b in balances[-10:]:
        print(f"   {b['time']} | ${b['balance']:.2f}")

    print("")
    print("=" * 80)
    print(f"💰 НАЧАЛЬНЫЙ БАЛАНС: ${balances[0]['balance']:.2f} ({balances[0]['time']})")
    print(f"💰 КОНЕЧНЫЙ БАЛАНС: ${balances[-1]['balance']:.2f} ({balances[-1]['time']})")

    change = balances[-1]["balance"] - balances[0]["balance"]
    print(f"")
    print(f"📈 ИЗМЕНЕНИЕ: ${change:+.2f} USDT")

    if change > 0:
        print(f"   ✅ ПРИБЫЛЬ: +{change/balances[0]['balance']*100:.2f}%")
    else:
        print(f"   ❌ УБЫТОК: {change/balances[0]['balance']*100:.2f}%")
    print("=" * 80)
else:
    print("❌ Баланс не найден!")
