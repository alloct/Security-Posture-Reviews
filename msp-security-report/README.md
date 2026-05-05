# MSP Security Posture Report

A self-hosted, internal-use web application for Managed Service Providers and
MDR teams to run an annual security posture assessment for each client and
produce a branded, professional PDF report.

The application is intentionally simple: FastAPI + Jinja2 + HTMX, a single
SQLite file, WeasyPrint for PDF rendering, and a single-service `docker-compose`
deployment. There is no authentication layer; deploy it on a network-restricted
host such as an internal VLAN or a Tailscale-only node.

---

## Features

- Track clients and run a year-on-year assessment against each one.
- Multi-step wizard with eight control domains and ~40 weighted questions.
- Optional Nessus CSV ingestion that adjusts the posture score and feeds a
  vulnerability-findings section in the report.
- Branded PDF output (logo, primary colour, footer text) generated from a
  WeasyPrint-friendly HTML template.
- Per-client report archive with re-download.
- Alembic migrations and a seeded `MSPSettings` row on first run.

---

## Stack

| Layer       | Technology                                           |
| ----------- | ---------------------------------------------------- |
| Backend     | Python 3.11, FastAPI, SQLAlchemy 2, Pydantic v2      |
| Database    | SQLite (file-based, single volume mount)             |
| Migrations  | Alembic (batch mode, SQLite-friendly)                |
| Frontend    | Jinja2 templates, plain CSS, HTMX                    |
| PDF engine  | WeasyPrint                                            |
| CSV parser  | pandas                                                |
| Container   | Docker + Docker Compose                              |

---

## Repository layout

```
msp-security-report/
  app/
    main.py                 # FastAPI factory + dashboard route
    database.py             # Engine + session
    models.py               # ORM models
    dependencies.py         # Templates, settings, upload-dir helpers
    routers/
      clients.py            # Client CRUD
      assessments.py        # Wizard + Nessus upload
      reports.py            # Generate + download PDFs
      settings.py           # MSP branding settings
    services/
      questions.py          # Assessment question catalogue
      scoring.py            # Score + recommendations engine
      nessus_parser.py      # Nessus CSV ingestion
      report_generator.py   # WeasyPrint report builder
    templates/              # Jinja2 templates (UI + report)
    static/
      css/main.css
      uploads/              # Logos, Nessus CSVs, generated PDFs
  alembic/                  # Alembic migrations
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

---

## Quick start with Docker (recommended)

You only need Docker and Docker Compose installed.

```bash
git clone https://github.com/<your-org>/msp-security-report.git
cd msp-security-report

# Build and start the container
docker compose up -d --build

# Tail logs to confirm it has started
docker compose logs -f
```

Open <http://localhost:8000> in a browser. The app boots, runs
`Base.metadata.create_all`, and seeds a default `MSPSettings` row so the UI is
immediately usable. To replace the seeded values, open the **Settings** page and
upload your logo, set the company name, primary brand colour, and footer text.

### Persistent volumes

The compose file mounts two host paths:

- `./data` -> `/app/data` (SQLite database file `app.db`)
- `./app/static/uploads` -> `/app/app/static/uploads` (logo, Nessus CSVs,
  generated PDF reports)

Both directories are created automatically on first run.

### Stop / restart / rebuild

```bash
docker compose stop          # stop without removing
docker compose down          # stop and remove the container
docker compose up -d --build # rebuild after pulling new code
```

---

## Local development (without Docker)

The app runs cleanly on Python 3.11. WeasyPrint requires native libraries
(Pango, Cairo, GDK-PixBuf). On Ubuntu/Debian:

```bash
sudo apt install -y libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
                    libgdk-pixbuf-2.0-0 shared-mime-info \
                    fonts-liberation
```

On Windows the easiest route is to use Docker; native WeasyPrint on Windows
requires GTK runtime and is not officially supported.

```bash
python -m venv .venv
source .venv/bin/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Apply migrations (or just let main.py create the tables on first run)
alembic upgrade head

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Database migrations

Alembic is configured in `alembic.ini` and `alembic/env.py`. The initial schema
is `alembic/versions/0001_initial_schema.py`.

```bash
# Apply latest migrations
alembic upgrade head

# Generate a new migration after editing models.py
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Inside the running Docker container:

```bash
docker compose exec app alembic upgrade head
```

The application's startup hook also calls `Base.metadata.create_all(...)` as a
fallback, so a fresh container is usable even if migrations have not been run -
but on production deployments you should always run migrations explicitly.

---

## Backup and restore

All persistent state lives in two folders, both mounted into the container:

- `data/app.db` - SQLite database
- `app/static/uploads/` - logo, Nessus CSV uploads, generated PDF reports

### Stop-the-world snapshot

The simplest, safest backup:

```bash
docker compose stop
tar czf msp-security-backup-$(date +%Y%m%d-%H%M%S).tar.gz \
    data app/static/uploads
docker compose start
```

### Hot backup (online SQLite copy)

If you cannot stop the service, use the SQLite `.backup` command which is safe
while the database is in use:

```bash
docker compose exec app sh -c \
  "sqlite3 /app/data/app.db '.backup /app/data/app.db.bak'"
cp data/app.db.bak msp-security-backup-$(date +%Y%m%d-%H%M%S).db
```

(You may need to `apt install sqlite3` inside the container to get the CLI.)

### Restore

```bash
docker compose down
rm -rf data app/static/uploads
tar xzf msp-security-backup-YYYYMMDD-HHMMSS.tar.gz
docker compose up -d
```

---

## How the assessment works

### Question catalogue

`app/services/questions.py` defines eight sections covering Identity & Access
Management, Endpoint Security, Network Security, Data Protection & Backup,
Vulnerability & Patch Management, Security Awareness & Training, Incident
Response & Business Continuity, and Compliance & Governance.

Each question has:

- a stable `key` (used as the database identifier),
- a `weight` reflecting criticality (1, 2, or 3),
- a list of options where each option carries a `score` factor of 0.0, 0.5,
  or 1.0,
- an optional remediation string used to auto-generate the report's
  Recommendations section.

### Scoring

`app/services/scoring.py` walks the catalogue and the saved `AssessmentAnswer`
rows, multiplies the option `score` by the question `weight` to produce earned
points, and computes:

- `raw_score` - sum of earned points,
- `max_score` - sum of question weights,
- `base_percentage`,
- `nessus_deduction` (see below),
- `adjusted_score` and `percentage`,
- `risk_rating` mapped via thresholds.

| Score band     | Rating              |
| -------------- | ------------------- |
| 85% - 100%     | Low Risk            |
| 70% - 84%      | Medium Risk         |
| 50% - 69%      | High Risk           |
| Below 50%      | Critical Risk       |

### Nessus CSV ingestion

When a Nessus CSV export is uploaded, `nessus_parser.py` validates the column
headers, reads the file with pandas, and builds a JSON summary stored on the
`Assessment` record:

- severity counts (Critical / High / Medium / Low / Informational)
- top 10 findings sorted by CVSS
- priority findings (CVSS >= 9.0)
- a deduction value used to adjust the posture score

Each Critical finding deducts 1.5 points (cap 15.0); each High deducts 0.5
(cap 10.0). Medium / Low / Informational findings are reported in full but do
not impact the score.

### Recommendations

For every question that scored less than full marks the engine emits a
recommendation, prioritised as Critical, High, or Medium based on weight and
answer. The PDF groups them in priority order.

### Report generation

`report_generator.py` renders `templates/report/report_template.html` to a PDF
using WeasyPrint. The template is fully WeasyPrint-friendly: it uses tables for
layout, no flexbox or grid, no external fonts, and no JavaScript. The MSP
primary brand colour drives the cover-page band, table headers, and progress
bars.

---

## Configuration

The application reads three optional environment variables:

| Variable        | Default                                              | Purpose |
| --------------- | ---------------------------------------------------- | ------- |
| `DATABASE_URL`  | `sqlite:///<project>/data/app.db`                    | SQLAlchemy URL |
| `UPLOAD_DIR`    | `<project>/app/static/uploads`                       | Where logos and Nessus CSVs are stored |
| `REPORT_DIR`    | `<project>/app/static/uploads/reports`               | Where PDF reports are written |

The Docker compose file sets these to the in-container paths under `/app`. You
do not need to edit them for the standard deployment.

---

## Deployment guide

This section is the recommended path for a production-style deployment of the
application onto an internal Linux host.

### 1. Provision the host

- Linux server (Ubuntu 22.04 LTS or similar).
- Docker Engine 24.x and the `docker compose` plugin.
- A non-root user that is a member of the `docker` group.
- Firewall locked down so port 8000 is only reachable on the management VLAN
  or via VPN/Tailscale.

```bash
# As root or via sudo
apt update && apt install -y docker.io docker-compose-plugin
usermod -aG docker $USER
newgrp docker
```

### 2. Clone the repository

```bash
sudo mkdir -p /opt/msp-security-report
sudo chown $USER:$USER /opt/msp-security-report
git clone https://github.com/<your-org>/msp-security-report.git /opt/msp-security-report
cd /opt/msp-security-report
```

### 3. Build and start

```bash
docker compose up -d --build
docker compose logs -f      # check for "Application startup complete"
```

### 4. First-run configuration

Open `http://<server-ip>:8000/settings` and:

1. Upload your MSP logo (PNG with transparent background recommended).
2. Set the company name and brand colour.
3. Set the contact email and phone that should appear in report footers.
4. Save.

You can now go to **Clients > Add Client** to create the first client and start
an assessment.

### 5. Reverse proxy (optional but recommended)

Front the service with Caddy, nginx, or Traefik so it has TLS and a sensible
hostname. A minimal Caddy snippet:

```
posture.example.internal {
    reverse_proxy 127.0.0.1:8000
}
```

### 6. Updating

```bash
cd /opt/msp-security-report
git pull
docker compose up -d --build
docker compose exec app alembic upgrade head
```

### 7. Backups (suggested cron)

```bash
0 2 * * * cd /opt/msp-security-report && \
    tar czf /var/backups/msp-security-$(date +\%Y\%m\%d).tar.gz \
    data app/static/uploads >/dev/null 2>&1
```

---

## Production notes and caveats

- **No authentication.** This tool does not implement user accounts. It must be
  deployed on a trusted network only.
- **Single-instance.** SQLite is the chosen database deliberately - assessments
  are low-volume, single-user-at-a-time, and the simpler the operational
  footprint the better. Do not run multiple replicas against the same SQLite
  file.
- **PDF rendering CPU.** WeasyPrint is single-threaded; a report may take 2-5
  seconds to render. The default uvicorn worker count is fine.
- **Time zones.** All timestamps are stored in UTC. The PDF cover page formats
  the generation date in `dd Month YYYY`.

---

## Troubleshooting

| Symptom                                              | Likely cause / fix |
| ---------------------------------------------------- | ------------------ |
| `weasyprint` errors mentioning `libpango`            | System libs missing - rebuild the Docker image, or install the apt packages listed above for local dev. |
| Logo does not appear on the PDF cover                | The logo file was deleted or never copied into `app/static/uploads/`. Re-upload from the Settings page. |
| Nessus upload rejected with "missing Risk column"    | The CSV was not exported as the standard Nessus CSV format. Re-export with default columns. |
| Score does not change after re-uploading Nessus CSV  | Refresh the assessment summary page; the score is recomputed on summary view and on report generation. |
| Migration error about an existing column on SQLite   | Use `alembic upgrade head`; SQLite needs Alembic batch mode (already configured in `env.py`). |

---

## License

Internal-use code. Add your preferred license file here before publishing.
