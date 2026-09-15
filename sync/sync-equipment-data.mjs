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
// To sync more projects, just add their project_key here.
const PROJECT_KEYS = ['STY4'];

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

async function getProject(projectKey) {
    const res = await supabaseRequest(
        `launchpad_projects?project_key=eq.${encodeURIComponent(projectKey)}&select=project_key,google_script_url`
    );
    const rows = await res.json();
    return rows[0] || null;
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
    let hadError = false;
    for (const projectKey of PROJECT_KEYS) {
        try {
            const project = await getProject(projectKey);
            if (!project || !project.google_script_url) {
                console.warn(`[${projectKey}] no google_script_url on file in launchpad_projects — skipping`);
                continue;
            }
            await syncEquipmentTracker(projectKey, project.google_script_url);
            await syncDashboard(projectKey, project.google_script_url);
        } catch (e) {
            hadError = true;
            console.error(`[${projectKey}] sync failed:`, e.message);
        }
    }
    if (hadError) process.exit(1);
}

main();
