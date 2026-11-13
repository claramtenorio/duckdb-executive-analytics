from pathlib import Path
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "gold" / "olist_analytics.duckdb"

st.set_page_config(
    page_title="Olist Executive Lakehouse | DuckDB + Medallion",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource
def get_connection() -> duckdb.DuckDBPyConnection:
    if DB_PATH.exists():
        return duckdb.connect(str(DB_PATH), read_only=True)

    # Cloud Deployment Fallback: mount Gold Parquet files directly into in-memory DuckDB
    gold_dir = BASE_DIR / "data" / "gold"
    parquet_files = list(gold_dir.glob("*.parquet"))
    if not parquet_files:
        st.error("Gold layer data not found! Please run `python3 run_pipeline.py` first.")
        st.stop()

    con = duckdb.connect(":memory:")
    for pq_file in parquet_files:
        table_name = pq_file.stem
        con.execute(f"CREATE VIEW {table_name} AS SELECT * FROM '{pq_file}';")
    return con


con = get_connection()

# SIDEBAR FILTERS
st.sidebar.title("🎛️ Executive Filters")
st.sidebar.markdown("Filter the **Gold Layer** in real time powered by **DuckDB OLAP**.")

min_date, max_date = con.execute(
    "SELECT MIN(order_purchase_timestamp)::DATE, MAX(order_purchase_timestamp)::DATE FROM fact_orders WHERE order_status = 'delivered'"
).fetchone()

date_range = st.sidebar.date_input(
    "Order Date Range",
    value=(pd.to_datetime("2017-01-01").date(), max_date),
    min_value=min_date,
    max_value=max_date,
)

all_states = [
    r[0]
    for r in con.execute(
        "SELECT DISTINCT customer_state FROM fact_orders WHERE customer_state IS NOT NULL ORDER BY 1"
    ).fetchall()
]
selected_states = st.sidebar.multiselect("Customer States (UF)", options=all_states, default=[])

if len(date_range) == 2:
    start_dt, end_dt = date_range
else:
    start_dt, end_dt = min_date, max_date

state_filter_sql = ""
if selected_states:
    states_str = ", ".join(f"'{s}'" for s in selected_states)
    state_filter_sql = f" AND customer_state IN ({states_str})"

st.sidebar.markdown("---")
st.sidebar.caption("Architecture: **Bronze (CSV) → Silver (Parquet) → Gold (DuckDB)**")

# HEADER
st.title("📊 Olist Executive Analytics & Medallion Lakehouse")
st.markdown(
    "Real-time OLAP intelligence built on **1.5M+ Brazilian E-Commerce & B2B Funnel records** using **Python, PyArrow, and DuckDB**."
)

# TOP KPI CARDS
kpi_query = f"""
    SELECT
        COUNT(DISTINCT order_id) AS total_orders,
        ROUND(SUM(gmv_total), 2) AS total_gmv,
        ROUND(SUM(paid_total), 2) AS total_paid,
        ROUND(AVG(gmv_total), 2) AS avg_ticket,
        ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / NULLIF(COUNT(*) FILTER (WHERE order_status = 'delivered'), 0), 2) AS late_rate_pct,
        ROUND(AVG(review_score), 2) AS avg_nps_score
    FROM fact_orders
    WHERE order_purchase_timestamp::DATE BETWEEN '{start_dt}' AND '{end_dt}'
    {state_filter_sql}
"""
kpis = con.execute(kpi_query).fetchone()

def fmt_brl(val: float) -> str:
    if val is None:
        return "R$ 0.00"
    if abs(val) >= 1_000_000:
        return f"R$ {val / 1_000_000:.2f}M"
    if abs(val) >= 10_000:
        return f"R$ {val / 1_000:.1f}K"
    return f"R$ {val:,.2f}"


row1_col1, row1_col2, row1_col3 = st.columns(3)
row2_col1, row2_col2, row2_col3 = st.columns(3)
row1_col1.metric("Total Orders", f"{kpis[0]:,}")
row1_col2.metric("Merchandise GMV", fmt_brl(kpis[1]), help=f"Exact GMV: R$ {kpis[1]:,.2f}")
row1_col3.metric("Total Paid (w/ Interest)", fmt_brl(kpis[2]), help=f"Exact Paid: R$ {kpis[2]:,.2f}")
row2_col1.metric("Average Order Ticket", f"R$ {kpis[3]:,.2f}")
row2_col2.metric("Late Delivery SLA", f"{kpis[4] or 0:.2f}%")
row2_col3.metric("Avg Customer Rating", f"{kpis[5] or 0:.2f} ⭐")

st.markdown("---")

# TABS
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "📈 Revenue & Growth",
        "🚚 Logistics & SLA Impact",
        "🤝 B2B Marketing Funnel",
        "📦 Category Pareto (80/20)",
        "💻 DuckDB SQL Workbench",
    ]
)

with tab1:
    st.subheader("Monthly GMV Evolution vs. Late Delivery Rate")
    q_monthly = f"""
        SELECT
            STRFTIME(order_month, '%Y-%m') AS year_month,
            COUNT(DISTINCT order_id) AS orders,
            ROUND(SUM(gmv_total), 2) AS gmv,
            ROUND(100.0 * COUNT(*) FILTER (WHERE is_late) / NULLIF(COUNT(*) FILTER (WHERE order_status = 'delivered'), 0), 2) AS late_rate_pct
        FROM fact_orders
        WHERE order_purchase_timestamp::DATE BETWEEN '{start_dt}' AND '{end_dt}'
          AND order_status = 'delivered'
          {state_filter_sql}
        GROUP BY 1
        ORDER BY 1
    """
    df_monthly = con.execute(q_monthly).df()

    fig_trend = go.Figure()
    fig_trend.add_trace(
        go.Bar(x=df_monthly["year_month"], y=df_monthly["gmv"], name="GMV (R$)", marker_color="#2563eb")
    )
    fig_trend.add_trace(
        go.Scatter(
            x=df_monthly["year_month"],
            y=df_monthly["late_rate_pct"],
            name="Late Rate (%)",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color="#dc2626", width=3),
        )
    )
    fig_trend.update_layout(
        yaxis=dict(title="Total GMV (R$)"),
        yaxis2=dict(title="Late Delivery Rate (%)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=440,
    )
    st.plotly_chart(fig_trend, use_container_width=True)

with tab2:
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("SLA Delay Impact on Review Scores")
        q_sla = f"""
            SELECT
                CASE WHEN is_late THEN 'Late Delivery' ELSE 'On-Time Delivery' END AS sla_status,
                ROUND(AVG(review_score), 2) AS avg_score,
                ROUND(100.0 * COUNT(*) FILTER (WHERE review_score = 1) / COUNT(review_score), 1) AS pct_1_star,
                ROUND(AVG(actual_delivery_days), 1) AS avg_days
            FROM fact_orders
            WHERE order_status = 'delivered'
              AND review_score IS NOT NULL
              AND order_purchase_timestamp::DATE BETWEEN '{start_dt}' AND '{end_dt}'
              {state_filter_sql}
            GROUP BY 1
        """
        df_sla = con.execute(q_sla).df()
        fig_sla = px.bar(
            df_sla,
            x="sla_status",
            y=["avg_score", "pct_1_star"],
            barmode="group",
            title="Avg Star Rating vs. % of 1-Star Reviews by SLA Status",
            labels={"value": "Metric Value", "sla_status": "Delivery Status"},
        )
        st.plotly_chart(fig_sla, use_container_width=True)
        st.dataframe(df_sla, use_container_width=True, hide_index=True)

    with c_right:
        st.subheader("Regional Logistics: Haversine Distance vs. SLA")
        q_states = f"""
            SELECT
                customer_state AS state,
                COUNT(DISTINCT order_id) AS orders,
                ROUND(SUM(total_item_value), 2) AS gmv,
                ROUND(AVG(shipping_distance_km), 0) AS avg_distance_km,
                ROUND(100.0 * AVG(freight_share), 1) AS freight_share_pct,
                ROUND(100.0 * COUNT(DISTINCT order_id) FILTER (WHERE is_late) / COUNT(DISTINCT order_id), 1) AS late_rate_pct
            FROM fact_order_items
            WHERE order_status = 'delivered'
              AND order_purchase_timestamp::DATE BETWEEN '{start_dt}' AND '{end_dt}'
              {state_filter_sql}
            GROUP BY 1
            HAVING COUNT(DISTINCT order_id) >= 100
            ORDER BY gmv DESC
        """
        df_states = con.execute(q_states).df()
        fig_scatter = px.scatter(
            df_states,
            x="avg_distance_km",
            y="late_rate_pct",
            size="gmv",
            color="freight_share_pct",
            hover_name="state",
            text="state",
            title="State Distance (km) vs. Late Rate (%) — Bubble Size = GMV",
            labels={
                "avg_distance_km": "Avg Seller-to-Customer Distance (km)",
                "late_rate_pct": "Late Delivery Rate (%)",
                "freight_share_pct": "Freight % of Order",
            },
        )
        fig_scatter.update_traces(textposition="top center")
        st.plotly_chart(fig_scatter, use_container_width=True)

with tab3:
    st.subheader("B2B Seller Acquisition Funnel & Realized Marketplace GMV")
    q_b2b = """
        SELECT
            origin AS acquisition_channel,
            COUNT(*) AS mql_leads,
            COUNT(*) FILTER (WHERE is_converted) AS closed_deals,
            COUNT(*) FILTER (WHERE realized_gmv > 0) AS active_generating_sellers,
            ROUND(100.0 * COUNT(*) FILTER (WHERE is_converted) / COUNT(*), 1) AS lead_to_deal_pct,
            ROUND(100.0 * COUNT(*) FILTER (WHERE realized_gmv > 0) / NULLIF(COUNT(*) FILTER (WHERE is_converted), 0), 1) AS deal_activation_pct,
            ROUND(SUM(realized_gmv), 2) AS realized_gmv,
            ROUND(SUM(realized_gmv) / COUNT(*), 2) AS gmv_per_lead
        FROM fact_b2b_funnel
        GROUP BY 1
        HAVING COUNT(*) >= 100
        ORDER BY realized_gmv DESC
    """
    df_b2b = con.execute(q_b2b).df()

    b_left, b_right = st.columns(2)
    with b_left:
        fig_b2b = px.bar(
            df_b2b,
            x="acquisition_channel",
            y="realized_gmv",
            color="gmv_per_lead",
            title="Realized Marketplace GMV by B2B Marketing Channel",
            labels={"realized_gmv": "Realized Seller GMV (R$)", "acquisition_channel": "Marketing Origin"},
        )
        st.plotly_chart(fig_b2b, use_container_width=True)
    with b_right:
        fig_conv = px.bar(
            df_b2b,
            x="acquisition_channel",
            y=["mql_leads", "closed_deals", "active_generating_sellers"],
            barmode="group",
            title="Funnel Leakage: Leads → Closed Deals → Active Sellers",
        )
        st.plotly_chart(fig_conv, use_container_width=True)

    st.dataframe(df_b2b, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Product Category Pareto (80/20 Concentration)")
    q_pareto = f"""
        WITH cat_gmv AS (
            SELECT
                category_en,
                COUNT(DISTINCT order_id) AS orders,
                ROUND(SUM(total_item_value), 2) AS gmv
            FROM fact_order_items
            WHERE order_status NOT IN ('canceled', 'unavailable')
              AND order_purchase_timestamp::DATE BETWEEN '{start_dt}' AND '{end_dt}'
              {state_filter_sql}
            GROUP BY 1
        )
        SELECT
            category_en,
            orders,
            gmv,
            ROUND(100.0 * gmv / SUM(gmv) OVER (), 2) AS share_pct,
            ROUND(100.0 * SUM(gmv) OVER (ORDER BY gmv DESC) / SUM(gmv) OVER (), 2) AS cumulative_pct
        FROM cat_gmv
        ORDER BY gmv DESC
        LIMIT 25
    """
    df_pareto = con.execute(q_pareto).df()

    fig_p = go.Figure()
    fig_p.add_trace(go.Bar(x=df_pareto["category_en"], y=df_pareto["gmv"], name="Category GMV (R$)"))
    fig_p.add_trace(
        go.Scatter(
            x=df_pareto["category_en"],
            y=df_pareto["cumulative_pct"],
            name="Cumulative Share (%)",
            yaxis="y2",
            mode="lines+markers",
            line=dict(color="#16a34a", width=3),
        )
    )
    fig_p.update_layout(
        yaxis=dict(title="GMV (R$)"),
        yaxis2=dict(title="Cumulative Share (%)", overlaying="y", side="right", range=[0, 105]),
        height=450,
    )
    st.plotly_chart(fig_p, use_container_width=True)
    st.dataframe(df_pareto, use_container_width=True, hide_index=True)

with tab5:
    st.subheader("💻 Interactive DuckDB SQL Workbench (Gold Layer)")
    st.markdown(
        "Run custom analytical SQL queries directly against `fact_orders`, `fact_order_items`, `fact_b2b_funnel`, `dim_products`, and `dim_sellers`."
    )
    default_sql = """SELECT 
    primary_payment_type,
    COUNT(*) AS orders,
    ROUND(AVG(max_installments), 1) AS avg_installments,
    ROUND(SUM(gmv_total), 2) AS total_gmv,
    ROUND(SUM(paid_total), 2) AS total_paid,
    ROUND(SUM(financing_spread), 2) AS total_financing_spread
FROM fact_orders
WHERE order_status = 'delivered'
GROUP BY 1
ORDER BY total_paid DESC;"""

    user_sql = st.text_area("SQL Query", value=default_sql, height=180)
    if st.button("▶️ Execute Query on DuckDB"):
        try:
            res_df = con.execute(user_sql).df()
            st.success(f"Returned {len(res_df):,} rows.")
            st.dataframe(res_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"SQL Error: {e}")