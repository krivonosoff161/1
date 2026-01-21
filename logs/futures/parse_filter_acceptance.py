import re
from collections import defaultdict

# Путь к логу (можно заменить на нужный)
LOG_PATH = (
    "c:/Users/krivo/simple trading bot okx/logs/futures/futures_main_2026-01-21.log"
)

# Регулярки для парсинга acceptance rate и режимов
tool_re = re.compile(
    r"\[FILTER_OUTPUT\] (\w+-USDT): (\d+) signals after filters \((\d+) before\)"
)
rate_re = re.compile(r"Acceptance rate: ([\d\.]+)%")
regime_re = re.compile(
    r"Regime scoring for (\w+-USDT): CHOPPY=([\d\.]+), TRENDING=([\d\.]+), RANGING=([\d\.]+), selected=(\w+) "
)

# Для сбора статистики
data = defaultdict(
    lambda: defaultdict(lambda: {"passed": 0, "total": 0, "acceptance": []})
)
current_symbol = None
current_regime = None

with open(LOG_PATH, encoding="utf-8") as f:
    for line in f:
        # Парсим режим
        m = regime_re.search(line)
        if m:
            current_symbol = m.group(1)
            current_regime = m.group(5).lower()
        # Парсим фильтры
        m = tool_re.search(line)
        if m and current_symbol and current_regime:
            symbol = m.group(1)
            passed = int(m.group(2))
            total = int(m.group(3))
            data[symbol][current_regime]["passed"] += passed
            data[symbol][current_regime]["total"] += total
        # Парсим acceptance rate
        m = rate_re.search(line)
        if m and current_symbol and current_regime:
            rate = float(m.group(1))
            data[current_symbol][current_regime]["acceptance"].append(rate)

# Выводим статистику
print("Acceptance rate по инструментам и режимам:")
for symbol, regimes in data.items():
    for regime, stats in regimes.items():
        total = stats["total"]
        passed = stats["passed"]
        avg_accept = (
            sum(stats["acceptance"]) / len(stats["acceptance"])
            if stats["acceptance"]
            else 0
        )
        print(
            f"{symbol:10} | {regime:8} | {passed:4}/{total:4} | avg_accept: {avg_accept:.1f}%"
        )
