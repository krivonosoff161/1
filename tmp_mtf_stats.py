import pathlib
import re
import zipfile
from collections import Counter

base = pathlib.Path("logs/futures")
files = sorted(base.glob("futures_main_2025-11-*.log.zip"))
for plain in ["futures_main_2025-11-09.log", "futures_main_2025-11-10.log"]:
    path = base / plain
    if path.exists():
        files.append(path)

block_regex = re.compile(
    r"MTF .* (?P<symbol>[A-Z-]+): (?P<direction>[A-Z]+) blocked by (?P<reason>.*)"
)
neutral_regex = re.compile(
    r"MTF .* (?P<symbol>[A-Z-]+): (?P<direction>[A-Z]+) не подтвержден"
)
confirm_regex = re.compile(
    r"MTF .* (?P<symbol>[A-Z-]+): (?P<direction>[A-Z]+) confirmed"
)

blocked = Counter()
neutral = Counter()
confirmed = Counter()

for path in files:
    if not path.exists():
        continue

    def process(lines):
        for line in lines:
            if "MTF" not in line:
                continue
            m = block_regex.search(line)
            if m:
                blocked[(m.group("symbol"), m.group("direction"))] += 1
                continue
            m = neutral_regex.search(line)
            if m:
                neutral[(m.group("symbol"), m.group("direction"))] += 1
                continue
            m = confirm_regex.search(line)
            if m:
                confirmed[(m.group("symbol"), m.group("direction"))] += 1

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                data = zf.read(name).decode("utf-8", "replace")
                process(data.splitlines())
    else:
        data = path.read_text(encoding="utf-8", errors="replace")
        process(data.splitlines())

symbols = sorted({sym for sym, _ in blocked} | {sym for sym, _ in confirmed})
for sym in symbols:
    print(f"\n=== {sym} ===")
    for direction in ["LONG", "SHORT"]:
        b = blocked.get((sym, direction), 0)
        n = neutral.get((sym, direction), 0)
        c = confirmed.get((sym, direction), 0)
        total = b + n + c
        if total == 0:
            continue
        print(
            f"  {direction}: blocked={b}, neutral={n}, confirmed={c}, block_rate={b/total:.2%}"
        )
