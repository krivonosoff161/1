import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open(
    "logs/futures/futures_main_2025-12-27.log", "r", encoding="utf-8", errors="ignore"
) as f:
    lines = f.readlines()

# Ищем события по SOL связанные с ордерами, отменой, market и прибылью
sol_events = []
for i, line in enumerate(lines):
    if "SOL" in line.upper():
        keywords = [
            "ORDER",
            "LIMIT",
            "MARKET",
            "CANCEL",
            "ОТМЕН",
            "РАЗМЕЩЕН",
            "PLACED",
            "ОТКРЫТ",
            "ЗАКРЫТ",
            "OPEN",
            "CLOSE",
            "SUCCESS",
            "PROFIT",
            "ПРИБЫЛЬ",
            "0.77",
            ".77",
            "PNL",
            "ИСПОЛНЕН",
            "FILLED",
            "рыночн",
            "лимит",
        ]
        if any(k in line.upper() for k in keywords):
            # Извлекаем время
            time_match = re.search(r"(\d{2}:\d{2}:\d{2})", line)
            time_str = time_match.group(1) if time_match else "N/A"
            sol_events.append((time_str, line.strip()[:500]))

print(f"Found {len(sol_events)} SOL trade events\n")
for i, (time_str, event) in enumerate(sol_events[-80:]):
    print(f"{i+1}. [{time_str}] {event}")

