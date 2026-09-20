from pathlib import Path

import pandas as pd

parquet_path = Path(r"D:\02_Trading\data\master_daily_trading_turnover.parquet")
if parquet_path.exists():
    df = pd.read_parquet(parquet_path)
    print("Columns:", df.columns.tolist())
    print("Shape:", df.shape)
    print("Sample:\n", df.head(2))
else:
    print("master_daily_trading_turnover.parquet does not exist")
