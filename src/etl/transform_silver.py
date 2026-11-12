from pathlib import Path
import numpy as np
import pandas as pd

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

    # 1. Left join with official English translation table
    df = df_prod.merge(df_trans, on="product_category_name", how="left")

    # 2. Patch the 2 missing Portuguese categories discovered in our audit
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

    # 3. Replace 0g physical weight anomalies (4 items) with NaN before imputation
    df.loc[df["product_weight_g"] <= 0, "product_weight_g"] = np.nan

    # 4. Impute missing numeric fields using category median + global median fallback (Zero warnings!)
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

    # 5. Engineer cubic volume (cm3) for freight efficiency analysis
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

    # 1. Parse timestamps
    df["review_creation_date"] = pd.to_datetime(df["review_creation_date"], errors="coerce")
    df["review_answer_timestamp"] = pd.to_datetime(df["review_answer_timestamp"], errors="coerce")

    # 2. Deduplicate 551 multi-review orders (keep the most recent review per order_id)
    df = (
        df.sort_values(["review_creation_date", "review_answer_timestamp"])
        .drop_duplicates(subset=["order_id"], keep="last")
        .copy()
    )

    # 3. Clean text nulls and create sentiment bucket
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


if __name__ == "__main__":
    clean_orders()
    clean_products()
    clean_reviews()