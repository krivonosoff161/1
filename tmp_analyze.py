import pathlib
import re
import zipfile
from collections import Counter, defaultdict

base = pathlib.Path("logs/futures")
files = sorted(base.glob("*.log.zip"))
if not files:
    print("Zip-логи не найдены")
    raise SystemExit

print(f"Найдено {len(files)} zip-логов\n")

symbol_re = re.compile(r"\b[A-Z]{2,6}-USDT\b")

risk_blocks = Counter()
orderflow_blocks = Counter()
orderflow_failopen = Counter()
liquidity_blocks = Counter()
volatility_blocks = Counter()
funding_blocks = Counter()
mtf_blocks = Counter()
position_attempts = Counter()
regime_counts = Counter()

risk_samples = defaultdict(list)
orderflow_samples = defaultdict(list)
liquidity_samples = defaultdict(list)
volatility_samples = defaultdict(list)
funding_samples = defaultdict(list)
mtf_samples = defaultdict(list)

executions = []

TOTAL_LINES = 0

for idx, path in enumerate(files, 1):
    print(f"[{idx:02d}/{len(files):02d}] {path.name}", flush=True)
    last_symbol = None
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            data = zf.read(name).decode("utf-8", "replace")
            for raw_line in data.splitlines():
                TOTAL_LINES += 1
                match = symbol_re.search(raw_line)
                if match:
                    last_symbol = match.group(0)
                parts = [part.strip() for part in raw_line.split("|", 3)]
                if len(parts) < 4:
                    continue
                ts, level, module, message = parts
                symbol = symbol_re.search(message)
                if symbol:
                    symbol = symbol.group(0)
                else:
                    symbol = last_symbol or "UNKNOWN"

                if "MaxSizeLimiter" in module and "превышает лимит" in message:
                    risk_blocks[symbol] += 1
                    if len(risk_samples[symbol]) < 5:
                        risk_samples[symbol].append((ts, message))
                elif "OrderFlowFilter" in module:
                    if "delta=" in message and ("<" in message or ">" in message):
                        orderflow_blocks[symbol] += 1
                        if len(orderflow_samples[symbol]) < 5:
                            orderflow_samples[symbol].append((ts, message))
                    elif "fail-open" in message:
                        orderflow_failopen[symbol] += 1
                elif "LiquidityFilter" in module:
                    if (
                        "" in message
                        or "не проходит" in message
                        or "блок" in message.lower()
                    ):
                        liquidity_blocks[symbol] += 1
                        if len(liquidity_samples[symbol]) < 5:
                            liquidity_samples[symbol].append((ts, message))
                elif "VolatilityRegimeFilter" in module:
                    if "" in message or "не проходит" in message:
                        volatility_blocks[symbol] += 1
                        if len(volatility_samples[symbol]) < 5:
                            volatility_samples[symbol].append((ts, message))
                elif "FundingRateFilter" in module:
                    if "" in message or "Запрещ" in message:
                        funding_blocks[symbol] += 1
                        if len(funding_samples[symbol]) < 5:
                            funding_samples[symbol].append((ts, message))
                if "multi_timeframe" in module and (
                    "НЕ" in message or "Отмен" in message
                ):
                    mtf_blocks[symbol] += 1
                    if len(mtf_samples[symbol]) < 5:
                        mtf_samples[symbol].append((ts, message))

                if "calculate_position_size" in module and "position_size=" in message:
                    position_attempts[symbol] += 1

                if (
                    "AdaptiveRegimeManager:detect_regime" in module
                    and "Detected:" in message
                ):
                    for line in message.split("\n"):
                        line = line.strip()
                        if line.startswith("Detected:"):
                            regime = line.split("Detected:")[1].split("(")[0].strip()
                            regime_counts[regime] += 1

                if "order_executor" in module and (
                    "Создан" in message or "Исполнен" in message or "Отмен" in message
                ):
                    executions.append((ts, symbol, message))

print("\n=== Итоги по всей ночи ===")
print(f"Всего строк в логах: {TOTAL_LINES:,}")
print(f"Всего попыток расчёта позиции: {sum(position_attempts.values())}")
print(f"Всего событий order_executor: {len(executions)}")

if risk_blocks:
    print("\n-- Блокировки MaxSizeLimiter --")
    for sym, cnt in risk_blocks.most_common():
        print(f"  {sym}: {cnt}")
        for ts, msg in risk_samples[sym]:
            print(f"    {ts} | {msg}")
else:
    print("\nMaxSizeLimiter: блокировок не найдено")

if orderflow_blocks:
    print("\n-- Отказы OrderFlow (delta) --")
    for sym, cnt in orderflow_blocks.most_common():
        print(f"  {sym}: {cnt} (fail-open {orderflow_failopen.get(sym, 0)})")
        for ts, msg in orderflow_samples[sym]:
            print(f"    {ts} | {msg}")
else:
    print("\nOrderFlow: блокировок не найдено")

if liquidity_blocks:
    print("\n-- Отказы Liquidity --")
    for sym, cnt in liquidity_blocks.most_common():
        print(f"  {sym}: {cnt}")
        for ts, msg in liquidity_samples[sym]:
            print(f"    {ts} | {msg}")

if mtf_blocks:
    print("\n-- Отказы MTF --")
    for sym, cnt in mtf_blocks.most_common():
        print(f"  {sym}: {cnt}")
        for ts, msg in mtf_samples[sym]:
            print(f"    {ts} | {msg}")

if volatility_blocks:
    print("\n-- Отказы Volatility --")
    for sym, cnt in volatility_blocks.most_common():
        print(f"  {sym}: {cnt}")
        for ts, msg in volatility_samples[sym]:
            print(f"    {ts} | {msg}")

if funding_blocks:
    print("\n-- Отказы FundingRate --")
    for sym, cnt in funding_blocks.most_common():
        print(f"  {sym}: {cnt}")
        for ts, msg in funding_samples[sym]:
            print(f"    {ts} | {msg}")

if regime_counts:
    print("\n-- Детекты режимов --")
    total_regimes = sum(regime_counts.values())
    for regime, cnt in regime_counts.most_common():
        pct = cnt / total_regimes * 100
        print(f"  {regime}: {cnt} ({pct:.1f}%)")

print("\nГотово.")
