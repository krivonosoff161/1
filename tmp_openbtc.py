import pathlib
import zipfile

paths = sorted(pathlib.Path("logs/futures").glob("futures_main_2025-11-09*.log.zip"))

for path in paths:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        for line in zf.read(name).decode("utf-8", "replace").splitlines():
            if "Позиция BTC-USDT" in line and "закрыта" not in line:
                print(path.name, line)
