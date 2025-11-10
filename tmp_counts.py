import pathlib
import zipfile

path = pathlib.Path(
    "logs/futures/futures_main_2025-11-09.2025-11-09_22-33-56_840066.log.zip"
)
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

count = sum("ордер" in line.lower() for line in lines)
print("order keyword count", count)
count2 = sum("position" in line.lower() for line in lines)
print("position keyword count", count2)
