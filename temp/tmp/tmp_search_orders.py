import pathlib
import zipfile

path = pathlib.Path(
    "logs/futures/futures_main_2025-11-09.2025-11-09_22-33-56_840066.log.zip"
)
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

for line in lines:
    if (
        "BTC-USDT" in line
        or "ETH-USDT" in line
        or "SOL-USDT" in line
        or "XRP-USDT" in line
    ):
        if (
            "создан" in line.lower()
            or "исполн" in line.lower()
            or "ордер" in line.lower()
            or "position" in line.lower()
        ):
            print(line)
