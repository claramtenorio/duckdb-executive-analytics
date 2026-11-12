from pathlib import Path
import numpy as np
import pandas as pd
import unicodedata

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BRONZE_DIR = BASE_DIR / "data" / "bronze"
SILVER_DIR = BASE_DIR / "data" / "silver"


def clean_orders() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_orders_dataset.csv")

    # Convert string columns to datetime
    ts_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    for col in ts_cols:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    # Flag and nullify carrier timestamps with chronological anomalies (189 cases)
    carrier_before_purchase = df["order_delivered_carrier_date"] < df["order_purchase_timestamp"]
    customer_before_carrier = df["order_delivered_customer_date"] < df["order_delivered_carrier_date"]
    
    df["has_chronological_error"] = carrier_before_purchase | customer_before_carrier
    df.loc[df["has_chronological_error"], "order_delivered_carrier_date"] = np.nan

    # Engineer lead time metrics (in fractional days)
    df["actual_delivery_days"] = (
        (df["order_delivered_customer_date"] - df["order_purchase_timestamp"]).dt.total_seconds() / 86400.0
    ).round(2)

    # Calendar-day SLA comparison (.dt.normalize() avoids the 1,292 midnight false-positives)
    delivered_cal = df["order_delivered_customer_date"].dt.normalize()
    estimated_cal = df["order_estimated_delivery_date"].dt.normalize()
    df["delivery_delay_days"] = ((delivered_cal - estimated_cal).dt.days).astype("Float64")

    df["is_late"] = (
        (df["order_status"] == "delivered")
        & df["delivery_delay_days"].notna()
        & (df["delivery_delay_days"] > 0)
    )

    # Save clean table to Silver layer in columnar Parquet format
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SILVER_DIR / "orders.parquet"
    df.to_parquet(output_path, index=False)

    print(f"[SILVER] orders.parquet saved! Rows: {len(df):,} | Chrono errors flagged: {df['has_chronological_error'].sum():,} | Late rate: {df.loc[df['order_status']=='delivered', 'is_late'].mean()*100:.2f}%")
    return df


def clean_products() -> pd.DataFrame:
    df_prod = pd.read_csv(BRONZE_DIR / "olist_products_dataset.csv")
    df_trans = pd.read_csv(BRONZE_DIR / "product_category_name_translation.csv")

    # Left join with official English translation table
    df = df_prod.merge(df_trans, on="product_category_name", how="left")

    # Patch the 2 missing Portuguese categories discovered in our audit
    custom_map = {
        "pc_gamer": "computers_gaming",
        "portateis_cozinha_e_preparadores_de_alimentos": "small_kitchen_appliances",
    }
    df["category_pt"] = df["product_category_name"].fillna("nao_classificado")
    df["category_en"] = (
        df["product_category_name_english"]
        .fillna(df["category_pt"].map(custom_map))
        .fillna("unclassified")
    )

    # Replace 0g physical weight anomalies (4 items) with NaN before imputation
    df.loc[df["product_weight_g"] <= 0, "product_weight_g"] = np.nan

    # Impute missing numeric fields using category median + global median fallback (Zero warnings!)
    num_cols = [
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ]
    for col in num_cols:
        global_median = float(df[col].dropna().median())
        category_medians = df.dropna(subset=[col]).groupby("category_en")[col].median()
        df[col] = df[col].fillna(df["category_en"].map(category_medians)).fillna(global_median)

    # Engineer cubic volume (cm3) for freight efficiency analysis
    df["volume_cm3"] = (
        df["product_length_cm"] * df["product_height_cm"] * df["product_width_cm"]
    ).round(2)

    df_clean = df.rename(
        columns={
            "product_name_lenght": "name_length",
            "product_description_lenght": "description_length",
            "product_photos_qty": "photos_qty",
            "product_weight_g": "weight_g",
            "product_length_cm": "length_cm",
            "product_height_cm": "height_cm",
            "product_width_cm": "width_cm",
        }
    )[
        [
            "product_id",
            "category_pt",
            "category_en",
            "name_length",
            "description_length",
            "photos_qty",
            "weight_g",
            "length_cm",
            "height_cm",
            "width_cm",
            "volume_cm3",
        ]
    ]

    output_path = SILVER_DIR / "products.parquet"
    df_clean.to_parquet(output_path, index=False)
    print(f"[SILVER] products.parquet saved! Rows: {len(df_clean):,} | Remaining nulls: {df_clean.isna().sum().sum()}")
    return df_clean


def clean_reviews() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_order_reviews_dataset.csv")

    # Parse timestamps
    df["review_creation_date"] = pd.to_datetime(df["review_creation_date"], errors="coerce")
    df["review_answer_timestamp"] = pd.to_datetime(df["review_answer_timestamp"], errors="coerce")

    # Deduplicate 551 multi-review orders (keep the most recent review per order_id)
    df = (
        df.sort_values(["review_creation_date", "review_answer_timestamp"])
        .drop_duplicates(subset=["order_id"], keep="last")
        .copy()
    )

    # Clean text nulls and create sentiment bucket
    df["has_comment"] = df["review_comment_message"].notna() & (df["review_comment_message"].astype(str).str.strip() != "")
    df["review_comment_title"] = df["review_comment_title"].fillna("No Title").astype(str).str.strip()
    df["review_comment_message"] = df["review_comment_message"].fillna("").astype(str).str.strip()
    df["sentiment_bucket"] = np.where(
        df["review_score"] >= 4, "Positive", np.where(df["review_score"] == 3, "Neutral", "Negative")
    )

    output_path = SILVER_DIR / "reviews.parquet"
    df.to_parquet(output_path, index=False)
    print(f"[SILVER] reviews.parquet saved! Rows: {len(df):,} (strict 1:1 with order_id) | Remaining nulls: {df.isna().sum().sum()}")
    return df


def normalize_text(series: pd.Series) -> pd.Series:
    """Remove accents, extra spaces, and convert text to lowercase."""
    return (
        series.astype(str)
        .str.strip()
        .str.lower()
        .apply(lambda s: unicodedata.normalize("NFKD", s).encode("ascii", errors="ignore").decode("utf-8"))
    )


def clean_geolocation() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_geolocation_dataset.csv")

    # Pad ZIP code prefix with leading zeros (e.g., 1001 -> '01001')
    df["zip_code_prefix"] = df["geolocation_zip_code_prefix"].astype(str).str.zfill(5)

    # Filter out GPS coordinates outside Brazil's geographic bounding box
    valid_lat = df["geolocation_lat"].between(-34.0, 5.3)
    valid_lng = df["geolocation_lng"].between(-74.0, -32.0)
    df = df[valid_lat & valid_lng].copy()

    # Normalize city names (e.g., 'são paulo' -> 'sao paulo')
    df["city"] = normalize_text(df["geolocation_city"])
    df["state"] = df["geolocation_state"].astype(str).str.strip().str.upper()

    # Deduplicate to 1 row per ZIP code prefix (1:1 grain)
    df_clean = (
        df.groupby("zip_code_prefix", as_index=False)
        .agg(
            lat=("geolocation_lat", "median"),
            lng=("geolocation_lng", "median"),
            city=("city", "first"),
            state=("state", "first"),
        )
    )

    output_path = SILVER_DIR / "geolocation.parquet"
    df_clean.to_parquet(output_path, index=False)
    print(f"[SILVER] geolocation.parquet saved! Compressed 1,000,163 -> {len(df_clean):,} unique ZIPs")
    return df_clean


def clean_customers() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_customers_dataset.csv")
    df["zip_code_prefix"] = df["customer_zip_code_prefix"].astype(str).str.zfill(5)
    df["city"] = normalize_text(df["customer_city"])
    df["state"] = df["customer_state"].astype(str).str.strip().str.upper()

    df_clean = df[["customer_id", "customer_unique_id", "zip_code_prefix", "city", "state"]]
    df_clean.to_parquet(SILVER_DIR / "customers.parquet", index=False)
    print(f"[SILVER] customers.parquet saved! Rows: {len(df_clean):,} | Unique customers: {df_clean['customer_unique_id'].nunique():,}")
    return df_clean


def clean_sellers() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_sellers_dataset.csv")
    df["zip_code_prefix"] = df["seller_zip_code_prefix"].astype(str).str.zfill(5)
    df["city"] = normalize_text(df["seller_city"])
    df["state"] = df["seller_state"].astype(str).str.strip().str.upper()

    df_clean = df[["seller_id", "zip_code_prefix", "city", "state"]]
    df_clean.to_parquet(SILVER_DIR / "sellers.parquet", index=False)
    print(f"[SILVER] sellers.parquet saved! Rows: {len(df_clean):,}")
    return df_clean


def clean_order_items() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_order_items_dataset.csv")
    df["shipping_limit_date"] = pd.to_datetime(df["shipping_limit_date"], errors="coerce")
    df["total_item_value"] = (df["price"] + df["freight_value"]).round(2)

    df.to_parquet(SILVER_DIR / "order_items.parquet", index=False)
    print(f"[SILVER] order_items.parquet saved! Rows: {len(df):,} | Total GMV: R$ {df['total_item_value'].sum():,.2f}")
    return df


def clean_payments() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_order_payments_dataset.csv")
    df["payment_type"] = df["payment_type"].astype(str).str.strip().str.lower()

    df.to_parquet(SILVER_DIR / "payments.parquet", index=False)
    print(f"[SILVER] payments.parquet saved! Rows: {len(df):,} | Total Paid: R$ {df['payment_value'].sum():,.2f}")
    return df


def clean_marketing_leads() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_marketing_qualified_leads_dataset.csv")
    df["first_contact_date"] = pd.to_datetime(df["first_contact_date"], errors="coerce")
    df["origin"] = df["origin"].fillna("unknown").astype(str).str.strip().str.lower()

    df.to_parquet(SILVER_DIR / "marketing_leads.parquet", index=False)
    print(f"[SILVER] marketing_leads.parquet saved! Rows: {len(df):,} | Remaining nulls: {df.isna().sum().sum()}")
    return df


def clean_closed_deals() -> pd.DataFrame:
    df = pd.read_csv(BRONZE_DIR / "olist_closed_deals_dataset.csv")
    df["won_date"] = pd.to_datetime(df["won_date"], errors="coerce")

    # Drop the 4 columns with >90% nulls identified in our Bronze inspection
    cols_to_drop = [
        "has_company",
        "has_gtin",
        "average_stock",
        "declared_product_catalog_size",
    ]
    df = df.drop(columns=cols_to_drop)

    # Fill remaining categorical nulls with 'unknown'
    cat_cols = ["business_segment", "lead_type", "lead_behaviour_profile", "business_type"]
    for col in cat_cols:
        df[col] = df[col].fillna("unknown").astype(str).str.strip().str.lower()

    df.to_parquet(SILVER_DIR / "closed_deals.parquet", index=False)
    print(f"[SILVER] closed_deals.parquet saved! Rows: {len(df):,} | Remaining nulls: {df.isna().sum().sum()}")
    return df


if __name__ == "__main__":
    clean_orders()
    clean_products()
    clean_reviews()
    clean_geolocation()
    clean_customers()
    clean_sellers()
    clean_order_items()
    clean_payments()
    clean_marketing_leads()
    clean_closed_deals()