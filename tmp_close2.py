import pathlib
import zipfile

path = pathlib.Path(
    "logs/futures/futures_main_2025-11-09.2025-11-09_22-46-34_107168.log.zip"
)
with zipfile.ZipFile(path) as zf:
    name = zf.namelist()[0]
    lines = zf.read(name).decode("utf-8", "replace").splitlines()

for line in lines:
    if (
        "закрыт" in line.lower()
        or "закрыта" in line.lower()
        or "закрываем" in line.lower()
    ):
        print(line)
