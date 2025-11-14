import pathlib
import zipfile

base = pathlib.Path("logs/futures")
for path in sorted(base.glob("futures_main_2025-11-09*.log.zip")):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        lines = zf.read(name).decode("utf-8", "replace").splitlines()
    hits = [line for line in lines if "лимит" in line.lower()]
    if hits:
        print(f"=== {path.name} ({len(hits)}) ===")
        for line in hits[:10]:
            print(line)
