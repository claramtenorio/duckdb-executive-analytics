from pathlib import Path
import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "gold" / "olist_analytics.duckdb"

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)


def run_executive_kpis() -> None:
    con = duckdb.connect(str(DB_PATH), read_only=True)

    # LOGISTICS SLA IMPACT ON CUSTOMER SATISFACTION
    q_sla = """
        SELECT
            CASE WHEN is_late THEN 'Late Delivery' ELSE 'On-Time Delivery' END AS delivery_status,
            COUNT(*) AS delivered_orders,
            ROUND(AVG(actual_delivery_days), 1) AS avg_delivery_days,
            ROUND(AVG(review_score), 2) AS avg_review_score,
            ROUND(100.0 * COUNT(*) FILTER (WHERE review_score = 1) / COUNT(review_score), 1) AS pct_1_star_reviews
        FROM fact_orders
        WHERE order_status = 'delivered' AND review_score IS NOT NULL
        GROUP BY 1
        ORDER BY 1 DESC;
    """
    print("\n=== 1. LOGISTICS SLA IMPACT ON CUSTOMER REVIEWS ===")
    print(con.execute(q_sla).df().to_string(index=False))

    # TOP 10 STATES BY GMV: DISTANCE, FREIGHT BURDEN & LATE RATE
    q_geo = """
        SELECT
            customer_state AS state,
            COUNT(DISTINCT order_id) AS total_orders,
            ROUND(SUM(total_item_value), 2) AS total_gmv,
            ROUND(AVG(shipping_distance_km), 0) AS avg_distance_km,
            ROUND(100.0 * AVG(freight_share), 1) AS avg_freight_share_pct,
            ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_late) / COUNT(DISTINCT order_id), 1) AS late_rate_pct
        FROM fact_order_items
        WHERE order_status = 'delivered'
        GROUP BY 1
        ORDER BY total_gmv DESC
        LIMIT 10;
    """
    print("\n=== 2. TOP 10 STATES: GMV, DISTANCE, FREIGHT SHARE & SLA ===")
    print(con.execute(q_geo).df().to_string(index=False))

    # B2B ACQUISITION FUNNEL ROI BY CHANNEL
    q_b2b = """
        SELECT
            origin,
            COUNT(*) AS total_leads,
            COUNT(*) FILTER (WHERE is_converted) AS closed_deals,
            ROUND(100.0 * COUNT(*) FILTER (WHERE is_converted) / COUNT(*), 1) AS conversion_rate_pct,
            COUNT(*) FILTER (WHERE realized_gmv > 0) AS active_sellers,
            ROUND(SUM(realized_gmv), 2) AS total_realized_gmv,
            ROUND(SUM(realized_gmv) / NULLIF(COUNT(*), 0), 2) AS gmv_per_lead
        FROM fact_b2b_funnel
        GROUP BY 1
        HAVING COUNT(*) >= 100
        ORDER BY total_realized_gmv DESC;
    """
    print("\n=== 3. B2B MARKETING FUNNEL ROI BY ACQUISITION CHANNEL ===")
    print(con.execute(q_b2b).df().to_string(index=False))

    # CATEGORY PARETO ANALYSIS (80/20 RULE WITH WINDOW FUNCTIONS)
    q_pareto = """
        WITH cat_gmv AS (
            SELECT
                category_en,
                COUNT(DISTINCT order_id) AS orders,
                ROUND(SUM(total_item_value), 2) AS gmv
            FROM fact_order_items
            WHERE order_status NOT IN ('canceled', 'unavailable')
            GROUP BY 1
        ),
        ranked AS (
            SELECT
                category_en,
                orders,
                gmv,
                ROUND(100.0 * gmv / SUM(gmv) OVER (), 2) AS gmv_share_pct,
                ROUND(100.0 * SUM(gmv) OVER (ORDER BY gmv DESC) / SUM(gmv) OVER (), 2) AS cumulative_gmv_pct
            FROM cat_gmv
        )
        SELECT *
        FROM ranked
        WHERE cumulative_gmv_pct <= 80.5
        ORDER BY gmv DESC;
    """
    df_pareto = con.execute(q_pareto).df()
    print(f"\n=== 4. CATEGORY PARETO (TOP {len(df_pareto)} OF 74 CATEGORIES = ~80% OF GMV) ===")
    print(df_pareto.to_string(index=False))

    con.close()


if __name__ == "__main__":
    run_executive_kpis()