import pandas as pd
import ast

# ─── Column Name Standardization ──────────────────────────────────────────────
def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df.columns = (
        df.columns
        .str.strip()
        .str.lower()
        .str.replace(' ', '_', regex=False)
        .str.replace(r'[^\w]', '_', regex=True)
    )
    return df

def safe_parse(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return {}
    if isinstance(val, (dict, list)):
        return val
    try:
        return ast.literal_eval(str(val))
    except:
        return {}

# ─── People ───────────────────────────────────────────────────────────────────
def clean_people(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = standardize_columns(df)
    for col in ['person_id', 'company', 'first_name', 'last_name', 'role']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    df['full_name'] = df['first_name'] + ' ' + df['last_name']
    return df

# ─── Build Lookups ────────────────────────────────────────────────────────────
def build_lookups(people: pd.DataFrame, companies: pd.DataFrame) -> dict:
    person_lookup  = {}
    company_lookup = {}

    if not people.empty and 'person_id' in people.columns:
        person_lookup = dict(zip(
            people['person_id'].astype(str).str.strip(),
            people['company'].astype(str).str.strip()
        ))

    if not companies.empty and 'company_id' in companies.columns:
        company_lookup = dict(zip(
            companies['company_id'].astype(str).str.strip(),
            companies['name'].astype(str).str.strip()
        ))

    return {"person": person_lookup, "company": company_lookup}

# ─── Resolve Assigned Company ─────────────────────────────────────────────────
def resolve_assigned_company(df: pd.DataFrame, lookups: dict) -> pd.DataFrame:
    if df.empty or 'assigned_name' not in df.columns:
        return df
    df = df.copy()

    person_lookup  = lookups.get("person", {})
    company_lookup = lookups.get("company", {})

    def resolve(row):
        assigned_type = str(row.get('assigned_type', '')).strip().lower()
        assigned_name = str(row.get('assigned_name', '')).strip()
        assigned_key  = str(row.get('assigned_key', '')).strip()

        if not assigned_name or assigned_name in ['nan', 'None', '0', '']:
            return 'Not Assigned Yet'

        if assigned_type == 'person':
            company = person_lookup.get(assigned_key, '')
            return company if company else assigned_name

        elif assigned_type == 'company':
            company = company_lookup.get(assigned_key, '')
            return company if company else assigned_name

        elif assigned_type == 'role':
            # Role name is the assignment until a real company is assigned
            return assigned_name

        else:
            return assigned_name

    df['assigned_company'] = df.apply(resolve, axis=1)
    return df

# ─── Flatten Extended Status ──────────────────────────────────────────────────
def flatten_extended_status(df: pd.DataFrame, fields: list) -> pd.DataFrame:
    if 'extended_status' not in df.columns:
        return df
    parsed = df['extended_status'].apply(safe_parse)
    for field in fields:
        df[field] = parsed.apply(lambda x: x.get(field, '') if isinstance(x, dict) else '')
        if field.endswith('_date'):
            df[field] = df[field].apply(
                lambda v: str(v).strip().split('\n')[-1].strip()
                if pd.notna(v) and str(v).strip() else ''
            )
            df[field] = df[field].replace('', pd.NA)
    return df

# ─── Issues ───────────────────────────────────────────────────────────────────
def clean_issues(df: pd.DataFrame, lookups: dict) -> pd.DataFrame:
    if df.empty:
        return df
    df = standardize_columns(df)

    # Drop rows where status is missing or numeric (bad data)
    if 'status' in df.columns:
        df['status'] = df['status'].astype(str).str.strip()
        df = df[~df['status'].isin(['0', 'nan', 'None', ''])]

    # Flatten extended_status
    df = flatten_extended_status(df, [
        'open_date', 'open_person', 'in_progress_date', 'in_progress_person',
        'pending_review_date', 'pending_review_person', 'closed_date', 'closed_person'
    ])

    # Dates
    for col in ['date_created', 'date_closed', 'due_date']:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')

    # Days open
    today = pd.Timestamp.now()
    if 'date_created' in df.columns:
        df['days_open'] = (today - df['date_created']).dt.days.fillna(0).astype(int)

    # Aging category
    def aging_cat(row):
        if str(row.get('status', '')).lower() == 'closed':
            return 'Closed'
        d = row.get('days_open', 0)
        if d > 60:  return '>60 Days'
        if d >= 45: return '45-60 Days'
        return 'Under 45 Days'
    df['aging_category'] = df.apply(aging_cat, axis=1)

    for col in ['status', 'priority', 'discipline', 'assigned_name', 'assigned_type']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    df = resolve_assigned_company(df, lookups)
    return df

# ─── Checklists ───────────────────────────────────────────────────────────────
def clean_checklists(df: pd.DataFrame, lookups: dict) -> pd.DataFrame:
    if df.empty:
        return df
    df = standardize_columns(df)

    # Derive commissioning level from type_name (L2, L3, etc.)
    if 'type_name' in df.columns:
        df['level'] = df['type_name'].str.extract(r'(L\d)', expand=False)
        # Map non-Lx types: Component Verification → L4, FAT → FAT
        mask_cv = df['type_name'].str.contains('Component Verification', case=False, na=False)
        mask_fat = df['type_name'].str.contains('FAT', case=False, na=False)
        df.loc[mask_cv, 'level'] = 'L4'
        df.loc[mask_fat, 'level'] = 'FAT'
        df['level'] = df['level'].fillna('Other')
 

    df = flatten_extended_status(df, [
        'not_started_date', 'in_progress_date',
        'gc_to_verify_date', 'finished_date',
    ])

    if 'date_created' in df.columns:
        df['date_created'] = pd.to_datetime(df['date_created'], errors='coerce')

    for col in ['status', 'discipline', 'assigned_name', 'assigned_type', 'type_name']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    df = resolve_assigned_company(df, lookups)
    return df

# ─── Tests ────────────────────────────────────────────────────────────────────
def clean_tests(df: pd.DataFrame, lookups: dict) -> pd.DataFrame:
    if df.empty:
        return df
    df = standardize_columns(df)

    df = flatten_extended_status(df, [
        'script_in_development_date', 'assigned_date',
        'in_progress_date', 'failed_date', 'passed_date'
    ])

    if 'attempts' in df.columns:
        def last_attempt_date(val):
            attempts = safe_parse(val)
            if isinstance(attempts, list) and attempts:
                return attempts[-1].get('status_change_date', '')
            return ''
        df['status_change_date'] = df['attempts'].apply(last_attempt_date)

    if 'date_created' in df.columns:
        df['date_created'] = pd.to_datetime(df['date_created'], errors='coerce')

    for col in ['status', 'discipline', 'assigned_name', 'assigned_type']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    df = resolve_assigned_company(df, lookups)
    return df

# ─── Equipment ────────────────────────────────────────────────────────────────
def clean_equipment(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = standardize_columns(df)
    for col in ['status', 'discipline', 'type', 'floor', 'building']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    return df

# ─── Master Clean ─────────────────────────────────────────────────────────────
def clean_all(sheets: dict) -> dict:
    cleaned = {}

    people    = clean_people(sheets.get('People', pd.DataFrame()))
    companies = standardize_columns(sheets.get('Companies', pd.DataFrame()))
    cleaned['People']    = people
    cleaned['Companies'] = companies

    lookups = build_lookups(people, companies)

    cleaned['Issues']     = clean_issues(sheets.get('Issues', pd.DataFrame()), lookups)
    cleaned['Checklists'] = clean_checklists(sheets.get('Checklists', pd.DataFrame()), lookups)
    cleaned['Tests']      = clean_tests(sheets.get('Tests', pd.DataFrame()), lookups)
    cleaned['Equipment']  = clean_equipment(sheets.get('Equipment', pd.DataFrame()))

    for tab, df in sheets.items():
        if tab not in cleaned:
            cleaned[tab] = standardize_columns(df)

    return cleaned