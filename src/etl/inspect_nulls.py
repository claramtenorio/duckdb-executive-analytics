from pathlib import Path
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"

TABLES_WITH_NULLS = {
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "marketing_leads": "olist_marketing_qualified_leads_dataset.csv",
    "closed_deals": "olist_closed_deals_dataset.csv",
}

for table_name, filename in TABLES_WITH_NULLS.items():
    df = pd.read_csv(BRONZE_DIR / filename, low_memory=False)
    null_series = df.isna().sum()
    null_cols = null_series[null_series > 0]
    
    print(f"\n--- {table_name.upper()} (Total rows: {len(df):,}) ---")
    for col_name, null_count in null_cols.items():
        pct = (null_count / len(df)) * 100
        print(f"  - {col_name:<36}: {null_count:>7,} nulls ({pct:>5.2f}%)")

# Check how nulls in orders behave across each order_status
df_orders = pd.read_csv(BRONZE_DIR / "olist_orders_dataset.csv")

print("\n--- ORDERS: NULLS BY ORDER STATUS ---")
null_by_status = df_orders.groupby("order_status")[
    ["order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"]
].apply(lambda g: g.isna().sum())

print(null_by_status)