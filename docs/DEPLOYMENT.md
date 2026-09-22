# Deployment

The app bootstraps itself: on every start it creates missing tables and syncs the rule files; with
`PAYROLL_AUTO_SEED=true` and an empty database it also builds the synthetic company, five demo users and the
Jan–Sep 2026 payroll history (≈45–60 s, once). Tested on SQLite and PostgreSQL 16.

| Variable | Purpose |
|---|---|
| `PAYROLL_SECRET_KEY` | JWT signing key (required outside dev) |
| `PAYROLL_DEMO_PASSWORD` | Password for the five `…@demo.ie` users |
| `PAYROLL_AUTO_SEED` | `true` → seed demo data if the DB is empty |
| `PAYROLL_PUBLIC_DEMO` | `true` → login page shows and prefills the demo login (synthetic data only) |
| `PAYROLL_DATABASE_URL` | Optional. Default SQLite file. `postgres://…` / `postgresql://…` URLs are accepted as-is |

---

## Option A — Streamlit Community Cloud (recommended for a portfolio link)

Free, one public URL, no database account needed.

1. Push this repository to GitHub (public, or private with Streamlit's GitHub access).
2. Go to **https://share.streamlit.io** → sign in with GitHub → **Create app** → *Deploy a public app from GitHub*.
3. Repository: `<you>/irish-payroll` · Branch: `main` · Main file path: **`ui/app.py`**.
4. **Advanced settings** → Python version **3.11** → **Secrets**: paste the contents of
   [`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example) with your own values.
5. **Deploy**. The first visit takes about a minute while the demo data is built; afterwards it's instant.
6. Optional: in app settings, choose a custom subdomain such as `irish-payroll-vignesh.streamlit.app`.

Notes: with the default SQLite file, visitors' changes are wiped whenever the app restarts or sleeps (the demo
rebuilds itself — ideal for a public demo). For persistence, create a free PostgreSQL database (e.g. Neon) and add
`PAYROLL_DATABASE_URL` to the secrets. Apps sleep after inactivity; the first visitor clicks "wake up".

## Option B — Render (UI + API + PostgreSQL)

1. Push to GitHub.
2. **https://dashboard.render.com** → **New → Blueprint** → select the repo. Render reads [`render.yaml`](../render.yaml)
   and creates `payroll-db` (PostgreSQL), `irish-payroll-ui` (Streamlit) and `irish-payroll-api` (FastAPI).
3. When prompted, enter `PAYROLL_DEMO_PASSWORD` for both services (same value). The secret keys are generated.
4. Open the UI service URL; the API's Swagger docs are at `<api-url>/docs`.

Free-tier caveats: services sleep when idle (~50 s cold start) and free PostgreSQL databases expire after a limited
period — check Render's current free-tier terms.

## Option C — any Docker host

```bash
cp .env.example .env    # set real secrets
docker compose up --build
```
UI on :8501, API on :8000. (Compose file provided; not executed in the original build environment.)

## Before sharing the link

* Keep `PAYROLL_PUBLIC_DEMO=true` only for synthetic data. For anything real: set it to `false`, set
  `PAYROLL_ENV=production` (enforces a secret key and four-eyes approval) and put the app behind HTTPS/SSO.
* Add the live link to the top of `README.md`, your CV and LinkedIn *Featured* section.
