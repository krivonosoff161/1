import pathlib
import zipfile

path = pathlib.Path("logs/futures/futures_main_2025-11-09.log.zip")
if path.exists():
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        data = zf.read(name).decode("utf-8", "replace")
        count = 0
        for line in data.splitlines():
            if "BTC-USDT" in line and count < 200:
                print(line)
                count += 1
        print(
            f"Total lines containing BTC-USDT: {sum('BTC-USDT' in line for line in data.splitlines())}"
        )
else:
    print("No file")
