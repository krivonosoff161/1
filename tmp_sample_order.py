import pathlib
import zipfile

path = pathlib.Path(
    "logs/futures/futures_main_2025-11-09.2025-11-09_22-33-56_840066.log.zip"
)
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

printed = 0
for line in lines:
    if "ордер" in line.lower():
        print(line)
        printed += 1
        if printed >= 40:
            break
