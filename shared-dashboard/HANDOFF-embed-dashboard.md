# Adding the CxAlloy Commissioning Dashboard to the app

**From:** kspann · **Source repo:** `github.com/kspann-hub/project-dashboard-stream` (private)

## What this is
A self-refreshing commissioning dashboard for the Stream Data Centers – PHXA7 project.
It's a **static bundle** (`index.html` + JSON data) plus a small Python pipeline that
runs **hourly in GitHub Actions** to pull fresh data from CxAlloy and commit updated JSON.
No server, no database to host — the browser just loads pre-built JSON files.

When you're done: the dashboard shows up embedded in the app via an `<iframe>`, and it
keeps itself current every hour with no manual steps.

## ⚠️ Security — please don't skip
- This dashboard holds a **real client's private data**. The repo it lives in must stay
  **private / behind the app's existing auth**. An iframe does **not** add any protection —
  the JSON is directly fetchable by URL, so it inherits whatever access the app has.
  Only proceed if the app requires login to reach. (Confirmed: it does.)
- The CxAlloy **API secret must never reach the browser and must never be committed.**
  It lives only in GitHub Actions secrets. kspann will send you the two values separately
  (not in this doc, not in the repo).

---

## Steps

### 1. Copy these files from the source repo into the app repo
Bring over the pipeline **and** the dashboard folder:

| From source repo | What it is |
|---|---|
| `sync_logic.py` | Pulls data from CxAlloy → local SQLite (runs in Actions) |
| `export_json.py` | Builds the trimmed JSON the dashboard reads |
| `config.py` | Small config constants |
| `utils/` (whole folder) | Data-cleaning helpers used by `export_json.py` |
| `html-dashboard/` (whole folder) | The static dashboard: `index.html` + `data/*.json` |
| `.github/workflows/refresh-dashboard.yml` | The hourly refresh Action |

Put `html-dashboard/` wherever the app **serves static files verbatim** (e.g. `public/`,
`static/`, or an assets dir that is **not** processed by a bundler). The pipeline files
(`sync_logic.py`, etc.) can sit at the repo root or a subfolder — just keep them together
and note the path for step 2.

### 2. Point the workflow at the served data path
Open `.github/workflows/refresh-dashboard.yml` and set `DASHBOARD_OUT_DIR` to the folder
the app serves the JSON from (repo-relative). For example, if the dashboard lives at
`public/html-dashboard/`, use:

```yaml
env:
  DASHBOARD_OUT_DIR: public/html-dashboard/data
```

Also update the final "commit" step's `git add` path if you changed the folder, and — if
the pipeline files aren't at the repo root — add a `working-directory:` or a `cd` so
`python export_json.py` / the sync command run from where those `.py` files are.

‹fill in: the exact served path in this repo›

### 3. Add the two GitHub Actions secrets
In the app repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add both (names must match **exactly**):

- `CXALLOY_IDENTIFIER`
- `CXALLOY_SECRET`

kspann will give you the two values. **Paste only the value** — no quotes, and make sure
there's **no trailing space or newline** (a stray newline caused a failure on our end;
the code now strips it, but paste clean anyway).

### 4. Run the Action once to verify
**Actions tab → "Refresh dashboard data" → Run workflow** (on your default branch).
A healthy run (~1–2 min):
- "Sync CxAlloy → SQLite" prints `Found 1 projects` then row counts (hundreds of issues,
  thousands of checklists). **No 401/403.**
- "Export view-ready JSON" prints the project line and a KB size.
- "Commit refreshed data" either commits `chore(data): scheduled dashboard refresh` or
  says "No data changes this run." Both are success.

After this, the hourly cron (`0 * * * *` UTC) keeps it current automatically.

### 5. Embed it in the app
Use the same iframe pattern the app already uses for its other embedded dashboard, pointing
at the copied path. Because it's the **same origin** as the app, there are no
`X-Frame-Options` / CSP `frame-ancestors` issues to configure:

```html
<iframe
  src="‹path-to›/html-dashboard/index.html"
  style="width:100%; height:100vh; border:0;"
  title="Commissioning Dashboard">
</iframe>
```

The dashboard is already responsive/fit-to-screen, so it scales to the iframe.

---

## Verify you're done
- [ ] `html-dashboard/index.html` loads over **http(s)** in the app (not `file://`) and
      renders 4 tabs with charts — not a blank page.
- [ ] The `data/project_50506.json` file exists at the served path and is a few hundred KB
      to ~2 MB (not empty).
- [ ] The Action ran green and the hourly schedule is enabled (Actions tab shows it).
- [ ] The app repo is private / behind auth.

## Gotchas
- **Blank dashboard = wrong protocol or wrong data path.** `index.html` uses `fetch()`,
  so it must be served over http(s) and find `data/*.json` at a path relative to itself.
- **Don't let a bundler transform `html-dashboard/`** — it's meant to be served as-is.
- **Don't commit the CxAlloy secret or any `secrets.toml`.** Actions secrets only.
- The Action rebuilds everything fresh in the runner each hour and commits **only the JSON**
  when it changes — no database is stored in the repo.

## Questions
Ping kspann (kspann@criticalarccx.com) — happy to hop on and pair through steps 2–5.
