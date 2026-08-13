import time
import hmac
import hashlib
import json
import requests
import pandas as pd
import streamlit as st

BASE_URL = "https://tq.cxalloy.com/api/v1"

def _make_headers(secret: str, identifier: str, body_str: str = None) -> dict:
    timestamp = str(int(time.time()))
    message = (body_str + timestamp) if body_str else timestamp
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type":       "application/json",
        "cxalloy-identifier": identifier,
        "cxalloy-signature":  signature,
        "cxalloy-timestamp":  timestamp,
        "user-agent":         "criticalarc-dashboard / v1.0"
    }

def _get(endpoint: str, params: dict = None) -> list:
    identifier = st.secrets["cxalloy"]["identifier"]
    secret     = st.secrets["cxalloy"]["secret"]
    results = []
    page = 1

    while True:
        p = params.copy() if params else {}
        p["page"] = page

        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            headers=_make_headers(secret, identifier),
            params=p
        )

        if resp.status_code != 200:
            st.error(f"CxAlloy GET error {resp.status_code} on {endpoint}: {resp.text}")
            break

        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
            if len(data) < 500:
                break
        else:
            break

        page += 1

    return results

def _post(endpoint: str, body: dict, include: list = None) -> list:
    identifier = st.secrets["cxalloy"]["identifier"]
    secret     = st.secrets["cxalloy"]["secret"]
    results = []
    page = 1

    while True:
        payload = {**body, "page": page}
        if include:
            payload["include"] = include

        # Must use same string for both signature and request body
        body_str = json.dumps(payload, separators=(',', ':'))

        resp = requests.post(
            f"{BASE_URL}/{endpoint}",
            headers=_make_headers(secret, identifier, body_str=body_str),
            data=body_str  # not json= — must be identical to signed string
        )

        if resp.status_code != 200:
            st.error(f"CxAlloy POST error {resp.status_code} on {endpoint}: {resp.text}")
            break

        data = resp.json()

        # API wraps POST results in "records" key
        if isinstance(data, dict):
            records = data.get("records", [])
        elif isinstance(data, list):
            records = data
        else:
            break

        results.extend(records)
        if len(records) < 500:
            break

        page += 1

    return results

@st.cache_data(ttl=600)
def load_all_projects() -> pd.DataFrame:
    data = _get("project")
    return pd.DataFrame(data) if data else pd.DataFrame()

@st.cache_data(ttl=60)
def load_project_data(project_id: int) -> dict:
    from utils.cleaning import clean_all
    import sqlite3

    conn = sqlite3.connect("dashboard_data.db")
    results = {}
    for table in ["Issues", "Checklists", "Tests", "People", "Companies", "Equipment"]:
        try:
            df = pd.read_sql(f"SELECT * FROM [{table}] WHERE _project_id = ?", conn, params=(project_id,))
            df = df.drop(columns=["_project_id"], errors="ignore")
            # Parse JSON strings back into dicts/lists
            for col in df.columns:
                df[col] = df[col].apply(lambda x: json.loads(x) if isinstance(x, str) and x.startswith(('[', '{')) else x)
            results[table] = df
        except Exception:
            results[table] = pd.DataFrame()
    conn.close()

    return clean_all(results)