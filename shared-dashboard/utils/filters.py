import pandas as pd

def build_company_lookup(people_df: pd.DataFrame) -> dict:
    """Build a person_id → company name lookup from the People tab."""
    if people_df.empty:
        return {}
    lookup = {}
    for _, row in people_df.iterrows():
        person_id = str(row.get('person_id', ''))
        company = row.get('company', '')
        if person_id and company:
            lookup[person_id] = company
    return lookup

def resolve_company(df: pd.DataFrame, lookup: dict) -> pd.DataFrame:
    """Add an assigned_company column by resolving person/role to company name."""
    if df.empty or 'assigned_name' not in df.columns or 'assigned_type' not in df.columns:
        return df
    df = df.copy()
    def resolve(row):
        assigned_type = str(row.get('assigned_type', '')).lower()
        if assigned_type == 'company':
            return row['assigned_name']
        if assigned_type == 'person':
            key = str(row.get('assigned_key', ''))
            return lookup.get(key, row['assigned_name'])
        # role — keep as-is
        return row['assigned_name']
    df['assigned_company'] = df.apply(resolve, axis=1)
    return df


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    
    filtered = df.copy()

    discipline = filters.get("discipline", "All")
    contractor = filters.get("contractor", "All")
    status     = filters.get("status", "All")

    if discipline != "All" and "discipline" in filtered.columns:
        filtered = filtered[filtered["discipline"] == discipline]

    if contractor != "All" and "assigned_company" in filtered.columns:
        filtered = filtered[filtered["assigned_company"] == contractor]

    if status != "All" and "status" in filtered.columns:
        filtered = filtered[filtered["status"] == status]

    return filtered
