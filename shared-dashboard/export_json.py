"""
export_json.py — Build view-ready JSON for the HTML dashboard.

Reads the SQLite store, runs the SAME clean_all() pipeline the Streamlit app
uses, pre-parses equipment attributes, and writes one JSON file per project
(plus an index). This is the exact step that will later run hourly in GitHub
Actions — only the OUTPUT path changes.

Run:  python export_json.py
Out:  ../html-dashboard/data/project_<id>.json  and  projects.json
"""

import os
import json
import sqlite3
import ast
import pandas as pd

from utils.cleaning import clean_all

DB_PATH = os.environ.get("DASHBOARD_DB_PATH", "dashboard_data.db")
# Where the view-ready JSON is written. Override in CI to target wherever the
# hosting app serves static files from (default = the local html-dashboard).
OUT_DIR = os.environ.get("DASHBOARD_OUT_DIR", os.path.join("..", "html-dashboard", "data"))

TABLES = ["Issues", "Checklists", "Tests", "People", "Companies", "Equipment"]


def _read_table(conn, table, project_id):
    """Mirror load_project_data(): read rows, JSON-decode embedded columns."""
    try:
        df = pd.read_sql(
            f"SELECT * FROM [{table}] WHERE _project_id = ?", conn, params=(project_id,)
        )
    except Exception:
        return pd.DataFrame()
    df = df.drop(columns=["_project_id"], errors="ignore")
    for col in df.columns:
        df[col] = df[col].apply(
            lambda x: json.loads(x) if isinstance(x, str) and x.startswith(("[", "{")) else x
        )
    return df


def _get_attr(attrs, name):
    """Pull a named value out of the equipment 'attributes' list (mirrors layout.py)."""
    try:
        if isinstance(attrs, str):
            attrs = ast.literal_eval(attrs)
        if isinstance(attrs, list):
            for a in attrs:
                if isinstance(a, dict) and a.get("name") == name:
                    v = str(a.get("value", "")).strip()
                    return v if v else "Unknown"
    except Exception:
        pass
    return "Unknown"


# Only the columns each tab actually renders — keeps the JSON small.
KEEP = {
    "issues": ["name", "description", "status", "priority", "discipline",
               "assigned_company", "assigned_name", "aging_category", "days_open",
               "date_created", "in_progress_date", "date_closed", "asset_key"],
    "checklists": ["level", "status", "discipline", "assigned_company",
                   "assigned_type", "asset_key", "type_name"],
    "tests": ["name", "status", "assigned_company", "assigned_name", "discipline",
              "attempt_count", "asset_name", "asset_key"],
    "equipment": ["equipment_id", "name", "type", "discipline", "status", "space",
                  "building_phase", "floor_parsed"],
    "companies": ["name"],
}


# ── Sanity gate ─────────────────────────────────────────────────────
# Guard against a broken sync silently committing empty/partial data. A table
# shrinking past this fraction of its last committed size fails the run (red X
# in Actions) instead of overwriting good JSON with garbage.
DROP_THRESHOLD = float(os.environ.get("DASHBOARD_MIN_RETAIN", "0.5"))
COUNTED_TABLES = ["issues", "checklists", "tests", "equipment", "companies"]


def _existing_counts(out_path):
    """Row counts per table from the last committed JSON, or None if absent."""
    if not os.path.exists(out_path):
        return None
    try:
        with open(out_path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        return None
    return {t: len(old.get(t, [])) for t in COUNTED_TABLES}


def _sanity_problems(payload, old_counts):
    """Reasons this payload should NOT be written (empty list == all good)."""
    problems = []
    new_counts = {t: len(payload.get(t, [])) for t in COUNTED_TABLES}
    # Hard floor: zero issues means the sync almost certainly broke.
    if new_counts["issues"] == 0:
        problems.append("issues == 0 (expected > 0)")
    # Relative floor: no table may shrink past DROP_THRESHOLD of its last size.
    if old_counts:
        for t in COUNTED_TABLES:
            old, new = old_counts[t], new_counts[t]
            if old > 0 and new < old * DROP_THRESHOLD:
                pct = (1 - new / old) * 100
                problems.append(
                    f"{t} dropped {pct:.0f}% ({old} -> {new}, below "
                    f"{DROP_THRESHOLD:.0%} retain floor)"
                )
    return problems


def _jsonable(df, keep=None):
    """Convert a cleaned DataFrame to a list of plain JSON records."""
    if df is None or df.empty:
        return []
    df = df.copy()
    if keep:
        df = df[[c for c in keep if c in df.columns]]
    # Stringify datetimes; drop nested objects we don't need in the browser.
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%d").where(df[col].notna(), None)
    df = df.where(pd.notna(df), None)
    recs = df.to_dict(orient="records")
    # Final scrub: pandas NaN/NaT that slipped through -> None; keep JSON small/clean.
    for r in recs:
        for k, v in list(r.items()):
            if isinstance(v, float) and pd.isna(v):
                r[k] = None
    return recs


def _last_synced_at(conn, project_id):
    """Latest successful CxAlloy sync time for this project as UTC ISO8601, or None.

    _sync_log.synced_at is written by sync_logic with SQLite datetime('now'), i.e.
    UTC 'YYYY-MM-DD HH:MM:SS'. We emit ISO8601 with a 'Z' so the browser renders it
    in the viewer's local timezone — this is the real 'data as of' moment, not page
    load time.
    """
    try:
        row = conn.execute(
            "SELECT MAX(synced_at) FROM _sync_log WHERE project_id = ? AND status = 'ok'",
            (project_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0]:
        return None
    return str(row[0]).replace(" ", "T") + "Z"


def export_project(conn, project_id, project_name):
    raw = {t: _read_table(conn, t, project_id) for t in TABLES}
    cleaned = clean_all(raw)

    # Pre-parse Building Phase / Floor onto equipment so the browser doesn't
    # have to parse the attributes blob.
    eq = cleaned.get("Equipment", pd.DataFrame())
    if not eq.empty and "attributes" in eq.columns:
        eq = eq.copy()
        eq["building_phase"] = eq["attributes"].apply(lambda x: _get_attr(x, "Building Phase"))
        eq["floor_parsed"] = eq["attributes"].apply(lambda x: _get_attr(x, "Floor"))
        eq = eq.drop(columns=["attributes", "systems", "areas_served"], errors="ignore")
        cleaned["Equipment"] = eq

    payload = {
        "project_id": project_id,
        "project_name": project_name,
        "data_synced_at": _last_synced_at(conn, project_id),
        "issues": _jsonable(cleaned.get("Issues"), KEEP["issues"]),
        "checklists": _jsonable(cleaned.get("Checklists"), KEEP["checklists"]),
        "tests": _jsonable(cleaned.get("Tests"), KEEP["tests"]),
        "equipment": _jsonable(cleaned.get("Equipment"), KEEP["equipment"]),
        "companies": _jsonable(cleaned.get("Companies"), KEEP["companies"]),
    }

    out = os.path.join(OUT_DIR, f"project_{project_id}.json")

    # Sanity gate: compare against the last committed file BEFORE overwriting it.
    problems = _sanity_problems(payload, _existing_counts(out))
    if problems:
        print(f"  ✗ {project_name} (#{project_id}) FAILED sanity gate — not written:")
        for p in problems:
            print(f"      - {p}")
        return {"project_id": project_id, "name": project_name, "ok": False}

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(
        f"  {project_name} (#{project_id}): "
        f"{len(payload['issues'])} issues, {len(payload['checklists'])} checklists, "
        f"{len(payload['tests'])} tests, {len(payload['equipment'])} equipment "
        f"-> {out} ({os.path.getsize(out)//1024} KB)"
    )
    return {"project_id": project_id, "name": project_name, "ok": True}


def main():
    conn = sqlite3.connect(DB_PATH)
    # Discover projects present in the store (join names if a Projects list exists).
    pids = [
        r[0]
        for r in conn.execute("SELECT DISTINCT _project_id FROM Issues").fetchall()
    ]
    # Names: try Companies/People project_id -> fall back to id. The live app gets
    # names from the API 'project' endpoint; for the pilot we label by known id.
    names = {50506: "Stream Data Centers - PHXA7"}

    def name_for(pid):
        try:
            return names.get(int(pid)) or names.get(pid) or f"Project {pid}"
        except (TypeError, ValueError):
            return names.get(pid, f"Project {pid}")

    index = []
    for pid in pids:
        index.append(export_project(conn, pid, name_for(pid)))
    conn.close()

    failed = [r for r in index if not r.get("ok")]
    if failed:
        # Leave projects.json (and the good files on disk) untouched, and fail the
        # run so a bad sync shows up as a red X in Actions instead of committing.
        names = ", ".join(f"{r['name']} (#{r['project_id']})" for r in failed)
        print(f"\n✗ Sanity gate failed for {len(failed)} project(s): {names}")
        print("  projects.json left unchanged; exiting non-zero.")
        raise SystemExit(1)

    written = [{"project_id": r["project_id"], "name": r["name"]} for r in index]
    with open(os.path.join(OUT_DIR, "projects.json"), "w", encoding="utf-8") as f:
        json.dump(written, f, ensure_ascii=False)
    print(f"\nWrote {len(written)} project file(s) + projects.json to {OUT_DIR}")


if __name__ == "__main__":
    main()
