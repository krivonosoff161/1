import pandas as pd

# Путь к файлу статистики (пример: all_data_2026-01-20.csv)
CSV_PATH = "c:/Users/krivo/simple trading bot okx/logs/all_data_2026-01-20.csv"

df = pd.read_csv(CSV_PATH)

# Группировка по инструменту и режиму
if "regime" in df.columns:
    group_cols = ["symbol", "regime"]
else:
    group_cols = ["symbol"]

agg = df.groupby(group_cols).agg(
    trades=("pnl", "count"),
    win_rate=("pnl", lambda x: (x > 0).mean()),
    avg_win=("pnl", lambda x: x[x > 0].mean() if (x > 0).any() else 0),
    avg_loss=("pnl", lambda x: x[x < 0].mean() if (x < 0).any() else 0),
    risk_reward=(
        "pnl",
        lambda x: abs(x[x > 0].mean() / x[x < 0].mean())
        if (x < 0).any() and (x > 0).any()
        else 0,
    ),
    total_pnl=("pnl", "sum"),
)

print(agg.reset_index())
