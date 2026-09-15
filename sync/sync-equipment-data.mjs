#!/usr/bin/env node
// Pulls fresh equipment-tracker + dashboard data from a project's Google
// Apps Script endpoint (the same one the app used to call live) and
// upserts it into Supabase, so the app can read a fast, recent snapshot
// instead of waiting on Apps Script's cold-start + Sheets-read latency on
// every page load.
//
// This does NOT change what the Apps Script does — it still owns the
// clean/format logic that turns the raw Sheet into the shape the app
// expects. This script just calls that same endpoint on a schedule instead
// of the browser calling it live.
//
// Run via .github/workflows/sync-equipment-tracker-data.yml (schedule +
// manual "Run workflow" trigger). Requires the SUPABASE_SERVICE_KEY env var
// (a Supabase service_role key, NOT the anon key used in the browser — it
// needs to bypass RLS to write) set as a GitHub Actions secret.
//
// Covers every project in launchpad_projects that has a google_script_url
// on file — no per-project list to maintain here.

const SUPABASE_URL = 'https://rcnxetcomdrlxvlarqoc.supabase.co';
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;

if (!SUPABASE_SERVICE_KEY) {
    console.error('Missing SUPABASE_SERVICE_KEY environment variable.');
    process.exit(1);
}

async function supabaseRequest(path, options = {}) {
    const res = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
        ...options,
        headers: {
            apikey: SUPABASE_SERVICE_KEY,
            Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`,
            'Content-Type': 'application/json',
            Prefer: 'resolution=merge-duplicates',
            ...options.headers,
        },
    });
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(`Supabase request failed (${res.status} ${path}): ${body}`);
    }
    return res;
}

async function getProjectsToSync() {
    const res = await supabaseRequest(
        `launchpad_projects?select=project_key,google_script_url&google_script_url=not.is.null`
    );
    const rows = await res.json();
    // Belt-and-suspenders: also drop rows where the column is an empty
    // string rather than a real null (PostgREST's not.is.null only
    // excludes actual NULLs).
    return rows.filter(p => p.project_key && p.google_script_url);
}

async function syncEquipmentTracker(projectKey, scriptUrl) {
    const res = await fetch(scriptUrl);
    if (!res.ok) throw new Error(`Equipment tracker fetch failed (${res.status})`);
    const payload = await res.json();
    if (payload.error) throw new Error(`Apps Script returned an error: ${payload.error}`);

    await supabaseRequest('launchpad_equipment_tracker_data', {
        method: 'POST',
        body: JSON.stringify([{
            project_key: projectKey,
            data: payload.data || [],
            phase_rules: (payload.config && payload.config.phaseRules) || [],
            synced_at: new Date().toISOString(),
        }]),
    });
    console.log(`[${projectKey}] equipment tracker: synced ${(payload.data || []).length} row(s)`);
}

async function syncDashboard(projectKey, scriptUrl) {
    const res = await fetch(`${scriptUrl}?action=getDashboardData`);
    if (!res.ok) throw new Error(`Dashboard fetch failed (${res.status})`);
    const data = await res.json();
    if (data.error) throw new Error(`Apps Script returned an error: ${data.error}`);

    await supabaseRequest('launchpad_dashboard_data', {
        method: 'POST',
        body: JSON.stringify([{
            project_key: projectKey,
            data,
            synced_at: new Date().toISOString(),
        }]),
    });
    console.log(`[${projectKey}] dashboard: synced`);
}

async function main() {
    const projects = await getProjectsToSync();
    console.log(`Found ${projects.length} project(s) with a google_script_url set.`);

    // Equipment tracker is the primary thing this pipeline exists for, so
    // its failures fail the whole run (so a real problem gets noticed).
    // Dashboard failures are logged clearly but don't fail the run — a
    // project's dashboard Apps Script action can be broken/undeployed
    // independently (e.g. a 404 because getDashboardData was never wired
    // into doGet, or the deployment needs a new version) without that
    // being a reason to keep alerting on every scheduled run once it's a
    // known, separate issue to fix on that project's Apps Script side.
    let hadCriticalError = false;
    for (const project of projects) {
        const projectKey = project.project_key;
        try {
            await syncEquipmentTracker(projectKey, project.google_script_url);
        } catch (e) {
            hadCriticalError = true;
            console.error(`[${projectKey}] equipment tracker sync failed:`, e.message);
        }
        try {
            await syncDashboard(projectKey, project.google_script_url);
        } catch (e) {
            console.warn(`[${projectKey}] dashboard sync failed (non-fatal):`, e.message);
        }
    }
    if (hadCriticalError) process.exit(1);
}

main();
