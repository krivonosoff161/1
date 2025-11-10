import pathlib
import zipfile

path = pathlib.Path("logs/futures/futures_main_2025-11-09.log.zip")
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

for line in lines:
    if "position_manager" in line:
        print(line)
