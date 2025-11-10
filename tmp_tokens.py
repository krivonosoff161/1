import pathlib
import zipfile

path = pathlib.Path("logs/futures/futures_main_2025-11-09.log.zip")
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    text = zf.read(name).decode("utf-8", "replace")

for token in ["FILLED", "Filled", "filled", "fill"]:
    count = text.count(token)
    print(token, count)
