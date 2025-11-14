import pathlib
import zipfile

path = pathlib.Path("logs/futures/futures_main_2025-11-09.log.zip")
if not path.exists():
    print("file not found")
else:
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        data = zf.read(name).decode("utf-8", "replace")
        lines = data.splitlines()
        print("\n".join(lines[:100]))
