import pathlib
import zipfile

base = pathlib.Path("logs/futures")
keywords = ["limit order", "Limit order", "placed", "place order", "order placed"]
for path in sorted(base.glob("futures_main_2025-11-09*.log.zip")):
    with zipfile.ZipFile(path) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", "replace")
    hits = [line for line in text.splitlines() if any(k in line for k in keywords)]
    if hits:
        print(f"=== {path.name} ({len(hits)}) ===")
        for line in hits[:10]:
            print(line)
