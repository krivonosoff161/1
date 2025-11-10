import pathlib
import re
import zipfile

base = pathlib.Path("logs/futures")
files = sorted(base.glob("futures_main_2025-11-*.log.zip"))

order_pattern = re.compile(
    r"Размещение лимитного ордера: ([A-Z-]+) (buy|sell) ([0-9.]+) @ ([0-9.]+)"
)
close_pattern = re.compile(
    r"Закрытие позиции ([A-Z-]+) по причине: ([^,]+), размер=([0-9.]+) контрактов, PnL=([-+0-9. ]+USDT)"
)
fill_pattern = re.compile(r"Ордер (\d+) для ([A-Z-]+) вероятно исполнен")
order_id_pattern = re.compile(r"Ордер (\d+)")

orders = []
closes = []
fills = []

for path in files:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        lines = zf.read(name).decode("utf-8", "replace").splitlines()
    for line in lines:
        if "_place_limit_order" in line:
            m = order_pattern.search(line)
            if m:
                sym, side, size, price = m.groups()
                order_id_match = order_id_pattern.search(line)
                order_id = order_id_match.group(1) if order_id_match else "unknown"
                timestamp = line.split("|")[0].strip()
                orders.append(
                    {
                        "time": timestamp,
                        "symbol": sym,
                        "side": side,
                        "size": float(size),
                        "price": float(price),
                        "order_id": order_id,
                    }
                )
        elif "_close_position_by_reason" in line:
            m = close_pattern.search(line)
            if m:
                sym, reason, size, pnl = m.groups()
                timestamp = line.split("|")[0].strip()
                closes.append(
                    {
                        "time": timestamp,
                        "symbol": sym,
                        "reason": reason.strip(),
                        "size": float(size),
                        "pnl": pnl,
                    }
                )
        elif "_update_orders_cache_status" in line and "вероятно исполнен" in line:
            m = fill_pattern.search(line)
            if m:
                order_id, sym = m.groups()
                timestamp = line.split("|")[0].strip()
                fills.append({"time": timestamp, "symbol": sym, "order_id": order_id})

print("ORDERS:")
for order in orders:
    print(order)
print("\nFILLS:")
for fill in fills:
    print(fill)
print("\nCLOSES:")
for close in closes:
    print(close)
print("\nTotals:", len(orders), "orders,", len(fills), "fills,", len(closes), "closes")
