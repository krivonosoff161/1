import pathlib
import zipfile

path = pathlib.Path("logs/futures/futures_main_2025-11-09.log.zip")
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

count = 0
for line in lines:
    if "order_executor" in line:
        print(line)
        count += 1
print("total", count)
