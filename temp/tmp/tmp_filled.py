import pathlib
import zipfile

base = pathlib.Path("logs/futures")
for path in sorted(base.glob("*.log.zip")):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        for line in zf.read(name).decode("utf-8", "replace").splitlines():
            if "вероятно исполнен" in line:
                print(line)
