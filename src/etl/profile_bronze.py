from pathlib import Path
import pandas as pd

# Automatically resolve the project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"

# Map canonical table names to their raw Kaggle CSV filenames and primary/grain keys
BRONZE_TABLES = {
    "orders": ("olist_orders_dataset.csv", "order_id"),
    "order_items": ("olist_order_items_dataset.csv", "order_id"),
    "payments": ("olist_order_payments_dataset.csv", "order_id"),
    "reviews": ("olist_order_reviews_dataset.csv", "order_id"),
    "customers": ("olist_customers_dataset.csv", "customer_id"),
    "products": ("olist_products_dataset.csv", "product_id"),
    "sellers": ("olist_sellers_dataset.csv", "seller_id"),
    "geolocation": ("olist_geolocation_dataset.csv", "geolocation_zip_code_prefix"),
    "category_translation": ("product_category_name_translation.csv", "product_category_name"),
    "marketing_leads": ("olist_marketing_qualified_leads_dataset.csv", "mql_id"),
    "closed_deals": ("olist_closed_deals_dataset.csv", "mql_id"),
}

print(f"{'TABLE NAME':<22} | {'ROWS':>10} | {'COLUMNS':>7} | {'NULL CELLS':>10} | {'DUPLICATE KEYS':>16}")
print("-" * 78)

for table_name, (filename, key_col) in BRONZE_TABLES.items():
    file_path = BRONZE_DIR / filename
    df = pd.read_csv(file_path, low_memory=False)
    
    rows, cols = df.shape
    total_nulls = df.isna().sum().sum()
    duplicate_keys = df[key_col].duplicated().sum()
    
    print(f"{table_name:<22} | {rows:>10,} | {cols:>7} | {total_nulls:>10,} | {duplicate_keys:>16,}")