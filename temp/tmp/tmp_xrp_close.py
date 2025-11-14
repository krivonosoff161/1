import pathlib
import zipfile

base = pathlib.Path("logs/futures")
for path in sorted(base.glob("futures_main_2025-11-10*.log.zip")):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        for line in zf.read(name).decode("utf-8", "replace").splitlines():
            if "XRP-USDT" in line and "Закрытие позиции" in line:
                print(path.name, line)
