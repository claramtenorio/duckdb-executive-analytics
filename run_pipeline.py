import time
from typing import Callable

from src.etl.audit_anomalies import (
    audit_orders_anomalies,
    audit_products_anomalies,
    audit_reviews_anomalies,
    audit_geolocation_anomalies,
    audit_fanout_trap,
)
from src.etl.transform_silver import (
    clean_orders,
    clean_products,
    clean_reviews,
    clean_geolocation,
    clean_customers,
    clean_sellers,
    clean_order_items,
    clean_payments,
    clean_marketing_leads,
    clean_closed_deals,
)
from src.etl.build_gold import build_gold_layer
from src.analytics.executive_kpis import run_executive_kpis


def run_step(step_name: str, func: Callable[[], None]) -> float:
    print(f"\n{'=' * 72}")
    print(f"[ORCHESTRATOR] Starting Stage: {step_name}")
    print(f"{'=' * 72}")
    start_time = time.perf_counter()
    func()
    elapsed = time.perf_counter() - start_time
    print(f"\n[ORCHESTRATOR] Completed '{step_name}' in {elapsed:.2f}s")
    return elapsed


def run_silver_layer() -> None:
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


def run_data_quality_audits() -> None:
    audit_orders_anomalies()
    audit_products_anomalies()
    audit_reviews_anomalies()
    audit_geolocation_anomalies()
    audit_fanout_trap()


def main() -> None:
    pipeline_start = time.perf_counter()
    timings: dict[str, float] = {}

    stages = [
        ("1. Silver Layer Transformation (CSV -> Parquet)", run_silver_layer),
        ("2. Data Quality & Anomaly Audits", run_data_quality_audits),
        ("3. Gold Layer Star Schema Build (DuckDB OLAP)", build_gold_layer),
        ("4. Executive Analytics & KPI Reporting", run_executive_kpis),
    ]

    for stage_name, stage_func in stages:
        timings[stage_name] = run_step(stage_name, stage_func)

    total_time = time.perf_counter() - pipeline_start

    print(f"\n{'=' * 72}")
    print("PIPELINE EXECUTION SUMMARY")
    print(f"{'=' * 72}")
    for stage_name, duration in timings.items():
        pct = (duration / total_time) * 100
        print(f"  - {stage_name:<48}: {duration:>6.2f}s ({pct:>5.1f}%)")
    print(f"{'-' * 72}")
    print(f"  TOTAL END-TO-END EXECUTION TIME                 : {total_time:>6.2f}s")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()