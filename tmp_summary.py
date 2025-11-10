import pathlib
import re
import zipfile

base = pathlib.Path("logs/futures")
files = sorted(base.glob("futures_main_2025-11-0*.log.zip"))

order_pattern = re.compile(
    r"Размещение лимитного ордера: ([A-Z-]+) (buy|sell) ([0-9.]+) @ ([0-9.]+)"
)
close_pattern = re.compile(
    r"Закрытие позиции ([A-Z-]+) по причине: ([^,]+), размер=([0-9.]+) контрактов, PnL=([-+0-9. ]+USDT)"
)

orders = []
closes = []

for path in files:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        for line in zf.read(name).decode("utf-8", "replace").splitlines():
            if "_place_limit_order" in line:
                m = order_pattern.search(line)
                if m:
                    sym, side, size, price = m.groups()
                    timestamp = line.split("|")[0].strip()
                    orders.append((timestamp, sym, side, float(size), float(price)))
            elif "_close_position_by_reason" in line:
                m = close_pattern.search(line)
                if m:
                    sym, reason, size, pnl = m.groups()
                    timestamp = line.split("|")[0].strip()
                    closes.append((timestamp, sym, reason.strip(), float(size), pnl))

print("ORDERS:")
for row in orders[:10]:
    print(row)
print("... total", len(orders))

print("\nCLOSES:")
for row in closes[:10]:
    print(row)
print("... total", len(closes))
