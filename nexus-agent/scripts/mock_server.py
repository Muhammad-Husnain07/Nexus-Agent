"""Nexus Agent Mock API Server.
Run with: uvicorn scripts.mock_server:app --port 8001
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel

app = FastAPI(title="Nexus Mock API")

DB_STATE: dict[str, Any] = {
    "datasources": ["banking_db", "analytics_db", "hr_db", "retail_db", "logistics_db"],
    "tables": {
        "banking_db": ["transactions", "users", "atm_failures", "accounts"],
        "analytics_db": ["web_traffic", "server_metrics", "user_sessions"],
        "hr_db": ["employees", "payroll", "departments"],
        "retail_db": ["orders", "products", "customers", "inventory"],
        "logistics_db": ["shipments", "warehouses", "routes"],
    },
    "columns": {
        "transactions": ["id", "account_id", "amount", "status", "timestamp", "channel"],
        "atm_failures": ["id", "error_code", "location", "timestamp", "amount", "atm_id", "duration_min"],
        "accounts": ["id", "customer_name", "balance", "currency", "status"],
        "web_traffic": ["id", "page_url", "visitors", "bounce_rate", "avg_session_s", "date"],
        "server_metrics": ["id", "server_name", "cpu_pct", "memory_pct", "disk_pct", "request_count"],
        "employees": ["id", "name", "department", "salary", "hire_date", "status"],
        "payroll": ["id", "employee_id", "gross_pay", "deductions", "net_pay", "pay_period"],
        "orders": ["id", "customer_id", "product_id", "quantity", "total", "status", "order_date"],
        "products": ["id", "name", "category", "price", "stock", "supplier"],
        "inventory": ["id", "product_id", "warehouse", "quantity", "reorder_level", "last_restocked"],
        "shipments": ["id", "tracking_no", "origin", "destination", "status", "eta", "weight_kg"],
    },
    "configs": {},
    "dashboards": [],
}

_COLUMN_GENERATORS: dict[str, list[Any]] = {
    "status": ["PENDING", "COMPLETED", "FAILED", "PROCESSING", "CANCELLED"],
    "error_code": ["E1001", "E2002", "E3003", "E4004", "E5005"],
    "channel": ["ATM", "MOBILE", "WEB", "BRANCH", "POS"],
    "currency": ["USD", "EUR", "GBP", "JPY", "CAD"],
    "department": ["ENGINEERING", "SALES", "FINANCE", "HR", "OPERATIONS"],
    "category": ["ELECTRONICS", "CLOTHING", "GROCERIES", "BOOKS", "TOYS"],
    "supplier": ["ACME CORP", "GLOBEX", "INITECH", "UMBRELLA", "STARK"],
    "warehouse": ["WH-NORTH", "WH-SOUTH", "WH-EAST", "WH-WEST"],
    "origin": ["NYC", "LAX", "CHI", "HOU", "SEA"],
    "destination": ["BOS", "MIA", "DEN", "PHX", "ATL"],
    "server_name": ["api-01", "api-02", "db-01", "cache-01", "worker-01"],
    "page_url": ["/home", "/pricing", "/docs", "/blog", "/checkout"],
}


class QueryPayload(BaseModel):
    table: str
    columns: list[str] = []
    filters: dict = {}


class DashboardPayload(BaseModel):
    title: str
    widgets: list[dict] = []


# ============================================================================
# 1. Data Retrieval & Workflow Endpoints
# ============================================================================


@app.get("/datasources")
async def get_datasources():
    return {"results": DB_STATE["datasources"]}


@app.get("/datasources/{ds_id}/tables")
async def get_tables(ds_id: str):
    if ds_id not in DB_STATE["tables"]:
        raise HTTPException(status_code=404, detail="Datasource not found")
    return {"results": DB_STATE["tables"][ds_id]}


@app.get("/tables/{table_name}/columns")
async def get_columns(table_name: str):
    if table_name not in DB_STATE["columns"]:
        raise HTTPException(status_code=404, detail="Table not found")
    return {"results": DB_STATE["columns"][table_name]}


@app.post("/query")
async def query_data(payload: QueryPayload):
    await asyncio.sleep(0.3)

    if payload.table not in DB_STATE["columns"]:
        raise HTTPException(status_code=404, detail=f"Table '{payload.table}' not found")

    available = DB_STATE["columns"][payload.table]
    requested = payload.columns or available[:4]

    # Cap requested columns to those the table actually has (defensive)
    requested = [c for c in requested if c in available]

    mock_rows = []
    row_count = random.randint(5, 9)
    for i in range(1, row_count + 1):
        row = {"id": i}
        for col in requested:
            if col == "id":
                continue
            if col in ("amount", "balance", "gross_pay", "net_pay", "total", "price"):
                row[col] = round(random.uniform(10.0, 5000.0), 2)
            elif col in ("quantity", "stock", "visitors", "request_count", "weight_kg"):
                row[col] = random.randint(1, 5000)
            elif col in ("cpu_pct", "memory_pct", "disk_pct", "bounce_rate", "avg_session_s"):
                row[col] = round(random.uniform(0.0, 100.0), 1)
            elif col in ("salary", "deductions"):
                row[col] = round(random.uniform(20000.0, 150000.0), 2)
            elif col == "duration_min":
                row[col] = random.randint(1, 240)
            elif col in ("timestamp", "hire_date", "order_date", "pay_period", "date", "eta", "last_restocked"):
                row[col] = f"2026-0{random.randint(1, 7)}-{random.randint(10, 28)}T00:00:00Z"
            elif col in ("tracking_no",):
                row[col] = f"TRK{random.randint(100000, 999999)}"
            elif col in ("customer_name", "name"):
                names = ["Alice", "Bob", "Carol", "David", "Eve", "Frank", "Grace", "Hank"]
                row[col] = f"{random.choice(names)} {random.choice(['Smith', 'Jones', 'Lee', 'Wu', 'Patel'])}"
            elif col in DB_STATE and col in ("server_name", "page_url", "origin", "destination", "warehouse", "supplier", "category", "department", "currency", "channel", "status", "error_code"):
                row[col] = random.choice(_COLUMN_GENERATORS[col])
            else:
                row[col] = f"value_{i}"
        mock_rows.append(row)

    return {"results": mock_rows, "count": len(mock_rows)}


# ============================================================================
# 2. Artifact Generation Endpoints
# ============================================================================


@app.post("/dashboards")
async def create_dashboard(payload: DashboardPayload):
    dashboard_id = f"dash_{int(time.time())}_{random.randint(100, 999)}"
    DB_STATE["dashboards"].append({"id": dashboard_id, **payload.model_dump()})
    return {
        "dashboard_id": dashboard_id,
        "status": "created",
        "url": f"http://localhost:3000/dashboards/{dashboard_id}",
        "widget_count": len(payload.widgets),
    }


# ============================================================================
# 3. Configuration & Stateful Endpoints
# ============================================================================


@app.get("/config/{key}")
async def get_config(key: str):
    if key not in DB_STATE["configs"]:
        raise HTTPException(status_code=404, detail="Config not found")
    return {"key": key, "value": DB_STATE["configs"][key]}


@app.post("/config/{key}")
async def set_config(key: str, value: Any = Body(..., embed=True)):
    DB_STATE["configs"][key] = value
    return {"key": key, "value": value, "status": "updated"}


# ============================================================================
# 4. Error & Edge Case Endpoints
# ============================================================================


@app.get("/error/timeout")
async def timeout_endpoint():
    await asyncio.sleep(30)
    return {"status": "should_never_reach_here"}


@app.get("/error/server")
async def server_error_endpoint():
    raise HTTPException(status_code=500, detail="Simulated internal server error")
