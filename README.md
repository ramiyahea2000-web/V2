# V2
# ⚡ Petra Panel Workshop — Fault Reporter v2

> A production-grade quality-control tracking system for electrical panel assembly,
> built for **Petra Engineering Industries** HVAC division.

---

## What It Does

Technicians on the workshop floor log faulty parts against their **Petra Code** (unique
part identifier). The system automatically raises a **critical alert** when any single
code is reported 3 or more times — signalling a recurring design flaw or a supplier
quality issue that needs engineering review.

---

## Repository Structure

```
petra-panel-workshop/
├── main.py                    ← Application entry point (v2)
├── requirements.txt           ← All Python dependencies
├── petra_logo.png             ← Company logo (add your own)
├── .streamlit/
│   ├── config.toml            ← Theme, server, and logger settings
│   └── secrets.toml           ← 🔒 Local only — DO NOT commit to GitHub
├── uploads/                   ← Fault images (auto-created, git-ignored)
└── workshop.db                ← SQLite database (auto-created, git-ignored)
```

---

## Local Development Setup

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/petra-panel-workshop.git
cd petra-panel-workshop
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
streamlit run main.py
```

The app will open at `http://localhost:8501`.

---

## Streamlit Cloud Deployment

1. Push this repository to GitHub (make sure `workshop.db` and `secrets.toml`
   are in `.gitignore`).
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Select your repository, branch (`main`), and set **Main file path** to `main.py`.
4. Click **Deploy**.

---

## Fixing Data Persistence (Google Sheets Sync)

By default, the SQLite database resets whenever Streamlit Cloud restarts.
To keep your data permanent, enable the built-in **Google Sheets sync**:

### Step 1 — Create a Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **IAM & Admin** → **Service Accounts**.
2. Create a new service account and download the **JSON key file**.
3. Enable the **Google Sheets API** and **Google Drive API** for your project.

### Step 2 — Share your Google Sheet

1. Create a new Google Sheet.
2. Copy its ID from the URL:
   `https://docs.google.com/spreadsheets/d/**<SHEET_ID>**/edit`
3. Share the sheet with the service account email (e.g. `petra-bot@your-project.iam.gserviceaccount.com`) — give it **Editor** access.

### Step 3 — Add secrets to Streamlit Cloud

In the Streamlit Cloud dashboard → **App settings** → **Secrets**, paste:

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-gcp-project-id"
private_key_id = "key-id-from-json"
private_key = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
client_email = "petra-bot@your-project.iam.gserviceaccount.com"
token_uri = "https://oauth2.googleapis.com/token"

[gsheets]
spreadsheet_key = "your-google-sheet-id"
```

For **local development**, create `.streamlit/secrets.toml` with the same content.
This file is already git-ignored — never commit it.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | Streamlit 1.35 |
| Language | Python 3.11 |
| Database (local) | SQLite 3 (WAL mode) |
| Database (cloud) | Google Sheets (sync) / Supabase PostgreSQL (optional) |
| Data processing | Pandas 2.2 |
| Image handling | Pillow 10 |
| Excel export | OpenPyXL 3.1 |
| Cloud hosting | Streamlit Community Cloud |

---

## Environment Variables & Secrets Reference

| Key | Purpose | Required |
|---|---|---|
| `gcp_service_account.*` | Google Sheets auth | Only for cloud sync |
| `gsheets.spreadsheet_key` | Target Sheet ID | Only for cloud sync |

---

## Alarm Threshold

The critical alert fires when a **Petra Code** accumulates **≥ 3 reports**.
To change this, edit line 20 of `main.py`:

```python
ALARM_THRESHOLD = 3   # ← change this value
```

---

## Roadmap

- [ ] Automated PDF Non-Conformance Reports (NCR) with `reportlab`
- [ ] Supplier Scorecard & Pareto Analysis tab
- [ ] EPLAN `.elk` XML cross-reference lookup
- [ ] Supabase PostgreSQL migration for full multi-user concurrency
- [ ] Email alerts when a Petra Code crosses the alarm threshold

---

## Author

**Eng. Rami** — Electrical Design Engineer, Petra Engineering Industries

