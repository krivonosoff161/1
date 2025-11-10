import pathlib
import zipfile

path = pathlib.Path(
    "logs/futures/futures_main_2025-11-10.2025-11-10_02-00-27_090883.log.zip"
)
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    for line in zf.read(name).decode("utf-8", "replace").splitlines():
        if "Закрытие позиции XRP-USDT" in line:
            print(line)
