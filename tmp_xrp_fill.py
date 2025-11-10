import pathlib
import zipfile

base = pathlib.Path("logs/futures")
for path in sorted(base.glob("*.log.zip")):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        data = zf.read(name).decode("utf-8", "replace")
        if "XRP-USDT вероятно исполнен" in data:
            for line in data.splitlines():
                if "XRP-USDT вероятно исполнен" in line:
                    print(line)
