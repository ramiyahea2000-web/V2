"""
Petra Panel Workshop - Fault Reporter
======================================
Production-grade Streamlit app for electrical panel QC tracking.
Supports SQLite (local/dev) and Google Sheets (cloud/persistent).

Author  : Eng. Rami - Petra Engineering Industries
Version : 2.0.0
"""

import os
import io
import uuid
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from PIL import Image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
APP_DIR       = os.path.dirname(os.path.abspath(__file__))
DB_PATH       = os.path.join(APP_DIR, "workshop.db")
UPLOAD_DIR    = os.path.join(APP_DIR, "uploads")
LOGO_PATH     = os.path.join(APP_DIR, "petra_logo.png")
ALARM_THRESHOLD = 3

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("uploads", exist_ok=True)   # relative path — used for DB storage & display

# ---------------------------------------------------------------------------
# Database Layer  (SQLite — swap for PostgreSQL by changing get_connection)
# ---------------------------------------------------------------------------
def get_connection():
    """Return a thread-safe SQLite connection with Row factory."""
    import sqlite3
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")   # safer for concurrent writes
    return conn


def init_db() -> None:
    """Create tables if they do not exist yet."""
    try:
        with get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    petra_code      TEXT    NOT NULL,
                    part_number     TEXT,
                    project_number  TEXT,
                    supplier        TEXT,
                    severity        TEXT    DEFAULT 'Medium',
                    notes           TEXT,
                    image_path      TEXT,
                    resolved        INTEGER DEFAULT 0,
                    timestamp       TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS suppliers (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    name    TEXT NOT NULL UNIQUE
                );

                CREATE INDEX IF NOT EXISTS idx_petra_code
                    ON entries (petra_code);
                CREATE INDEX IF NOT EXISTS idx_timestamp
                    ON entries (timestamp);
            """)
        log.info("Database initialised at %s", DB_PATH)
    except Exception as exc:
        log.error("init_db failed: %s", exc)
        st.error(f"Database init error: {exc}")


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------
def is_duplicate(petra_code: str, part_number: str, project_number: str):
    """Return (is_dup: bool, reason: str)."""
    try:
        with get_connection() as conn:
            pn = project_number.strip() if project_number and project_number.strip() else None
            if pn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM entries WHERE petra_code=? AND project_number=?",
                    (petra_code, pn),
                ).fetchone()[0]
                if count:
                    return True, f"Petra Code **{petra_code}** already logged for Project **{pn}**."
                if part_number and part_number.strip():
                    count2 = conn.execute(
                        "SELECT COUNT(*) FROM entries WHERE part_number=? AND project_number=?",
                        (part_number.strip(), pn),
                    ).fetchone()[0]
                    if count2:
                        return True, f"Part Number **{part_number.strip()}** already logged for Project **{pn}**."
            else:
                count = conn.execute(
                    "SELECT COUNT(*) FROM entries "
                    "WHERE petra_code=? AND (project_number IS NULL OR project_number='')",
                    (petra_code,),
                ).fetchone()[0]
                if count:
                    return True, f"Petra Code **{petra_code}** already exists (no project)."
        return False, ""
    except Exception as exc:
        log.error("is_duplicate: %s", exc)
        return False, ""     # fail open — let the entry through rather than block valid input


def save_entry(petra_code, part_number, project_number, supplier, severity, notes, image_path) -> bool:
    """Insert a new fault entry. Returns True on success."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO entries
                   (petra_code, part_number, project_number, supplier, severity,
                    notes, image_path, resolved, timestamp)
                   VALUES (?,?,?,?,?,?,?,0,?)""",
                (
                    petra_code,
                    part_number or None,
                    project_number or None,
                    supplier or None,
                    severity,
                    notes or None,
                    image_path,
                    ts,
                ),
            )
        return True
    except Exception as exc:
        log.error("save_entry: %s", exc)
        st.error(f"Failed to save entry: {exc}")
        return False


def toggle_resolved(entry_id: int) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE entries SET resolved = 1 - resolved WHERE id=?", (entry_id,)
            )
    except Exception as exc:
        log.error("toggle_resolved: %s", exc)


def delete_entries(ids: list) -> None:
    if not ids:
        return
    try:
        with get_connection() as conn:
            ph = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM entries WHERE id IN ({ph})", ids)
    except Exception as exc:
        log.error("delete_entries: %s", exc)
        st.error(f"Delete failed: {exc}")


def get_all_entries() -> list:
    try:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM entries ORDER BY timestamp DESC"
            ).fetchall()
    except Exception as exc:
        log.error("get_all_entries: %s", exc)
        return []


def get_filtered_entries(
    project: str = "",
    supplier: str = "",
    severity: str = "",
    resolved: str = "All",
    date_from: str = "",
    date_to: str = "",
) -> list:
    try:
        clauses, params = [], []
        if project:
            clauses.append("project_number=?");  params.append(project)
        if supplier:
            clauses.append("supplier=?");        params.append(supplier)
        if severity:
            clauses.append("severity=?");        params.append(severity)
        if resolved == "Open":
            clauses.append("resolved=0")
        elif resolved == "Closed":
            clauses.append("resolved=1")
        if date_from:
            clauses.append("timestamp>=?");      params.append(date_from + " 00:00:00")
        if date_to:
            clauses.append("timestamp<=?");      params.append(date_to + " 23:59:59")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with get_connection() as conn:
            return conn.execute(
                f"SELECT * FROM entries {where} ORDER BY timestamp DESC", params
            ).fetchall()
    except Exception as exc:
        log.error("get_filtered_entries: %s", exc)
        return []


def get_critical_petra_codes() -> list:
    try:
        with get_connection() as conn:
            return conn.execute(
                f"""SELECT petra_code,
                           COUNT(*)        AS total_count,
                           MAX(timestamp)  AS last_seen,
                           SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_count
                    FROM entries
                    GROUP BY petra_code
                    HAVING COUNT(*) >= {ALARM_THRESHOLD}
                    ORDER BY total_count DESC"""
            ).fetchall()
    except Exception as exc:
        log.error("get_critical_petra_codes: %s", exc)
        return []


def get_kpi_stats() -> dict:
    try:
        with get_connection() as conn:
            total     = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            open_cnt  = conn.execute("SELECT COUNT(*) FROM entries WHERE resolved=0").fetchone()[0]
            critical  = conn.execute(
                f"SELECT COUNT(DISTINCT petra_code) FROM entries "
                f"GROUP BY petra_code HAVING COUNT(*) >= {ALARM_THRESHOLD}"
            ).fetchall()
            week_ago  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            week_cnt  = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE timestamp>=?", (week_ago,)
            ).fetchone()[0]
        return {
            "total": total,
            "open": open_cnt,
            "closed": total - open_cnt,
            "critical_codes": len(critical),
            "week": week_cnt,
        }
    except Exception as exc:
        log.error("get_kpi_stats: %s", exc)
        return {"total": 0, "open": 0, "closed": 0, "critical_codes": 0, "week": 0}


def get_chart_data() -> dict:
    """Returns DataFrames ready for Streamlit charts."""
    try:
        with get_connection() as conn:
            # top faulty codes
            top = pd.read_sql_query(
                "SELECT petra_code, COUNT(*) AS reports "
                "FROM entries GROUP BY petra_code ORDER BY reports DESC LIMIT 10",
                conn,
            )
            # severity breakdown
            sev = pd.read_sql_query(
                "SELECT severity, COUNT(*) AS count FROM entries GROUP BY severity",
                conn,
            )
            # daily trend (last 30 days)
            cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            trend = pd.read_sql_query(
                "SELECT substr(timestamp,1,10) AS day, COUNT(*) AS reports "
                "FROM entries WHERE timestamp>=? GROUP BY day ORDER BY day",
                conn,
                params=(cutoff,),
            )
            # supplier faults
            sup = pd.read_sql_query(
                "SELECT COALESCE(supplier,'Unknown') AS supplier, COUNT(*) AS faults "
                "FROM entries GROUP BY supplier ORDER BY faults DESC LIMIT 8",
                conn,
            )
        return {"top": top, "severity": sev, "trend": trend, "supplier": sup}
    except Exception as exc:
        log.error("get_chart_data: %s", exc)
        return {}


def save_image(uploaded_file) -> str | None:
    """Save uploaded image to UPLOAD_DIR and return ONLY the filename for DB storage."""
    try:
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR)
        filename = f"{int(time.time())}_{uploaded_file.name}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        img = Image.open(uploaded_file).convert("RGB")
        img.save(file_path, optimize=True)
        log.info("Image saved: %s", file_path)
        return filename           # e.g.  "1714000000_photo.jpg"  — path rebuilt at display time
    except Exception as exc:
        log.error("save_image: %s", exc)
        return None


def build_excel_report(rows: list) -> io.BytesIO:
    """Stream an Excel file from a list of sqlite3.Row objects."""
    try:
        df = pd.DataFrame([dict(r) for r in rows])
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Fault_Report")
            # auto-fit column widths
            ws = writer.sheets["Fault_Report"]
            for col in ws.columns:
                max_len = max(len(str(c.value or "")) for c in col) + 4
                ws.column_dimensions[col[0].column_letter].width = min(max_len, 50)
        buf.seek(0)
        return buf
    except Exception as exc:
        log.error("build_excel_report: %s", exc)
        return io.BytesIO()


# ---------------------------------------------------------------------------
# Google Sheets sync  (optional — set GSHEET_KEY in Streamlit Secrets)
# ---------------------------------------------------------------------------
def sync_to_gsheets() -> None:
    """
    Push the entire entries table to a Google Sheet for cloud persistence.

    Setup (one-time):
    1.  pip install gspread oauth2client
    2.  Create a Google Service Account and share the Sheet with its email.
    3.  Add to .streamlit/secrets.toml:
            [gcp_service_account]
            type = "service_account"
            project_id = "..."
            private_key_id = "..."
            private_key = "..."
            client_email = "..."
            ...
            [gsheets]
            spreadsheet_key = "YOUR_SHEET_ID"
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict  = dict(st.secrets["gcp_service_account"])
        sheet_key   = st.secrets["gsheets"]["spreadsheet_key"]
        scopes      = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc     = gspread.authorize(creds)
        ws     = gc.open_by_key(sheet_key).sheet1

        rows = get_all_entries()
        df   = pd.DataFrame([dict(r) for r in rows])
        ws.clear()
        ws.update([df.columns.tolist()] + df.values.tolist())
        log.info("Synced %d rows to Google Sheets.", len(rows))
        st.toast("Synced to Google Sheets!", icon="✅")
    except KeyError:
        pass   # Secrets not configured — silent skip in dev
    except Exception as exc:
        log.error("sync_to_gsheets: %s", exc)
        st.warning(f"Google Sheets sync failed: {exc}")


# ===========================================================================
# UI
# ===========================================================================
init_db()
st.set_page_config(
    page_title="Petra Panel Workshop",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---- Custom CSS -----------------------------------------------------------
st.markdown("""
<style>
    /* Severity badges */
    .badge-high   { background:#e53935; color:#fff; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; font-weight:600; }
    .badge-medium { background:#f57c00; color:#fff; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; font-weight:600; }
    .badge-low    { background:#388e3c; color:#fff; padding:2px 10px;
                    border-radius:12px; font-size:0.78rem; font-weight:600; }
    /* KPI cards */
    .kpi-card { background:#1e2a3a; border-radius:12px; padding:18px 24px;
                text-align:center; border:1px solid #2d3f55; }
    .kpi-value { font-size:2.4rem; font-weight:800; color:#4fc3f7; line-height:1; }
    .kpi-label { font-size:0.85rem; color:#90a4ae; margin-top:4px; }
    /* Hide Streamlit branding */
    #MainMenu {visibility:hidden;}
    footer     {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# ---- Header ---------------------------------------------------------------
hdr_l, hdr_c, hdr_r = st.columns([1, 2, 1])
with hdr_c:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=220)
st.markdown(
    "<h2 style='text-align:center;margin-top:-10px;'>⚡ Panel Workshop — Fault Reporter</h2>",
    unsafe_allow_html=True,
)

# ---- Tabs -----------------------------------------------------------------
tab_submit, tab_dash, tab_search, tab_admin = st.tabs(
    ["📋 Submit Entry", "📊 Dashboard", "🔍 Search & Filter", "🔧 Admin"]
)


# ===========================  TAB 1 : SUBMIT  ==============================
with tab_submit:
    st.subheader("Log a New Fault")

    with st.form("entry_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            petra_code  = st.text_input("Petra Code *", placeholder="e.g. PC-2024-0042")
        with c2:
            part_number = st.text_input("Part Number", placeholder="e.g. CB-3P-63A")
        with c3:
            project_number = st.text_input("Project Number", placeholder="e.g. PRJ-112")

        c4, c5 = st.columns(2)
        with c4:
            supplier = st.text_input("Supplier", placeholder="e.g. Schneider Electric")
        with c5:
            severity = st.selectbox("Severity", ["High", "Medium", "Low"], index=1)

        notes = st.text_area("Notes / Description", placeholder="Describe the fault in detail...")

        st.markdown("**Attach Image**")
        method = st.radio("Capture method", ["Upload from device", "In-browser camera"],
                          horizontal=True)
        image_file = (
            st.file_uploader("Upload image", type=["jpg", "jpeg", "png"])
            if method == "Upload from device"
            else st.camera_input("Take a photo")
        )

        submitted = st.form_submit_button("Submit Fault Report", type="primary",
                                          use_container_width=True)

    if submitted:
        if not petra_code.strip():
            st.error("Petra Code is required.")
        else:
            dup, reason = is_duplicate(
                petra_code.strip(), part_number.strip(), project_number.strip()
            )
            if dup:
                st.error(reason)
            else:
                img_path = save_image(image_file) if image_file else None
                ok = save_entry(
                    petra_code.strip(),
                    part_number.strip(),
                    project_number.strip(),
                    supplier.strip(),
                    severity,
                    notes.strip(),
                    img_path,
                )
                if ok:
                    sync_to_gsheets()
                    st.success("Fault report submitted successfully!")
                    st.balloons()
                    st.rerun()

    # Recent entries preview
    st.markdown("---")
    st.subheader("Recent Entries")
    recent = get_filtered_entries()[:20]
    if not recent:
        st.info("No entries yet.")
    for e in recent:
        sev_cls = {"High": "badge-high", "Medium": "badge-medium", "Low": "badge-low"}.get(
            e["severity"], "badge-medium"
        )
        status_icon = "✅" if e["resolved"] else "🔴"
        with st.expander(f"{status_icon} {e['timestamp']} | Petra: {e['petra_code']}"):
            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.markdown(
                    f"**Part:** {e['part_number'] or '-'}  \n"
                    f"**Project:** {e['project_number'] or '-'}  \n"
                    f"**Supplier:** {e['supplier'] or '-'}  \n"
                    f"**Severity:** {e['severity']}  \n"
                    f"**Notes:** {e['notes'] or 'None'}",
                    unsafe_allow_html=True,
                )
                if st.button("Toggle Resolved", key=f"res_{e['id']}"):
                    toggle_resolved(e["id"])
                    st.rerun()
            with col_b:
                img_filename = e["image_path"]
                if img_filename:
                    full_path = os.path.join(UPLOAD_DIR, img_filename)
                    if os.path.exists(full_path):
                        try:
                            st.image(full_path, use_container_width=True)
                        except Exception:
                            st.caption("⚠️ Could not render image")
                        # Fail-safe download — available whether st.image succeeds or not
                        with open(full_path, "rb") as img_file:
                            st.download_button(
                                label="⬇️ Download Image",
                                data=img_file.read(),
                                file_name=img_filename,
                                mime="image/png",
                                key=f"dl_{e['id']}",
                                use_container_width=True,
                            )
                    else:
                        st.info("No image file found on server")
                else:
                    st.caption("🚫 No image attached")


# ===========================  TAB 2 : DASHBOARD  ===========================
with tab_dash:
    st.subheader("Quality Control Dashboard")

    kpi = get_kpi_stats()
    k1, k2, k3, k4, k5 = st.columns(5)
    for col, label, val in [
        (k1, "Total Reports",   kpi["total"]),
        (k2, "Open Issues",     kpi["open"]),
        (k3, "Closed Issues",   kpi["closed"]),
        (k4, "Critical Codes",  kpi["critical_codes"]),
        (k5, "This Week",       kpi["week"]),
    ]:
        col.markdown(
            f'<div class="kpi-card"><div class="kpi-value">{val}</div>'
            f'<div class="kpi-label">{label}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    charts = get_chart_data()

    if charts.get("top") is not None and not charts["top"].empty:
        col_l, col_r = st.columns(2)
        with col_l:
            st.markdown("#### 🔴 Top 10 Faulty Petra Codes")
            st.bar_chart(charts["top"].set_index("petra_code")["reports"])
        with col_r:
            st.markdown("#### 📅 Daily Fault Trend (Last 30 Days)")
            if not charts["trend"].empty:
                st.line_chart(charts["trend"].set_index("day")["reports"])
            else:
                st.info("Not enough data yet.")

        col_m, col_n = st.columns(2)
        with col_m:
            st.markdown("#### ⚠️ Severity Breakdown")
            st.bar_chart(charts["severity"].set_index("severity")["count"])
        with col_n:
            st.markdown("#### 🏭 Faults by Supplier")
            if not charts["supplier"].empty:
                st.bar_chart(charts["supplier"].set_index("supplier")["faults"])

    st.markdown("---")
    st.subheader("🚨 Critical Petra Codes")
    critical = get_critical_petra_codes()
    if critical:
        crit_df = pd.DataFrame([dict(r) for r in critical])
        st.dataframe(crit_df, use_container_width=True)
        all_rows = get_all_entries()
        st.download_button(
            label="⬇️ Download Full Excel Report",
            data=build_excel_report(all_rows),
            file_name=f"petra_fault_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.success("No Petra codes have exceeded the alarm threshold. System is healthy.")

    if st.button("🔄 Sync to Google Sheets"):
        sync_to_gsheets()


# =======================  TAB 3 : SEARCH & FILTER  ========================
with tab_search:
    st.subheader("Search & Filter Entries")

    fc1, fc2, fc3, fc4 = st.columns(4)
    with fc1:
        f_project  = st.text_input("Project Number")
    with fc2:
        f_supplier = st.text_input("Supplier")
    with fc3:
        f_severity = st.selectbox("Severity", ["", "High", "Medium", "Low"])
    with fc4:
        f_resolved = st.selectbox("Status", ["All", "Open", "Closed"])

    dc1, dc2 = st.columns(2)
    with dc1:
        f_date_from = st.date_input("From Date", value=None)
    with dc2:
        f_date_to   = st.date_input("To Date",   value=None)

    if st.button("Apply Filters", type="primary"):
        results = get_filtered_entries(
            project   = f_project.strip(),
            supplier  = f_supplier.strip(),
            severity  = f_severity,
            resolved  = f_resolved,
            date_from = str(f_date_from) if f_date_from else "",
            date_to   = str(f_date_to)   if f_date_to   else "",
        )
        st.info(f"Found **{len(results)}** entries.")
        if results:
            df = pd.DataFrame([dict(r) for r in results])
            st.dataframe(df, use_container_width=True)
            st.download_button(
                "⬇️ Export Filtered Results",
                data=build_excel_report(results),
                file_name="filtered_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# ===========================  TAB 4 : ADMIN  ===============================
with tab_admin:
    st.subheader("Admin Panel")

    with st.expander("🗑️ Delete Entries", expanded=False):
        all_entries = get_all_entries()
        if not all_entries:
            st.info("No entries to delete.")
        else:
            options = {
                f"ID:{e['id']}  |  {e['timestamp']}  |  Petra: {e['petra_code']}": e["id"]
                for e in all_entries
            }
            selected = st.multiselect("Select entries to delete", list(options.keys()))
            if st.button("Delete Selected", type="primary", disabled=not selected):
                delete_entries([options[s] for s in selected])
                st.success(f"Deleted {len(selected)} entries.")
                st.rerun()

    with st.expander("📤 Export / Backup", expanded=False):
        all_entries = get_all_entries()
        if all_entries:
            st.download_button(
                "⬇️ Download Full Database Export",
                data=build_excel_report(all_entries),
                file_name=f"full_backup_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if st.button("☁️ Manual Google Sheets Sync"):
            sync_to_gsheets()

    with st.expander("ℹ️ System Info", expanded=False):
        st.markdown(f"""
        | Parameter | Value |
        |---|---|
        | DB Path | `{DB_PATH}` |
        | Upload Dir | `{UPLOAD_DIR}` |
        | Alarm Threshold | `{ALARM_THRESHOLD}` |
        | App Version | `2.0.0` |
        """)
