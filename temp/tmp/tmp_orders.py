import pathlib
import re
import zipfile

base = pathlib.Path("logs/futures")
files = (
    [base / "futures_main_2025-11-09.log.zip"]
    + sorted(base.glob("futures_main_2025-11-09.2025-11-09_22-*.log.zip"))
    + sorted(base.glob("futures_main_2025-11-10.2025-11-10_0*.log.zip"))
)

symbols = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT"]
keywords = ["order_executor", "position_manager", "order_executor", "order_executor"]

pattern = re.compile("|".join(re.escape(sym) for sym in symbols))

for path in files:
    if not path.exists():
        continue
    print(f"\n=== {path.name} ===")
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        data = zf.read(name).decode("utf-8", "replace")
        for line in data.splitlines():
            if (
                "order_executor" in line
                or "Открыта позиция" in line
                or "Закрываем позицию" in line
                or "Исполнен" in line
                or "Создан" in line
            ):
                if pattern.search(line):
                    print(line)
