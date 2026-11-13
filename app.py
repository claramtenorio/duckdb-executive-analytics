# Olist Medallion Lakehouse & Executive Analytics (DuckDB OLAP)

[![Live Executive Dashboard](https://img.shields.io/badge/🔴_Live_Demo-Streamlit_Cloud-FF4B4B?style=for-the-badge)](https://duckdb-executive-analytics-claramtenorio.streamlit.app/)

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)
![DuckDB](https://img.shields.io/badge/DuckDB-OLAP_Engine-FFF000?logo=duckdb&logoColor=black)
![Apache Parquet](https://img.shields.io/badge/PyArrow-Parquet-orange?logo=apacheparquet&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-Executive_App-FF4B4B?logo=streamlit&logoColor=white)

An end-to-end **Medallion Architecture Data Pipeline (`Bronze → Silver → Gold`)** and **Interactive Executive Analytics Suite** built on **1.5M+ real Brazilian E-Commerce and B2B Marketing Funnel records**.

🔗 **Live Interactive Application:** **[duckdb-executive-analytics-claramtenorio.streamlit.app](https://duckdb-executive-analytics-claramtenorio.streamlit.app/)**

Unlike standard exploratory notebooks, this project focuses on **production-grade data engineering**: strict grain enforcement, zero-copy Parquet processing, mathematical prevention of SQL fan-out traps, geospatial feature engineering, and sub-second OLAP execution powered by **DuckDB**.

---

## System Architecture (Medallion Pattern)

```text
+-----------------------------------------------------------------------------------+
| BRONZE LAYER (Raw Ingestion - 11 CSV Files | ~1.55M Rows | ~126 MB)               |
| Raw e-commerce transactions, reviews, 1M+ GPS coordinates, and B2B funnel leads.  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  [src/etl/transform_silver.py]
+-----------------------------------------------------------------------------------+
| SILVER LAYER (Cleaned, Deduplicated & Enriched - 10 Parquet Files | PyArrow)      |
| • Geolocation deduplication: 1,000,163 rows -> 19,011 unique ZIPs (99% smaller)   |
| • Date-truncation SLA fix: corrected 1,292 false-positive late delivery flags     |
| • Strict 1:1 grain deduplication on reviews & hierarchical median imputation      |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  [src/etl/build_gold.py]
+-----------------------------------------------------------------------------------+
| GOLD LAYER (Dimensional Star Schema - DuckDB OLAP Engine & Gold Parquet)          |
| • Pre-aggregated CTEs guaranteeing 0.00% financial Fan-Out across 1:N joins       |
| • Geospatial Haversine distance (km) computed in vectorized SQL                   |
| • End-to-end B2B-to-B2C lineage (Marketing Leads -> Closed Deals -> Seller GMV)   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v  [app.py & src/analytics/executive_kpis.py]
+-----------------------------------------------------------------------------------+
| CONSUMPTION LAYER (Streamlit Executive Dashboard + Live DuckDB SQL Workbench)     |
+-----------------------------------------------------------------------------------+
```

---

## Data Engineering & Quality Audits (`src/etl/audit_anomalies.py`)

Before modeling the Gold layer, automated audits uncovered critical anomalies in the raw dataset that distort standard analyses:

### 1. Eliminating the R$ 4.3M SQL Fan-Out Trap
Joining `order_items` (`1:N`) directly with `payments` (`1:N`) on `order_id` creates a Cartesian product on multi-item, multi-payment orders. Our DuckDB audit quantified the exact distortion:

| Metric | True Isolated Value | Naive `JOIN` Value (Fan-Out) | Artificial Distortion |
| :--- | :---: | :---: | :---: |
| **Merchandise GMV (`order_items`)** | `R$ 15,843,553.24` | `R$ 16,566,543.85` | **+R$ 722,990.61 (Fake GMV)** |
| **Total Paid (`payments`)** | `R$ 16,008,872.12` | `R$ 20,308,134.71` | **+R$ 4,299,262.59 (+26.8% Error)** |

* **Engineering Solution:** In `build_gold.py`, both `order_items` and `payments` are pre-aggregated to strict `1:1` `order_id` grain inside Common Table Expressions (`CTEs`) prior to joining into `fact_orders`, achieving **to-the-cent financial reconciliation**.

### 2. Fixing the `00:00:00` Timestamp SLA Trap
* `order_estimated_delivery_date` is stored at midnight (`00:00:00`), whereas `order_delivered_customer_date` includes exact hours and minutes.
* A naive timestamp comparison (`delivered > estimated`) falsely flags **7,827 orders (8.11%)** as late—including orders delivered *on the promised date* at `14:30`.
* **Engineering Solution:** Normalizing both timestamps to calendar days (`dt.normalize()`) revealed that **1,292 orders were false positives**, bringing the true late delivery rate to **6.77% (6,535 orders)**.

### 3. Preserving Revenue While Flagging Chronological Corruption
* **189 delivered orders** exhibit impossible logistics timestamps (e.g., `delivered_customer_date < delivered_carrier_date` or `carrier_date < purchase_timestamp`).
* Rather than dropping these rows and destroying valid financial GMV, the Silver layer isolates them with `has_chronological_error = True` so financial totals remain intact while SLA distributions remain uncorrupted.

### 4. Geospatial Compression & Bounding-Box Filtering
* Filtered out **31 invalid GPS coordinates** located outside Brazil's geographic bounding box (ocean/hemisphere errors) and compressed `1,000,163` raw coordinate logs into **`19,011` unique 5-digit ZIP code prefixes** (`58 MB CSV → 551 KB Parquet`).

---

## Key Executive Business Insights (`src/analytics/executive_kpis.py`)

1. **The Cost of Broken SLAs on Customer Retention:**
   * **On-Time Deliveries (avg 11.0 days):** Achieve a **4.29 ⭐** average rating with only **6.6%** 1-star reviews.
   * **Late Deliveries (avg 33.8 days):** Rating collapses to **2.27 ⭐**, and **53.8% of all reviews become 1-star** (an **8.1x surge** in severe dissatisfaction).
2. **Regional Last-Mile Bottlenecks (RJ vs. MG & Northeast):**
   * Despite similar average shipping distances from sellers (~500 km) and comparable GMV (~R$ 1.8M–2.0M), **Rio de Janeiro (`RJ`) suffers a 12.1% late delivery rate**—nearly **3x higher than Minas Gerais (`MG` at 4.6%)**.
   * **Bahia (`BA`)** faces an average shipping distance of **1,345 km**, pushing freight costs to **24.9% of total order value** and late rates to **12.2%**, highlighting the ROI of decentralizing fulfillment hubs to the Northeast.
3. **B2B Seller Funnel Activation Leakage:**
   * Across **8,000 Marketing Qualified Leads (MQLs)** and **842 Closed Deals**, less than **45% of signed sellers ever generate their first sale** on the marketplace (e.g., `organic_search` converts 271 deals, but only 113 become active revenue-generating sellers).
   * `paid_search` delivers **3x higher realized GMV per lead (`R$ 114.75`)** than `social` (`R$ 38.05`).
4. **Category Pareto Concentration (80/20 Rule):**
   * Out of 74 product categories, just **17 categories (23% of the catalog)** drive **79.81% of total marketplace GMV**, led by `health_beauty`, `watches_gifts`, and `bed_bath_table`.

---

## End-to-End Pipeline Performance

Executed on Apple Silicon via `python3 run_pipeline.py`:

| Pipeline Stage | Engine | Execution Time | Share |
| :--- | :--- | :---: | :---: |
| **1. Silver Layer Transformation (CSV → Parquet)** | `Pandas / PyArrow` | `3.34s` | `61.5%` |
| **2. Data Quality & Anomaly Audits** | `Pandas / DuckDB` | `0.97s` | `17.9%` |
| **3. Gold Layer Star Schema Build (5 Tables + Haversine)** | `DuckDB SQL` | `1.06s` | `19.5%` |
| **4. Executive Analytics & KPI Reporting (4 Complex Queries)** | `DuckDB SQL` | `0.06s` | `1.1%` |
| **TOTAL END-TO-END EXECUTION** | **Hybrid Lakehouse** | **`5.43s`** | **`100%`** |

---

## How to Run Locally

### 1. Clone the repository & install dependencies
```bash
git clone [https://github.com/claramtenorio/duckdb-executive-analytics.git](https://github.com/claramtenorio/duckdb-executive-analytics.git)
cd duckdb-executive-analytics
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Place raw CSV files in `data/bronze/`
Download the [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and the [Marketing Funnel by Olist](https://www.kaggle.com/datasets/olistbr/marketing-funnel-olist) and place all 11 CSV files inside `data/bronze/`.

### 3. Run the End-to-End Medallion Pipeline
```bash
python3 run_pipeline.py
```

### 4. Launch the Interactive Executive Dashboard
```bash
streamlit run app.py
```

---

## Repository Structure

```text
duckdb-executive-analytics/
├── app.py                          # Streamlit Executive Dashboard & Live DuckDB SQL Workbench
├── run_pipeline.py                 # End-to-end pipeline orchestrator with execution profiler
├── requirements.txt                # Project dependencies
├── data/
│   ├── bronze/                     # Raw CSV datasets (git-ignored)
│   ├── silver/                     # Cleaned & deduplicated Parquet files (git-ignored)
│   └── gold/                       # DuckDB OLAP database & Star Schema Parquets
└── src/
    ├── etl/
    │   ├── profile_bronze.py       # Automated raw data profiling & schema inspection
    │   ├── audit_anomalies.py      # SLA, chronology, geospatial & SQL fan-out audits
    │   ├── transform_silver.py     # Silver layer cleaning, normalization & Parquet export
    │   └── build_gold.py           # Gold Star Schema modeling in DuckDB SQL
    └── analytics/
        └── executive_kpis.py       # Strategic business KPI suite in DuckDB SQL
```