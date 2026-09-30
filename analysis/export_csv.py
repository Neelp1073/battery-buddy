"""Export the Battery Buddy readings history from SQLite to CSV.

    python analysis/export_csv.py --db backend/battery.db --out analysis/output/readings.csv
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

QUERY = """
SELECT h.device_id,
       d.device_type,
       h.battery_percent,
       h.is_charging,
       h.created_at
FROM history AS h
LEFT JOIN devices AS d USING (device_id)
ORDER BY h.created_at, h.id
"""


def load_readings_from_db(db_path) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(QUERY, conn)
    conn.close()
    return df


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", default=root / "backend" / "battery.db")
    parser.add_argument("--out", default=root / "analysis" / "output" / "readings.csv")
    args = parser.parse_args()

    df = load_readings_from_db(args.db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Exported {len(df)} readings for {df['device_id'].nunique()} device(s) to {out}")


if __name__ == "__main__":
    main()
