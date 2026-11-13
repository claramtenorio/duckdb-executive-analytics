from pathlib import Path
import pandas as pd
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"


def audit_orders_anomalies() -> None:
    df = pd.read_csv(BRONZE_DIR / "olist_orders_dataset.csv")
    for col in [
        "order_purchase_timestamp",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    delivered = df[(df["order_status"] == "delivered") & df["order_delivered_customer_date"].notna()]
    naive_late = ((delivered["order_delivered_customer_date"] - delivered["order_estimated_delivery_date"]).dt.total_seconds() > 0).sum()
    cal_late = ((delivered["order_delivered_customer_date"].dt.normalize() - delivered["order_estimated_delivery_date"].dt.normalize()).dt.days > 0).sum()

    carrier_err = (df["order_delivered_carrier_date"] < df["order_purchase_timestamp"]).sum()
    cust_err = (df["order_delivered_customer_date"] < df["order_delivered_carrier_date"]).sum()

    print("=== 1. ORDERS ANOMALIES AUDIT ===")
    print(f"  - Midnight SLA False Positives : {naive_late - cal_late:,} orders ({naive_late:,} naive vs {cal_late:,} calendar)")
    print(f"  - Carrier before purchase      : {carrier_err:,} orders")
    print(f"  - Customer before carrier      : {cust_err:,} orders\n")


def audit_products_anomalies() -> None:
    df_prod = pd.read_csv(BRONZE_DIR / "olist_products_dataset.csv")
    df_trans = pd.read_csv(BRONZE_DIR / "product_category_name_translation.csv")

    # Merge products with the official English translation table
    merged = df_prod.merge(df_trans, on="product_category_name", how="left")

    # Find categories that exist in products.csv but are MISSING from category_translation.csv
    untranslated = merged[
        merged["product_category_name"].notna() & merged["product_category_name_english"].isna()
    ]["product_category_name"].value_counts()

    # Check physical weight anomalies (e.g., weight <= 0 grams)
    zero_weight = (df_prod["product_weight_g"] <= 0).sum()

    print("=== 2. PRODUCTS ANOMALIES AUDIT ===")
    print(f"  - Products with missing category (NaN) : {df_prod['product_category_name'].isna().sum():,}")
    print(f"  - Products with 0g weight              : {zero_weight:,}")
    print("  - Portuguese categories missing from official translation CSV:")
    for cat, count in untranslated.items():
        print(f"      * {cat}: {count} products")


def audit_reviews_anomalies() -> None:
    df_rev = pd.read_csv(BRONZE_DIR / "olist_order_reviews_dataset.csv")
    
    total_rows = len(df_rev)
    unique_orders = df_rev["order_id"].nunique()
    duplicate_order_rows = df_rev["order_id"].duplicated().sum()
    
    print("\n=== 3. REVIEWS ANOMALIES AUDIT ===")
    print(f"  - Total review rows            : {total_rows:,}")
    print(f"  - Unique order_ids reviewed    : {unique_orders:,}")
    print(f"  - Extra rows per order (1:N)   : {duplicate_order_rows:,} duplicate rows")


def audit_geolocation_anomalies() -> None:
    df = pd.read_csv(BRONZE_DIR / "olist_geolocation_dataset.csv")
    
    total_rows = len(df)
    unique_zips = df["geolocation_zip_code_prefix"].nunique()
    
    # Bounding box for Brazil (rough limits)
    # Latitude: roughly -34.0 to 5.3 | Longitude: roughly -74.0 to -32.0
    invalid_lat = ((df["geolocation_lat"] < -34.0) | (df["geolocation_lat"] > 5.3)).sum()
    invalid_lng = ((df["geolocation_lng"] < -74.0) | (df["geolocation_lng"] > -32.0)).sum()

    print("\n=== 4. GEOLOCATION ANOMALIES AUDIT ===")
    print(f"  - Total rows in bronze         : {total_rows:,}")
    print(f"  - Unique ZIP code prefixes     : {unique_zips:,}")
    print(f"  - Duplicate rows (compressible): {total_rows - unique_zips:,}")
    print(f"  - Invalid Latitude (outside BR): {invalid_lat:,}")
    print(f"  - Invalid Longitude (outside BR): {invalid_lng:,}")


def audit_fanout_trap() -> None:
    silver_dir = BASE_DIR / "data" / "silver"
    con = duckdb.connect()

    # Naive JOIN between order_items (1:N) and payments (1:N) without pre-aggregation
    naive_query = f"""
        SELECT 
            COUNT(*) AS joined_rows,
            SUM(oi.total_item_value) AS inflated_gmv,
            SUM(p.payment_value) AS inflated_paid
        FROM '{silver_dir}/order_items.parquet' oi
        JOIN '{silver_dir}/payments.parquet' p USING (order_id)
    """
    joined_rows, inflated_gmv, inflated_paid = con.execute(naive_query).fetchone()

    # True totals from isolated tables
    true_gmv = con.execute(f"SELECT SUM(total_item_value) FROM '{silver_dir}/order_items.parquet'").fetchone()[0]
    true_paid = con.execute(f"SELECT SUM(payment_value) FROM '{silver_dir}/payments.parquet'").fetchone()[0]

    print("\n=== 5. SQL FAN-OUT TRAP AUDIT (DUCKDB) ===")
    print(f"  - True GMV (order_items)       : R$ {true_gmv:>13,.2f}")
    print(f"  - Naive Joined GMV (Fan-Out!)  : R$ {inflated_gmv:>13,.2f} (+R$ {inflated_gmv - true_gmv:,.2f} fake revenue!)")
    print(f"  - True Paid (payments)         : R$ {true_paid:>13,.2f}")
    print(f"  - Naive Joined Paid (Fan-Out!) : R$ {inflated_paid:>13,.2f} (+R$ {inflated_paid - true_paid:,.2f} fake paid!)")

    
if __name__ == "__main__":
    audit_orders_anomalies()
    audit_products_anomalies()
    audit_reviews_anomalies()
    audit_geolocation_anomalies()
    audit_fanout_trap()