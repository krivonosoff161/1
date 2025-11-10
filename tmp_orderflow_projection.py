import pathlib
import re
import zipfile
from collections import defaultdict

base = pathlib.Path("logs/futures")
files = sorted(base.glob("futures_main_2025-11-*.log.zip"))
for plain in ["futures_main_2025-11-09.log", "futures_main_2025-11-10.log"]:
    path = base / plain
    if path.exists():
        files.append(path)

block_regex = re.compile(
    r"delta=(?P<delta>-?\d+\.\d+) < (?P<th_label>long_threshold|short_threshold) (?P<th>-?\d+\.\d+) \(regime=(?P<regime>[a-zA-Z]+)\)"
)
relax_regex = re.compile(r"OrderFlowFilter: (?P<symbol>[A-Z-]+) пороги ослаблены")

stats = defaultdict(
    lambda: defaultdict(lambda: defaultdict(list))
)  # sym -> regime -> label -> [delta]

for path in files:
    if not path.exists():
        continue

    def process(lines):
        last_symbol = None
        for line in lines:
            if "OrderFlowFilter" not in line:
                continue
            relax_match = relax_regex.search(line)
            if relax_match:
                last_symbol = relax_match.group("symbol")
                continue
            block_match = block_regex.search(line)
            if block_match and last_symbol:
                regime = block_match.group("regime").lower()
                label = block_match.group("th_label")
                delta = float(block_match.group("delta"))
                stats[last_symbol][regime][label].append(delta)

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                data = zf.read(name).decode("utf-8", "replace")
                process(data.splitlines())
    else:
        data = path.read_text(encoding="utf-8", errors="replace")
        process(data.splitlines())

new_thresholds = {
    "BTC-USDT": {"ranging": {"long_threshold": -0.05}},
    "ETH-USDT": {"ranging": {"long_threshold": -0.07}},
    "SOL-USDT": {"ranging": {"long_threshold": -0.10}},
    "DOGE-USDT": {"ranging": {"long_threshold": -0.06}},
    "XRP-USDT": {"ranging": {"long_threshold": -0.06}},
}

for sym, regimes in stats.items():
    print(f"\n=== {sym} ===")
    for regime, sides in regimes.items():
        for label, deltas in sides.items():
            current_blocks = len(deltas)
            if current_blocks == 0:
                continue
            threshold = None
            override = new_thresholds.get(sym, {}).get(regime, {}).get(label)
            if override is None:
                print(f"  {regime} {label}: {current_blocks} blocks (unchanged)")
                continue
            still_blocked = sum(1 for d in deltas if d < override)
            freed = current_blocks - still_blocked
            print(
                f"  {regime} {label}: {current_blocks} blocks  останется {still_blocked} (прибавим {freed}) при пороге {override}"
            )
