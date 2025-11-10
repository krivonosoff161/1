import pathlib
import re
import zipfile
from statistics import mean

base = pathlib.Path("logs/futures")
files = sorted(base.glob("futures_main_2025-11-*.log.zip"))
for plain in ["futures_main_2025-11-09.log", "futures_main_2025-11-10.log"]:
    path = base / plain
    if path.exists():
        files.append(path)

block_regex = re.compile(
    r"delta=(?P<delta>-?\d+\.\d+) < (?P<th_label>long_threshold|short_threshold) (?P<th>-?\d+\.\d+) \(regime=(?P<regime>[a-zA-Z]+)\)"
)
pass_regex = re.compile(
    r" OrderFlowFilter: (?P<symbol>[A-Z-]+) (?P<side>[a-zA-Z]+) подтверждён \(delta=(?P<delta>-?\d+\.\d+), regime=(?P<regime>[a-zA-Z]+)\)"
)
depth_regex = re.compile(
    r"OrderFlowFilter: (?P<symbol>[A-Z-]+) отклонён  суммарная глубина (?P<depth>[\d,]+)"
)
relax_regex = re.compile(r"OrderFlowFilter: (?P<symbol>[A-Z-]+) пороги ослаблены")
fail_regex = re.compile(
    r"OrderFlowFilter fail-open активирован для (?P<symbol>[A-Z-]+): пороги ослаблены на (?P<duration>\d+)s"
)

stats = {}

for path in files:
    if not path.exists():
        continue

    def process_lines(lines):
        last_symbol = None
        for line in lines:
            if "OrderFlowFilter" not in line:
                continue
            relax_match = relax_regex.search(line)
            if relax_match:
                last_symbol = relax_match.group("symbol")
            block_match = block_regex.search(line)
            if block_match:
                symbol = last_symbol
                if not symbol:
                    continue
                regime = block_match.group("regime").lower()
                entry = stats.setdefault(
                    symbol,
                    {"blocks": {}, "passes": {}, "depth_blocks": [], "fail_open": 0},
                )
                entry["blocks"].setdefault(regime, []).append(
                    float(block_match.group("delta"))
                )
                entry.setdefault("thresholds", {}).setdefault(regime, []).append(
                    float(block_match.group("th"))
                )
                continue
            pass_match = pass_regex.search(line)
            if pass_match:
                symbol = pass_match.group("symbol")
                regime = pass_match.group("regime").lower()
                entry = stats.setdefault(
                    symbol,
                    {"blocks": {}, "passes": {}, "depth_blocks": [], "fail_open": 0},
                )
                entry["passes"].setdefault(regime, []).append(
                    float(pass_match.group("delta"))
                )
                continue
            depth_match = depth_regex.search(line)
            if depth_match:
                symbol = depth_match.group("symbol")
                depth = float(depth_match.group("depth").replace(",", ""))
                entry = stats.setdefault(
                    symbol,
                    {"blocks": {}, "passes": {}, "depth_blocks": [], "fail_open": 0},
                )
                entry["depth_blocks"].append(depth)
                continue
            fail_match = fail_regex.search(line)
            if fail_match:
                symbol = fail_match.group("symbol")
                entry = stats.setdefault(
                    symbol,
                    {"blocks": {}, "passes": {}, "depth_blocks": [], "fail_open": 0},
                )
                entry["fail_open"] += 1

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                data = zf.read(name).decode("utf-8", "replace")
                process_lines(data.splitlines())
    else:
        data = path.read_text(encoding="utf-8", errors="replace")
        process_lines(data.splitlines())

for sym, data in stats.items():
    print(f"\n=== {sym} ===")
    for regime, deltas in sorted(data.get("blocks", {}).items()):
        print(
            f"  Blocked [{regime}]: {len(deltas)} events, mean delta={mean(deltas):.4f}, min={min(deltas):.4f}, max={max(deltas):.4f}"
        )
        thresholds = data.get("thresholds", {}).get(regime)
        if thresholds:
            uniq = sorted({round(t, 4) for t in thresholds})
            print(f"    thresholds seen: {uniq}")
    for regime, deltas in sorted(data.get("passes", {}).items()):
        print(
            f"  Passed [{regime}]: {len(deltas)} events, mean delta={mean(deltas):.4f}, min={min(deltas):.4f}, max={max(deltas):.4f}"
        )
    if data["depth_blocks"]:
        print(
            f"  Depth blocks: {len(data['depth_blocks'])} events, min depth={min(data['depth_blocks']):,.0f}, max depth={max(data['depth_blocks']):,.0f}"
        )
    if data["fail_open"]:
        print(f"  Fail-open activations: {data['fail_open']}")
