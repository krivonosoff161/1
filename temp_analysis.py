import csv
from collections import Counter, defaultdict

path = "logs/futures/archived/staging_2026-01-11_21-27-02/all_data_2026-01-11.csv"
stats = Counter()
filter_stats = defaultdict(lambda: {"passed": 0, "total": 0})
signal_types = Counter()
with open(path, encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rt = row.get("record_type", "")
        stats[f"record_type:{rt}"] += 1
        if rt == "signals":
            signal_types[row.get("source", "unknown")] += 1
            strength = row.get("signal_strength")
            if strength:
                stats[f"strength:{strength}"] += 1
        if rt.startswith("filters"):
            name = row.get("filter_type", "?")
            status = row.get("status", "")
            filter_stats[name]["total"] += 1
            if status.lower() == "passed":
                filter_stats[name]["passed"] += 1
        if rt == "positions_open":
            stats["positions_opened"] += 1
        if rt == "position_closures":
            stats["closures"] += 1
print("summary", stats)
print("signalsource", signal_types)
print("filter stats")
for name, data in filter_stats.items():
    if data["total"] > 0:
        print(name, data["passed"], data["total"])
