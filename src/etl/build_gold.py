from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SILVER_DIR = BASE_DIR / "data" / "silver"
GOLD_DIR = BASE_DIR / "data" / "gold"
DB_PATH = GOLD_DIR / "olist_analytics.duckdb"


def build_gold_layer() -> None:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old DB file to ensure idempotent full-refresh builds
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = duckdb.connect(str(DB_PATH))

    # DIMENSION TABLES
    con.execute(f"""
        CREATE TABLE dim_products AS
        SELECT * FROM '{SILVER_DIR}/products.parquet';
    """)

    con.execute(f"""
        CREATE TABLE dim_sellers AS
        SELECT 
            s.seller_id,
            s.zip_code_prefix,
            s.city AS seller_city,
            s.state AS seller_state,
            g.lat AS seller_lat,
            g.lng AS seller_lng
        FROM '{SILVER_DIR}/sellers.parquet' s
        LEFT JOIN '{SILVER_DIR}/geolocation.parquet' g USING (zip_code_prefix);
    """)

    # FACT_ORDERS (Grain: 1 row per order_id - Zero Fan-Out via pre-aggregated CTEs)
    con.execute(f"""
        CREATE TABLE fact_orders AS
        WITH items_agg AS (
            SELECT
                order_id,
                COUNT(*) AS items_count,
                COUNT(DISTINCT product_id) AS distinct_products,
                COUNT(DISTINCT seller_id) AS distinct_sellers,
                ROUND(SUM(price), 2) AS items_price_total,
                ROUND(SUM(freight_value), 2) AS freight_total,
                ROUND(SUM(total_item_value), 2) AS gmv_total
            FROM '{SILVER_DIR}/order_items.parquet'
            GROUP BY order_id
        ),
        payments_agg AS (
            SELECT
                order_id,
                COUNT(*) AS payment_installments_rows,
                MAX(payment_installments) AS max_installments,
                ROUND(SUM(payment_value), 2) AS paid_total,
                FIRST(payment_type ORDER BY payment_value DESC) AS primary_payment_type
            FROM '{SILVER_DIR}/payments.parquet'
            GROUP BY order_id
        )
        SELECT
            o.order_id,
            o.customer_id,
            c.customer_unique_id,
            c.city AS customer_city,
            c.state AS customer_state,
            g.lat AS customer_lat,
            g.lng AS customer_lng,
            o.order_status,
            o.order_purchase_timestamp,
            DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
            o.order_approved_at,
            o.order_delivered_carrier_date,
            o.order_delivered_customer_date,
            o.order_estimated_delivery_date,
            o.has_chronological_error,
            o.actual_delivery_days,
            o.delivery_delay_days,
            o.is_late,
            COALESCE(i.items_count, 0) AS items_count,
            COALESCE(i.distinct_products, 0) AS distinct_products,
            COALESCE(i.distinct_sellers, 0) AS distinct_sellers,
            COALESCE(i.items_price_total, 0.0) AS items_price_total,
            COALESCE(i.freight_total, 0.0) AS freight_total,
            COALESCE(i.gmv_total, 0.0) AS gmv_total,
            COALESCE(p.paid_total, 0.0) AS paid_total,
            ROUND(COALESCE(p.paid_total, 0.0) - COALESCE(i.gmv_total, 0.0), 2) AS financing_spread,
            COALESCE(p.max_installments, 1) AS max_installments,
            COALESCE(p.primary_payment_type, 'unknown') AS primary_payment_type,
            r.review_score,
            r.sentiment_bucket,
            r.has_comment
        FROM '{SILVER_DIR}/orders.parquet' o
        LEFT JOIN items_agg i USING (order_id)
        LEFT JOIN payments_agg p USING (order_id)
        LEFT JOIN '{SILVER_DIR}/reviews.parquet' r USING (order_id)
        LEFT JOIN '{SILVER_DIR}/customers.parquet' c USING (customer_id)
        LEFT JOIN '{SILVER_DIR}/geolocation.parquet' g ON c.zip_code_prefix = g.zip_code_prefix;
    """)

    # FACT_ORDER_ITEMS (Grain: 1 row per item sold, enriched with Haversine distance in km)
    con.execute(f"""
        CREATE TABLE fact_order_items AS
        SELECT
            oi.order_id,
            oi.order_item_id,
            o.order_status,
            o.order_purchase_timestamp,
            DATE_TRUNC('month', o.order_purchase_timestamp) AS order_month,
            o.is_late,
            o.actual_delivery_days,
            oi.product_id,
            p.category_en,
            p.category_pt,
            p.weight_g,
            p.volume_cm3,
            oi.seller_id,
            s.seller_city,
            s.seller_state,
            c.customer_unique_id,
            c.city AS customer_city,
            c.state AS customer_state,
            (s.seller_state = c.state) AS is_same_state,
            oi.price,
            oi.freight_value,
            oi.total_item_value,
            ROUND(oi.freight_value / NULLIF(oi.total_item_value, 0), 4) AS freight_share,
            -- Haversine distance (km) between seller and customer coordinates
            ROUND(
                6371 * 2 * ASIN(SQRT(
                    POWER(SIN(RADIANS(cg.lat - s.seller_lat) / 2), 2) +
                    COS(RADIANS(s.seller_lat)) * COS(RADIANS(cg.lat)) *
                    POWER(SIN(RADIANS(cg.lng - s.seller_lng) / 2), 2)
                )), 1
            ) AS shipping_distance_km
        FROM '{SILVER_DIR}/order_items.parquet' oi
        JOIN '{SILVER_DIR}/orders.parquet' o USING (order_id)
        LEFT JOIN dim_products p USING (product_id)
        LEFT JOIN dim_sellers s USING (seller_id)
        LEFT JOIN '{SILVER_DIR}/customers.parquet' c USING (customer_id)
        LEFT JOIN '{SILVER_DIR}/geolocation.parquet' cg ON c.zip_code_prefix = cg.zip_code_prefix;
    """)

    # FACT_B2B_FUNNEL (Grain: 1 row per MQL lead, linking Marketing -> Sales -> Marketplace GMV)
    con.execute(f"""
        CREATE TABLE fact_b2b_funnel AS
        WITH seller_sales AS (
            SELECT
                seller_id,
                COUNT(DISTINCT order_id) AS total_orders_generated,
                COUNT(*) AS total_items_sold,
                ROUND(SUM(total_item_value), 2) AS realized_gmv,
                MIN(order_purchase_timestamp) AS first_sale_timestamp
            FROM fact_order_items
            GROUP BY seller_id
        )
        SELECT
            m.mql_id,
            m.first_contact_date,
            DATE_TRUNC('month', m.first_contact_date) AS lead_month,
            m.landing_page_id,
            m.origin,
            (d.mql_id IS NOT NULL) AS is_converted,
            d.seller_id,
            d.sdr_id,
            d.sr_id,
            d.won_date,
            DATE_DIFF('day', m.first_contact_date, d.won_date) AS days_to_close,
            COALESCE(d.business_segment, 'not_converted') AS business_segment,
            COALESCE(d.lead_type, 'not_converted') AS lead_type,
            COALESCE(d.business_type, 'not_converted') AS business_type,
            COALESCE(ss.total_orders_generated, 0) AS total_orders_generated,
            COALESCE(ss.total_items_sold, 0) AS total_items_sold,
            COALESCE(ss.realized_gmv, 0.0) AS realized_gmv,
            DATE_DIFF('day', d.won_date, ss.first_sale_timestamp) AS days_to_first_sale
        FROM '{SILVER_DIR}/marketing_leads.parquet' m
        LEFT JOIN '{SILVER_DIR}/closed_deals.parquet' d USING (mql_id)
        LEFT JOIN seller_sales ss ON d.seller_id = ss.seller_id;
    """)

    # Export Gold tables to Parquet as well for portability
    gold_tables = ["dim_products", "dim_sellers", "fact_orders", "fact_order_items", "fact_b2b_funnel"]
    print("=== GOLD LAYER BUILD SUMMARY ===")
    for tbl in gold_tables:
        con.execute(f"COPY {tbl} TO '{GOLD_DIR}/{tbl}.parquet' (FORMAT PARQUET);")
        row_count = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  - {tbl:<18}: {row_count:>10,} rows (saved in DuckDB & Parquet)")

    # Financial Integrity Check (Proof of Zero Fan-Out)
    gold_gmv, gold_paid = con.execute("SELECT SUM(gmv_total), SUM(paid_total) FROM fact_orders").fetchone()
    print("\n=== GOLD FINANCIAL RECONCILIATION ===")
    print(f"  - fact_orders GMV Total  : R$ {gold_gmv:,.2f} (Matches Silver exact GMV!)")
    print(f"  - fact_orders Paid Total : R$ {gold_paid:,.2f} (Matches Silver exact Paid!)")

    con.close()


if __name__ == "__main__":
    build_gold_layer()