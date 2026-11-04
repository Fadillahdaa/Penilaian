import base64
import gc
import io
import json
import os
import sqlite3
import urllib.request
import pandas as pd
import streamlit as st

# ==================== KONFIGURASI HALAMAN ====================
st.set_page_config(
    page_title="Final Project PBK Digital AI Work Exhibition",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DB_FILE = "penilaian_juri.db"
EXCEL_DB_FILE = "database_penilaian.xlsx"
MAX_PESERTA = 12

ASPEK_PENILAIAN = [
    ("aspek_1", "Kedalaman riset kreativitas dan inovasi"),
    ("aspek_2", "Pemanfaatan Generative AI"),
    ("aspek_3", "Relevansi dengan kebutuhan industri"),
    ("aspek_4", "Kualitas hasil project"),
    ("aspek_5", "Potensi implementasi dan manfaat"),
    ("aspek_6", "Presentasi dan komunikasi"),
    ("aspek_7", "Akurasi dan etika penggunaan AI"),
]

# Avatar Formal Default (Navy & Gold sesuai tema gambar)
DEFAULT_AVATAR_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'>"
    "<circle cx='60' cy='60' r='60' fill='%23dbe4f0'/>"
    "<circle cx='60' cy='44' r='21' fill='%230d2240'/>"
    "<path d='M22 108 C22 79, 98 79, 98 108' fill='%230d2240'/>"
    "</svg>"
)


# ==================== CUSTOM URL ROUTE (/admin/masuk) ====================
def register_admin_url_route():
    """Mendaftarkan route /admin/masuk pada server Tornado Streamlit agar langsung mengarah ke halaman Admin."""
    try:
        import tornado.routing
        import tornado.web

        class AdminMasukHandler(tornado.web.RequestHandler):
            def get(self):
                self.redirect("/?page=admin/masuk")

        for obj in gc.get_objects():
            if isinstance(obj, tornado.web.Application):
                if not getattr(obj, "_admin_masuk_route_added", False):
                    rule = tornado.routing.Rule(
                        tornado.routing.PathMatches(r"/admin/masuk/?"),
                        AdminMasukHandler,
                    )
                    obj.wildcard_router.rules.insert(0, rule)
                    obj.default_router.rules.insert(0, rule)
                    obj._admin_masuk_route_added = True
                break
    except Exception:
        pass


register_admin_url_route()


# ==================== DATABASE SETUP & CLOUD AUTO-RESTORE ====================
def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS instansi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_instansi TEXT UNIQUE NOT NULL
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS peserta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_peserta TEXT UNIQUE NOT NULL,
            asal_instansi TEXT DEFAULT '',
            judul_project TEXT DEFAULT '',
            foto_base64 TEXT DEFAULT ''
        )
        """
    )

    c.execute("PRAGMA table_info(peserta)")
    peserta_cols = [row[1] for row in c.fetchall()]
    if "asal_instansi" not in peserta_cols:
        c.execute("ALTER TABLE peserta ADD COLUMN asal_instansi TEXT DEFAULT ''")
    if "judul_project" not in peserta_cols:
        c.execute("ALTER TABLE peserta ADD COLUMN judul_project TEXT DEFAULT ''")
    if "foto_base64" not in peserta_cols:
        c.execute("ALTER TABLE peserta ADD COLUMN foto_base64 TEXT DEFAULT ''")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS penilaian_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_juri TEXT NOT NULL,
            nama_juri_lower TEXT NOT NULL,
            instansi_juri TEXT NOT NULL,
            peserta_id INTEGER NOT NULL,
            aspek_1 INTEGER NOT NULL,
            aspek_2 INTEGER NOT NULL,
            aspek_3 INTEGER NOT NULL,
            aspek_4 INTEGER NOT NULL,
            aspek_5 INTEGER NOT NULL,
            aspek_6 INTEGER NOT NULL,
            aspek_7 INTEGER NOT NULL,
            nilai_akhir REAL NOT NULL,
            waktu_input TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(nama_juri_lower, peserta_id),
            FOREIGN KEY(peserta_id) REFERENCES peserta(id) ON DELETE CASCADE
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS favorit_vote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_juri TEXT NOT NULL,
            nama_juri_lower TEXT UNIQUE NOT NULL,
            instansi_juri TEXT NOT NULL,
            peserta_id INTEGER NOT NULL,
            waktu_input TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(peserta_id) REFERENCES peserta(id) ON DELETE CASCADE
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS juri_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_juri TEXT NOT NULL,
            nama_juri_lower TEXT UNIQUE NOT NULL,
            instansi_juri TEXT NOT NULL,
            waktu_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute("SELECT value FROM app_config WHERE key = 'clean_initial_state_v2'")
    if c.fetchone() is None:
        c.execute("DELETE FROM penilaian_detail")
        c.execute("DELETE FROM favorit_vote")
        c.execute("DELETE FROM juri_session")
        c.execute("DELETE FROM peserta")
        c.execute("DELETE FROM instansi")
        c.execute("DELETE FROM sqlite_sequence")
        c.execute(
            "INSERT INTO app_config (key, value) VALUES ('clean_initial_state_v2', 'true')"
        )

    conn.commit()
    conn.close()


init_db()


# ==================== FUNGSI HELPER & KONFIGURASI DEPLOY ====================
def encode_uploaded_image(uploaded_file) -> str:
    if uploaded_file is None:
        return ""
    mime_type = uploaded_file.type or "image/jpeg"
    b64_str = base64.b64encode(uploaded_file.getvalue()).decode("utf-8")
    return f"data:{mime_type};base64,{b64_str}"


def get_photo_src(foto_base64: str) -> str:
    if foto_base64 and str(foto_base64).startswith("data:image"):
        return foto_base64
    return DEFAULT_AVATAR_SVG


def get_config(key: str, default: str = "") -> str:
    # Prioritas 1: Database lokal
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM app_config WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    if row and row[0].strip():
        return row[0].strip()

    # Prioritas 2: Streamlit Cloud Secrets / Environment Variable (untuk Deploy Cloud)
    env_key = key.upper()
    if env_key in os.environ and os.environ[env_key].strip():
        return os.environ[env_key].strip()
    try:
        if env_key in st.secrets:
            return str(st.secrets[env_key]).strip()
    except Exception:
        pass

    return default


def set_config(key: str, value: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO app_config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value.strip()),
    )
    conn.commit()
    conn.close()


def get_instansi_df():
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, nama_instansi FROM instansi ORDER BY id ASC", conn)
    conn.close()
    return df


def get_peserta_df():
    conn = get_connection()
    df = pd.read_sql_query(
        """
        SELECT 
            id,
            nama_peserta,
            COALESCE(asal_instansi, '') AS asal_instansi,
            COALESCE(judul_project, '') AS judul_project,
            COALESCE(foto_base64, '') AS foto_base64
        FROM peserta
        ORDER BY id ASC
        """,
        conn,
    )
    conn.close()
    return df


def get_juri_info(nama_juri: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT nama_juri, instansi_juri FROM juri_session WHERE nama_juri_lower = ?",
        (nama_juri.strip().lower(),),
    )
    row = c.fetchone()
    conn.close()
    return row


def save_juri_login(nama_juri: str, instansi_juri: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO juri_session (nama_juri, nama_juri_lower, instansi_juri)
        VALUES (?, ?, ?)
        ON CONFLICT(nama_juri_lower) DO UPDATE SET instansi_juri = excluded.instansi_juri
        """,
        (nama_juri.strip(), nama_juri.strip().lower(), instansi_juri),
    )
    conn.commit()
    conn.close()


def get_juri_scored_map(nama_juri: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT peserta_id, nilai_akhir, aspek_1, aspek_2, aspek_3, aspek_4, aspek_5, aspek_6, aspek_7
        FROM penilaian_detail
        WHERE nama_juri_lower = ?
        """,
        (nama_juri.strip().lower(),),
    )
    rows = c.fetchall()
    conn.close()
    return {
        r[0]: {
            "nilai_akhir": r[1],
            "aspek": [r[2], r[3], r[4], r[5], r[6], r[7], r[8]],
        }
        for r in rows
    }


def get_juri_favorit(nama_juri: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT f.peserta_id, p.nama_peserta
        FROM favorit_vote f
        JOIN peserta p ON f.peserta_id = p.id
        WHERE f.nama_juri_lower = ?
        """,
        (nama_juri.strip().lower(),),
    )
    row = c.fetchone()
    conn.close()
    return row


def get_ranking_final_df():
    conn = get_connection()
    query = """
        SELECT 
            p.id,
            p.nama_peserta AS "Nama Peserta",
            COALESCE(p.asal_instansi, '-') AS "Instansi Peserta",
            COALESCE(p.judul_project, '-') AS "Judul Project",
            COUNT(pd.id) AS "Jumlah Juri Menilai",
            COALESCE(ROUND(AVG(pd.nilai_akhir), 2), 0.0) AS "Nilai Akhir"
        FROM peserta p
        LEFT JOIN penilaian_detail pd ON p.id = pd.peserta_id
        GROUP BY p.id, p.nama_peserta
        ORDER BY "Nilai Akhir" DESC, p.id ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_all_penilaian_detail_df():
    conn = get_connection()
    query = """
        SELECT
            pd.id,
            p.nama_peserta AS "Nama Peserta",
            COALESCE(p.asal_instansi, '-') AS "Instansi Peserta",
            pd.nama_juri AS "Nama Dewan Juri",
            pd.instansi_juri AS "Instansi Juri",
            pd.aspek_1 AS "1. Riset & Inovasi",
            pd.aspek_2 AS "2. Generative AI",
            pd.aspek_3 AS "3. Relevansi Industri",
            pd.aspek_4 AS "4. Kualitas Project",
            pd.aspek_5 AS "5. Potensi Manfaat",
            pd.aspek_6 AS "6. Presentasi",
            pd.aspek_7 AS "7. Akurasi & Etika AI",
            ROUND(pd.nilai_akhir, 2) AS "Rata-rata Nilai",
            pd.waktu_input AS "Waktu Penilaian"
        FROM penilaian_detail pd
        JOIN peserta p ON pd.peserta_id = p.id
        ORDER BY p.id ASC, pd.waktu_input DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_favorit_summary_df():
    conn = get_connection()
    query = """
        SELECT 
            p.id,
            p.nama_peserta AS "Nama Peserta",
            COALESCE(p.asal_instansi, '-') AS "Instansi Peserta",
            COALESCE(p.foto_base64, '') AS "foto_base64",
            COUNT(f.id) AS "Vote"
        FROM peserta p
        LEFT JOIN favorit_vote f ON p.id = f.peserta_id
        GROUP BY p.id, p.nama_peserta
        ORDER BY "Vote" DESC, p.id ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_favorit_votes_log_df():
    conn = get_connection()
    query = """
        SELECT
            f.nama_juri AS "Nama Dewan Juri",
            f.instansi_juri AS "Instansi Juri",
            p.nama_peserta AS "Peserta Favorit Pilihan",
            f.waktu_input AS "Waktu Vote"
        FROM favorit_vote f
        JOIN peserta p ON f.peserta_id = p.id
        ORDER BY f.waktu_input DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_admin_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM peserta")
    total_peserta = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT nama_juri_lower) FROM juri_session")
    jumlah_juri_session = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT nama_juri_lower) FROM penilaian_detail")
    sudah_menilai = c.fetchone()[0]

    jumlah_juri = max(jumlah_juri_session, sudah_menilai)

    c.execute("SELECT COUNT(*) FROM favorit_vote")
    total_vote = c.fetchone()[0]

    conn.close()
    return total_peserta, jumlah_juri, sudah_menilai, total_vote


# ==================== SINKRONISASI SPREADSHEET (EXCEL & GOOGLE SHEETS) ====================
def build_spreadsheet_sheets_dict():
    df_peserta = get_peserta_df().drop(columns=["foto_base64"], errors="ignore")
    df_instansi = get_instansi_df()
    df_penilaian = get_all_penilaian_detail_df().drop(columns=["id"], errors="ignore")
    df_favorit = get_favorit_votes_log_df()
    df_ranking = get_ranking_final_df().copy()
    if not df_ranking.empty:
        df_ranking.insert(0, "Peringkat", range(1, len(df_ranking) + 1))
        df_ranking = df_ranking.drop(columns=["id"], errors="ignore")
    else:
        df_ranking = pd.DataFrame(
            columns=["Peringkat", "Nama Peserta", "Instansi Peserta", "Judul Project", "Jumlah Juri Menilai", "Nilai Akhir"]
        )

    return {
        "Peserta": df_peserta,
        "Instansi": df_instansi,
        "Penilaian_Juri": df_penilaian,
        "Vote_Favorit": df_favorit,
        "Ranking_Final": df_ranking,
    }


def sync_to_spreadsheet() -> tuple[bool, str]:
    sheets_dict = build_spreadsheet_sheets_dict()
    messages = []

    try:
        with pd.ExcelWriter(EXCEL_DB_FILE, engine="openpyxl") as writer:
            for sheet_name, df in sheets_dict.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        messages.append(f"Tersimpan di {EXCEL_DB_FILE}")
    except Exception as e:
        messages.append(f"Catatan Excel lokal: {e}")

    gsheet_url = get_config("gsheet_webapp_url", "").strip()
    if gsheet_url:
        try:
            payload_sheets = {
                name: df.fillna("").to_dict(orient="records")
                for name, df in sheets_dict.items()
            }
            body = json.dumps({"sheets": payload_sheets}).encode("utf-8")
            req = urllib.request.Request(
                gsheet_url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if resp_data.get("status") == "ok":
                    messages.append("Tersinkronisasi ke Google Spreadsheet")
                else:
                    return False, f"Google Sheet merespons: {resp_data.get('message')}"
        except Exception as e:
            return False, f"Gagal mengirim ke Google Spreadsheet: {e}"

    return True, " | ".join(messages)


def restore_from_google_sheet() -> tuple[bool, str]:
    """Menarik kembali data Peserta, Instansi, Nilai Juri, dan Favorit dari Google Spreadsheet (berguna saat Deploy Cloud)."""
    gsheet_url = get_config("gsheet_webapp_url", "").strip()
    if not gsheet_url:
        return False, "URL Web App Google Spreadsheet belum dikonfigurasi."

    try:
        req = urllib.request.Request(gsheet_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))

        if resp_data.get("status") != "ok":
            return False, "Respons Google Spreadsheet tidak valid."

        data = resp_data.get("data", {})
        conn = get_connection()
        c = conn.cursor()

        for r in data.get("Instansi", []):
            nama_i = str(r.get("nama_instansi", "")).strip()
            if nama_i:
                c.execute("INSERT OR IGNORE INTO instansi (nama_instansi) VALUES (?)", (nama_i,))

        for r in data.get("Peserta", [])[:MAX_PESERTA]:
            nama_p = str(r.get("nama_peserta", "")).strip()
            kampus_p = str(r.get("asal_instansi", "-")).strip()
            judul_p = str(r.get("judul_project", "")).strip()
            if nama_p:
                c.execute(
                    "INSERT OR IGNORE INTO peserta (nama_peserta, asal_instansi, judul_project) VALUES (?, ?, ?)",
                    (nama_p, kampus_p, judul_p),
                )

        conn.commit()

        # Map nama_peserta -> id
        c.execute("SELECT id, nama_peserta FROM peserta")
        p_name_to_id = {row[1].strip().lower(): row[0] for row in c.fetchall()}

        for r in data.get("Penilaian_Juri", []):
            nama_p = str(r.get("Nama Peserta", "")).strip().lower()
            nama_j = str(r.get("Nama Dewan Juri", "")).strip()
            inst_j = str(r.get("Instansi Juri", "-")).strip()
            if nama_p in p_name_to_id and nama_j:
                pid = p_name_to_id[nama_p]
                a1 = int(float(r.get("1. Riset & Inovasi", 0) or 0))
                a2 = int(float(r.get("2. Generative AI", 0) or 0))
                a3 = int(float(r.get("3. Relevansi Industri", 0) or 0))
                a4 = int(float(r.get("4. Kualitas Project", 0) or 0))
                a5 = int(float(r.get("5. Potensi Manfaat", 0) or 0))
                a6 = int(float(r.get("6. Presentasi", 0) or 0))
                a7 = int(float(r.get("7. Akurasi & Etika AI", 0) or 0))
                rata = (a1 + a2 + a3 + a4 + a5 + a6 + a7) / 7.0
                c.execute(
                    """
                    INSERT OR IGNORE INTO penilaian_detail (
                        nama_juri, nama_juri_lower, instansi_juri, peserta_id,
                        aspek_1, aspek_2, aspek_3, aspek_4, aspek_5, aspek_6, aspek_7, nilai_akhir
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nama_j, nama_j.lower(), inst_j, pid, a1, a2, a3, a4, a5, a6, a7, rata),
                )
                c.execute(
                    "INSERT OR IGNORE INTO juri_session (nama_juri, nama_juri_lower, instansi_juri) VALUES (?, ?, ?)",
                    (nama_j, nama_j.lower(), inst_j),
                )

        for r in data.get("Vote_Favorit", []):
            nama_j = str(r.get("Nama Dewan Juri", "")).strip()
            inst_j = str(r.get("Instansi Juri", "-")).strip()
            nama_p = str(r.get("Peserta Favorit Pilihan", "")).strip().lower()
            if nama_j and nama_p in p_name_to_id:
                c.execute(
                    """
                    INSERT OR IGNORE INTO favorit_vote (nama_juri, nama_juri_lower, instansi_juri, peserta_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (nama_j, nama_j.lower(), inst_j, p_name_to_id[nama_p]),
                )

        conn.commit()
        conn.close()
        sync_to_spreadsheet()
        return True, "Seluruh data berhasil dipulihkan dari Google Spreadsheet!"
    except Exception as e:
        return False, f"Gagal memulihkan dari Google Spreadsheet: {e}"


def get_excel_bytes() -> bytes | None:
    try:
        sheets_dict = build_spreadsheet_sheets_dict()
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for sheet_name, df in sheets_dict.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
        return buffer.getvalue()
    except Exception:
        return None


# Jika di-deploy ke Cloud dan database lokal masih kosong sementara URL Google Sheet tersedia, tarik otomatis sekali
if "cloud_restore_checked" not in st.session_state:
    st.session_state.cloud_restore_checked = True
    if get_config("gsheet_webapp_url", ""):
        tp, _, _, _ = get_admin_stats()
        if tp == 0:
            restore_from_google_sheet()

sync_to_spreadsheet()


# ==================== CSS FORMAL SESUAI WARNA GAMBAR MOCKUP ====================
st.markdown(
    """
    <style>
    /* Palet Warna Utama Sesuai Gambar:
       - Navy Utama: #0d2240
       - Navy Sekunder: #16335b
       - Gold / Emas: #d8b467 & #c59b43
       - Cream Banner: #f6ebd4
       - Background Aplikasi: #f4f6f9
       - Kartu: #ffffff
    */
    .stApp {
        background: linear-gradient(180deg, #f2f5f9 0%, #eaeff6 100%);
        color: #0d2240;
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    }

    .block-container {
        max-width: 1020px !important;
        padding-top: 1.2rem !important;
        padding-bottom: 3.5rem !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        margin: 0 auto !important;
    }

    /* Header Utama Navy & Gold (Persis Gambar) */
    .navy-header {
        background: linear-gradient(135deg, #0d2240 0%, #153259 75%, #1d3f6f 100%);
        color: #ffffff;
        padding: 18px 24px;
        border-radius: 18px;
        border-bottom: 4px solid #d8b467;
        box-shadow: 0 8px 22px rgba(13, 34, 64, 0.16);
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 18px;
        position: relative;
        overflow: hidden;
    }
    .navy-header-left {
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .gold-badge {
        width: 46px;
        height: 46px;
        border-radius: 12px;
        background: linear-gradient(135deg, #f4d993 0%, #c59b43 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 23px;
        color: #0d2240;
        font-weight: bold;
        box-shadow: 0 3px 10px rgba(197, 155, 67, 0.4);
        flex-shrink: 0;
    }
    .header-title {
        font-size: 15.5px;
        font-weight: 800;
        letter-spacing: 0.6px;
        line-height: 1.25;
        color: #ffffff;
        margin: 0;
    }
    .header-subtitle {
        font-size: 12.5px;
        color: #f4d993;
        font-weight: 700;
        letter-spacing: 0.4px;
        margin: 2px 0 0 0;
    }

    /* Kartu Sapaan Juri / Admin */
    .greeting-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 16px 20px;
        box-shadow: 0 4px 14px rgba(13, 34, 64, 0.05);
        border: 1px solid #e6ebf2;
        display: flex;
        align-items: center;
        gap: 15px;
        margin-bottom: 16px;
    }
    .avatar-circle {
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: #e3ecf8;
        color: #0d2240;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 22px;
        font-weight: bold;
        flex-shrink: 0;
        border: 2px solid #d8b467;
    }
    .greeting-name {
        font-size: 17.5px;
        font-weight: 800;
        color: #0d2240 !important;
        margin: 0;
    }
    .greeting-inst {
        font-size: 13.5px;
        color: #64748b !important;
        margin: 2px 0 0 0;
    }

    /* Grid 4 Kartu Statistik Sesuai Gambar */
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 14px;
        margin-bottom: 20px;
    }
    .stat-card {
        background: #ffffff;
        border-radius: 16px;
        padding: 16px 18px;
        box-shadow: 0 4px 14px rgba(13, 34, 64, 0.05);
        border: 1px solid #e6ebf2;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .stat-icon-wrap {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        margin-bottom: 8px;
    }
    .icon-blue { background: #e0f2fe; color: #0369a1; }
    .icon-green { background: #dcfce7; color: #15803d; }
    .icon-navy { background: #e2e8f0; color: #0d2240; }
    .icon-gold { background: #fef3c7; color: #d97706; }

    .stat-label {
        font-size: 13px;
        color: #64748b !important;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .stat-value {
        font-size: 25px;
        font-weight: 800;
        color: #0d2240 !important;
        margin: 0;
    }
    .stat-value-sm {
        font-size: 16px;
        font-weight: 800;
        color: #0d2240 !important;
        margin: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Tabel Formal Ranking Final (Sesuai Gambar Pojok Kanan Bawah) */
    .formal-table-wrap {
        background: #ffffff;
        border-radius: 16px;
        border: 1px solid #e6ebf2;
        box-shadow: 0 4px 14px rgba(13, 34, 64, 0.05);
        overflow: hidden;
        margin-bottom: 20px;
    }
    .formal-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
    }
    .formal-table thead tr {
        background: #eef2f7;
        color: #0d2240;
        text-align: left;
    }
    .formal-table th {
        padding: 12px 16px;
        font-weight: 700;
        color: #0d2240;
        border-bottom: 1px solid #dce3ec;
    }
    .formal-table td {
        padding: 12px 16px;
        color: #0d2240;
        border-bottom: 1px solid #f1f5f9;
        font-weight: 500;
    }
    .formal-table tbody tr:last-child td {
        border-bottom: none;
    }
    .formal-table tbody tr:hover {
        background: #f8fafc;
    }

    /* Grid Top 3 Peserta Favorit */
    .fav-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        margin-top: 8px;
        margin-bottom: 18px;
    }
    .fav-medal-badge {
        display: inline-block;
        background: linear-gradient(135deg, #f4d993 0%, #c59b43 100%);
        color: #0d2240;
        font-weight: 800;
        font-size: 11.5px;
        padding: 3px 10px;
        border-radius: 12px;
        margin-bottom: 8px;
    }

    /* Foto Peserta */
    .peserta-photo {
        width: 52px;
        height: 52px;
        border-radius: 50%;
        object-fit: cover;
        border: 2px solid #d8b467;
        flex-shrink: 0;
        background: #e3ecf8;
    }
    .peserta-photo-lg {
        width: 74px;
        height: 74px;
        border-radius: 50%;
        object-fit: cover;
        border: 3px solid #d8b467;
        flex-shrink: 0;
        background: #e3ecf8;
    }

    /* Kartu Daftar Peserta */
    .peserta-row-card {
        background: #ffffff;
        border-radius: 14px;
        padding: 12px 18px;
        border: 1px solid #e6ebf2;
        box-shadow: 0 2px 10px rgba(13, 34, 64, 0.04);
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
    }
    .badge-belum {
        background: #f9efd8;
        color: #9a6700;
        padding: 5px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        white-space: nowrap;
    }
    .badge-sudah {
        background: #dcfce7;
        color: #15803d;
        padding: 5px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
        white-space: nowrap;
    }

    /* Banner Instruksi Krem Hangat (Persis Gambar Kanan Atas) */
    .info-banner-warm {
        background: #f5ead4;
        border: 1px solid #e6d3ad;
        color: #0d2240;
        padding: 14px 18px;
        border-radius: 14px;
        font-size: 14px;
        font-weight: 500;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 12px;
    }

    /* Banner Notifikasi Berhasil Inline (Tanpa Pindah Halaman) */
    .inline-success-banner {
        background: #ecfdf5;
        border: 1.5px solid #22c55e;
        border-radius: 16px;
        padding: 16px 20px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 14px;
        box-shadow: 0 4px 14px rgba(34, 197, 94, 0.12);
    }
    .inline-success-icon {
        width: 44px;
        height: 44px;
        border-radius: 50%;
        background: #22c55e;
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 24px;
        font-weight: bold;
        flex-shrink: 0;
    }

    /* Kartu Identitas / Login dengan Aksen Navy & Gold */
    .center-card {
        background: #ffffff;
        border-radius: 20px;
        padding: 30px 24px;
        box-shadow: 0 10px 28px rgba(13, 34, 64, 0.07);
        border: 1px solid #e6ebf2;
        border-top: 5px solid #0d2240;
        border-bottom: 4px solid #d8b467;
        text-align: center;
        margin-bottom: 18px;
    }
    .big-icon-circle {
        width: 78px;
        height: 78px;
        border-radius: 50%;
        margin: 0 auto 14px auto;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 36px;
    }

    /* Tombol Formal Navy (#0d2240) Sesuai Gambar */
    div.stButton > button {
        min-height: 45px !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
    }
    div.stButton > button[kind="primary"] {
        background: #0d2240 !important;
        color: #ffffff !important;
        border: 1px solid #0d2240 !important;
        font-weight: 700 !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background: #16335b !important;
        border-color: #d8b467 !important;
    }

    /* ==================== MEDIA QUERIES: TABLET (TAB) ==================== */
    @media (max-width: 900px) {
        .block-container {
            max-width: 760px !important;
            padding-left: 1.1rem !important;
            padding-right: 1.1rem !important;
        }
        .stats-grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }

    /* ==================== MEDIA QUERIES: HP (SMARTPHONE) ==================== */
    @media (max-width: 600px) {
        .block-container {
            max-width: 100% !important;
            padding-top: 0.8rem !important;
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
        .navy-header {
            padding: 14px 16px;
            border-radius: 14px;
        }
        .header-title {
            font-size: 13.5px;
        }
        .header-subtitle {
            font-size: 11px;
        }
        .stats-grid {
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
        }
        .stat-card {
            padding: 13px 14px;
        }
        .stat-value {
            font-size: 21px;
        }
        .fav-grid {
            grid-template-columns: 1fr;
            gap: 10px;
        }
        .center-card {
            padding: 22px 16px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_top_header():
    st.markdown(
        """
        <div class="navy-header">
            <div class="navy-header-left">
                <div class="gold-badge">🏆</div>
                <div>
                    <p class="header-title">FINAL PROJECT</p>
                    <p class="header-subtitle">PBK DIGITAL AI WORK EXHIBITION</p>
                </div>
            </div>
            <div style="font-size:20px; color:#f4d993; font-weight:bold;">☰</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_inline_success(judul: str, pesan: str):
    """Menampilkan banner notifikasi sukses langsung di halaman yang sama (tanpa pindah halaman)."""
    st.markdown(
        f"""
        <div class="inline-success-banner">
            <div class="inline-success-icon">✓</div>
            <div>
                <div style="font-weight:800; font-size:16px; color:#065f46;">{judul}</div>
                <div style="font-size:13.5px; color:#047857; margin-top:2px;">{pesan}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_formal_ranking_table(df_rank: pd.DataFrame):
    """Merender tabel Ranking Final dengan gaya formal biru-abu persis seperti pada gambar."""
    rows_html = ""
    for idx, row in df_rank.iterrows():
        peringkat = idx + 1
        nama = row["Nama Peserta"]
        judul = row["Judul Project"] if row["Judul Project"] and row["Judul Project"] != "-" else ""
        tampilan_peserta = f"<b>{nama}</b>" + (f"<div style='font-size:12px; color:#64748b;'>{judul}</div>" if judul else "")
        nilai = f"{float(row['Nilai Akhir']):.2f}"
        rows_html += f"""
        <tr>
            <td style="text-align:center; font-weight:700; width:90px;">{peringkat}</td>
            <td>{tampilan_peserta}</td>
            <td style="text-align:right; font-weight:800;">{nilai}</td>
        </tr>
        """

    st.markdown(
        f"""
        <div class="formal-table-wrap">
            <table class="formal-table">
                <thead>
                    <tr>
                        <th style="text-align:center; width:90px;">Peringkat</th>
                        <th>Nama Peserta</th>
                        <th style="text-align:right;">Nilai Akhir</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ==================== DETEKSI ROUTE (JURI vs ADMIN/MASUK) ====================
query_params = st.query_params
page_param = query_params.get("page", "").strip().strip("/").lower()
is_admin_route = page_param in ("admin/masuk", "admin")


# ==============================================================================
#                              MODE 1: HALAMAN ADMIN
#                URL: http://localhost:8501/admin/masuk
#                atau http://localhost:8501/?page=admin/masuk
# ==============================================================================
if is_admin_route:
    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False
    if "admin_tab" not in st.session_state:
        st.session_state.admin_tab = "Dashboard"

    render_top_header()

    # --- LOGIN ADMIN (/admin/masuk) ---
    if not st.session_state.admin_logged_in:
        st.markdown(
            """
            <div class="center-card">
                <div class="big-icon-circle" style="background:#e3ecf8; color:#0d2240;">🔐</div>
                <h3 style="margin:0 0 6px 0; color:#0d2240; font-weight:800;">Login Administrator</h3>
                <p style="color:#64748b; font-size:14px; margin:0;">
                    Silakan masuk untuk mengelola peserta, foto peserta, instansi, serta memantau hasil penilaian.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("form_login_admin"):
            admin_user = st.text_input("👤 Username Administrator", value="admin")
            admin_pass = st.text_input(
                "🔑 Kata Sandi Administrator",
                type="password",
                value="admin123",
                help="Default: admin / admin123",
            )
            submit_admin = st.form_submit_button("Masuk", type="primary", use_container_width=True)

            if submit_admin:
                if admin_user.strip().lower() == "admin" and admin_pass == "admin123":
                    st.session_state.admin_logged_in = True
                    st.rerun()
                else:
                    st.error("Username atau Kata Sandi Administrator tidak sesuai! (Default: admin / admin123)")

        st.stop()

    # --- HEADER SAPAAN ADMIN (Sesuai Gambar Pojok Kanan Bawah) ---
    st.markdown(
        """
        <div class="greeting-card">
            <div class="avatar-circle">👨‍💼</div>
            <div>
                <p class="greeting-inst">Selamat Datang,</p>
                <p class="greeting-name">Admin</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nav_cols = st.columns(4)
    admin_tabs = [
        ("Dashboard", "🏠 Dashboard"),
        ("Nilai Juri", "📋 Nilai Juri"),
        ("Peserta Favorit", "⭐ Peserta Favorit"),
        ("Pengaturan", "⚙️ Pengaturan"),
    ]
    for idx, (tab_key, tab_label) in enumerate(admin_tabs):
        btn_type = "primary" if st.session_state.admin_tab == tab_key else "secondary"
        if nav_cols[idx].button(tab_label, key=f"adm_nav_{tab_key}", type=btn_type, use_container_width=True):
            st.session_state.admin_tab = tab_key
            st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    total_peserta, jumlah_juri, sudah_menilai, total_vote = get_admin_stats()
    df_ranking = get_ranking_final_df()
    df_fav_summary = get_favorit_summary_df()

    # ---------------- TAB 1: DASHBOARD ADMIN ----------------
    if st.session_state.admin_tab == "Dashboard":
        st.markdown(
            f"""
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-blue">👥</div>
                    <div class="stat-label">Total Peserta</div>
                    <p class="stat-value">{total_peserta}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-navy">👥</div>
                    <div class="stat-label">Jumlah Juri</div>
                    <p class="stat-value">{jumlah_juri}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-green">✓</div>
                    <div class="stat-label">Sudah Menilai</div>
                    <p class="stat-value">{sudah_menilai}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-gold">★</div>
                    <div class="stat-label">Peserta Favorit</div>
                    <p class="stat-value">{total_vote} Vote</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if total_peserta == 0:
            st.info(
                "ℹ️ **Data Peserta & Instansi masih kosong.** Silakan buka tab **⚙️ Pengaturan** untuk menginputkan **Daftar Instansi** dan **Daftar Peserta beserta Foto Peserta**."
            )

        hdr_l, hdr_r = st.columns([3, 1.2])
        hdr_l.markdown("##### 🏆 Ranking Final")
        if hdr_r.button("Lihat Semua →", key="lihat_semua_ranking", use_container_width=True):
            st.session_state.admin_tab = "Nilai Juri"
            st.rerun()

        if df_ranking.empty:
            st.caption("Belum ada data peserta yang diinputkan oleh Administrator.")
        else:
            render_formal_ranking_table(df_ranking.head(5).reset_index(drop=True))

        fav_l, fav_r = st.columns([3, 1.2])
        fav_l.markdown("##### ⭐ Hasil Peserta Favorit")
        if fav_r.button("Lihat Detail →", key="lihat_detail_fav", use_container_width=True):
            st.session_state.admin_tab = "Peserta Favorit"
            st.rerun()

        if df_fav_summary.empty:
            st.caption("Belum ada peserta yang terdaftar.")
        else:
            top3_fav = df_fav_summary.head(3)
            fav_cards_html = '<div class="fav-grid">'
            for i, (_, frow) in enumerate(top3_fav.iterrows()):
                photo_src = get_photo_src(frow["foto_base64"])
                fav_cards_html += f"""
                <div class="stat-card" style="text-align:center; padding:16px 12px; align-items:center;">
                    <span class="fav-medal-badge">🏅 Peringkat {i + 1}</span>
                    <img src="{photo_src}" class="peserta-photo" style="margin:4px auto 8px auto; display:block;" />
                    <div style="font-weight:800; font-size:14.5px; color:#0d2240;">
                        {frow['Nama Peserta']}
                    </div>
                    <div style="font-size:12px; color:#64748b; margin-top:2px;">{frow['Instansi Peserta']}</div>
                    <div style="font-weight:800; font-size:14.5px; color:#0d2240; margin-top:6px;">
                        {frow['Vote']} Vote
                    </div>
                </div>
                """
            fav_cards_html += "</div>"
            st.markdown(fav_cards_html, unsafe_allow_html=True)

    # ---------------- TAB 2: NILAI JURI & LIVE SPREADSHEET VIEWER ----------------
    elif st.session_state.admin_tab == "Nilai Juri":
        st.markdown("#### 🏆 Ranking Final Seluruh Peserta")
        if df_ranking.empty:
            st.info("Belum ada data peserta.")
        else:
            render_formal_ranking_table(df_ranking.reset_index(drop=True))

        st.markdown("#### 📊 Database Google Spreadsheet (Google Drive)")
        gdrive_sheet_link = get_config("gdrive_sheet_link", "")
        if gdrive_sheet_link:
            st.link_button(
                "📂 Buka Spreadsheet Langsung di Google Drive",
                url=gdrive_sheet_link,
                type="primary",
                use_container_width=True,
            )
        else:
            st.info(
                "💡 Anda belum menautkan link Google Spreadsheet dari Google Drive. "
                "Silakan tautkan di menu **⚙️ Pengaturan → ☁️ Database Spreadsheet & Deploy**."
            )

        excel_bytes = get_excel_bytes()
        if excel_bytes:
            st.download_button(
                "⬇️ Unduh Salinan Cadangan Spreadsheet (.xlsx)",
                data=excel_bytes,
                file_name="database_penilaian.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        sheets_dict = build_spreadsheet_sheets_dict()
        sheet_tabs = st.tabs(
            [
                "📄 Sheet 1: Penilaian_Juri",
                "📄 Sheet 2: Ranking_Final",
                "📄 Sheet 3: Peserta",
                "📄 Sheet 4: Instansi",
                "📄 Sheet 5: Vote_Favorit",
            ]
        )

        with sheet_tabs[0]:
            st.dataframe(sheets_dict["Penilaian_Juri"], use_container_width=True, hide_index=True)
        with sheet_tabs[1]:
            st.dataframe(sheets_dict["Ranking_Final"], use_container_width=True, hide_index=True)
        with sheet_tabs[2]:
            st.dataframe(sheets_dict["Peserta"], use_container_width=True, hide_index=True)
        with sheet_tabs[3]:
            st.dataframe(sheets_dict["Instansi"], use_container_width=True, hide_index=True)
        with sheet_tabs[4]:
            st.dataframe(sheets_dict["Vote_Favorit"], use_container_width=True, hide_index=True)

    # ---------------- TAB 3: PESERTA FAVORIT ----------------
    elif st.session_state.admin_tab == "Peserta Favorit":
        st.markdown("#### ⭐ Rekapitulasi Perolehan Suara Peserta Favorit")
        if df_fav_summary.empty:
            st.info("Belum ada data peserta.")
        else:
            fav_rank = df_fav_summary.drop(columns=["id", "foto_base64"], errors="ignore").copy()
            fav_rank.insert(0, "Peringkat", range(1, len(fav_rank) + 1))
            st.dataframe(fav_rank, use_container_width=True, hide_index=True)

        st.markdown("#### 🗳️ Riwayat Pilihan Favorit Dewan Juri")
        df_fav_log = get_favorit_votes_log_df()
        if df_fav_log.empty:
            st.info("Belum ada Dewan Juri yang memberikan suara peserta favorit.")
        else:
            st.dataframe(df_fav_log, use_container_width=True, hide_index=True)

    # ---------------- TAB 4: PENGATURAN (PESERTA + FOTO, INSTANSI, CLOUD DEPLOY) ----------------
    elif st.session_state.admin_tab == "Pengaturan":
        sub_peserta, sub_instansi, sub_sheet = st.tabs(
            [
                f"👥 Input Peserta & Foto ({total_peserta}/{MAX_PESERTA})",
                "🏢 Input Instansi Juri",
                "☁️ Database Spreadsheet & Deploy",
            ]
        )

        with sub_peserta:
            df_peserta = get_peserta_df()
            jml_p = len(df_peserta)
            st.progress(
                min(jml_p / MAX_PESERTA, 1.0),
                text=f"Kuota Peserta Terdaftar: {jml_p} dari {MAX_PESERTA} Peserta",
            )

            if jml_p < MAX_PESERTA:
                st.markdown("##### ➕ Tambah Peserta Baru")
                with st.form("form_admin_add_peserta", clear_on_submit=True):
                    c_in1, c_in2 = st.columns(2)
                    in_nama = c_in1.text_input("Nama Lengkap Peserta *", placeholder="Contoh: Andi Pratama")
                    in_kampus = c_in2.text_input("Asal Instansi / Perguruan Tinggi *", placeholder="Contoh: Politeknik Negeri Madiun")
                    in_judul = st.text_input("Judul Karya / Project AI", placeholder="Contoh: Inovasi Smart Education")
                    in_foto = st.file_uploader(
                        "📷 Unggah Foto Formal Peserta (JPG / PNG / WEBP)",
                        type=["jpg", "jpeg", "png", "webp"],
                    )
                    if st.form_submit_button("💾 Simpan Data Peserta", type="primary", use_container_width=True):
                        if not in_nama.strip():
                            st.error("Nama lengkap peserta wajib diisi!")
                        else:
                            foto_b64 = encode_uploaded_image(in_foto)
                            try:
                                conn = get_connection()
                                c = conn.cursor()
                                c.execute(
                                    """
                                    INSERT INTO peserta (nama_peserta, asal_instansi, judul_project, foto_base64)
                                    VALUES (?, ?, ?, ?)
                                    """,
                                    (
                                        in_nama.strip(),
                                        in_kampus.strip() or "-",
                                        in_judul.strip(),
                                        foto_b64,
                                    ),
                                )
                                conn.commit()
                                conn.close()
                                sync_to_spreadsheet()
                                st.toast(f"✅ Peserta '{in_nama.strip()}' berhasil ditambahkan!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("Nama peserta tersebut sudah terdaftar!")
            else:
                st.success(f"✅ Kuota maksimal {MAX_PESERTA} peserta telah terpenuhi.")

            st.markdown("---")
            st.markdown("##### 📋 Daftar Peserta Terdaftar")
            if df_peserta.empty:
                st.info("Belum ada peserta yang terdaftar. Silakan tambahkan peserta melalui formulir di atas.")
            else:
                for idx, row in df_peserta.iterrows():
                    photo_src = get_photo_src(row["foto_base64"])
                    ket_judul = f"<div style='font-size:12px; color:#153259; font-style:italic;'>Karya: {row['judul_project']}</div>" if row["judul_project"] else ""
                    col_a, col_b = st.columns([4.5, 1])
                    with col_a:
                        st.markdown(
                            f"""
                            <div class="peserta-row-card">
                                <div style="display:flex; align-items:center; gap:14px;">
                                    <img src="{photo_src}" class="peserta-photo" />
                                    <div>
                                        <div style="font-weight:800; font-size:15px; color:#0d2240;">{idx + 1}. {row['nama_peserta']}</div>
                                        <div style="font-size:12.5px; color:#64748b;">{row['asal_instansi']}</div>
                                        {ket_judul}
                                    </div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    with col_b:
                        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                        if st.button("🗑️ Hapus", key=f"del_pes_{row['id']}", use_container_width=True):
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("DELETE FROM peserta WHERE id = ?", (row["id"],))
                            conn.commit()
                            conn.close()
                            sync_to_spreadsheet()
                            st.rerun()

                with st.expander("🖼️ Perbarui / Unggah Ulang Foto Peserta"):
                    peserta_options = dict(zip(df_peserta["nama_peserta"], df_peserta["id"]))
                    target_nama_foto = st.selectbox("Pilih Peserta:", options=list(peserta_options.keys()))
                    new_photo_file = st.file_uploader(
                        "Pilih Foto Baru (JPG / PNG / WEBP):",
                        type=["jpg", "jpeg", "png", "webp"],
                        key="update_photo_uploader",
                    )
                    if st.button("💾 Perbarui Foto Peserta", type="primary"):
                        if new_photo_file is None:
                            st.warning("Silakan pilih file foto terlebih dahulu.")
                        else:
                            new_b64 = encode_uploaded_image(new_photo_file)
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                "UPDATE peserta SET foto_base64 = ? WHERE id = ?",
                                (new_b64, peserta_options[target_nama_foto]),
                            )
                            conn.commit()
                            conn.close()
                            st.toast(f"✅ Foto untuk {target_nama_foto} berhasil diperbarui!")
                            st.rerun()

        with sub_instansi:
            df_inst = get_instansi_df()
            st.markdown("##### ➕ Tambah Nama Instansi (Untuk Dropdown Dewan Juri)")
            with st.form("form_admin_add_instansi", clear_on_submit=True):
                in_inst = st.text_input("Nama Instansi Resmi", placeholder="Contoh: PT Maju Bersama / Politeknik Negeri Madiun")
                if st.form_submit_button("💾 Simpan Nama Instansi", type="primary", use_container_width=True):
                    if not in_inst.strip():
                        st.error("Nama instansi tidak boleh kosong!")
                    else:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute("INSERT INTO instansi (nama_instansi) VALUES (?)", (in_inst.strip(),))
                            conn.commit()
                            conn.close()
                            sync_to_spreadsheet()
                            st.toast(f"✅ Instansi '{in_inst.strip()}' berhasil ditambahkan!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Nama instansi tersebut sudah terdaftar!")

            st.markdown("##### Daftar Instansi Terdaftar")
            if df_inst.empty:
                st.info("Belum ada instansi yang diinputkan.")
            else:
                for idx, row in df_inst.iterrows():
                    col_a, col_b = st.columns([4.5, 1])
                    col_a.markdown(f"**{idx + 1}.** {row['nama_instansi']}")
                    if col_b.button("🗑️ Hapus", key=f"del_inst_{row['id']}", use_container_width=True):
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM instansi WHERE id = ?", (row["id"],))
                        conn.commit()
                        conn.close()
                        sync_to_spreadsheet()
                        st.rerun()

        with sub_sheet:
            st.markdown("##### ☁️ Koneksi Google Spreadsheet (Penyimpanan Permanen Saat Deploy)")
            st.caption(
                "Saat aplikasi di-deploy ke **Streamlit Cloud**, hubungkan URL Web App Google Apps Script di bawah ini "
                "(atau simpan di **Streamlit Secrets** sebagai `GSHEET_WEBAPP_URL = \"https://...\"`) agar seluruh data otomatis tersimpan dan dipulihkan dari Google Spreadsheet."
            )
            current_gsheet_url = get_config("gsheet_webapp_url", "")
            with st.form("form_gsheet_config"):
                new_gsheet_url = st.text_input(
                    "URL Web App Google Apps Script",
                    value=current_gsheet_url,
                    placeholder="https://script.google.com/macros/s/......./exec",
                )
                if st.form_submit_button("💾 Simpan & Sinkronkan ke Google Spreadsheet", type="primary", use_container_width=True):
                    set_config("gsheet_webapp_url", new_gsheet_url)
                    ok, msg = sync_to_spreadsheet()
                    if ok:
                        st.success(f"✅ Berhasil disinkronkan! ({msg})")
                    else:
                        st.warning(f"URL disimpan, namun sinkronisasi gagal: {msg}")

            c_sync1, c_sync2 = st.columns(2)
            if c_sync1.button("🔄 Kirim Data ke Google Sheet", use_container_width=True):
                ok, msg = sync_to_spreadsheet()
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
            if c_sync2.button("📥 Pulihkan Data dari Google Sheet", use_container_width=True):
                ok, msg = restore_from_google_sheet()
                if ok:
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

            st.markdown("---")
            st.markdown("##### 🧹 Reset / Kosongkan Database")
            r_col1, r_col2 = st.columns(2)
            if r_col1.button("🗑️ Kosongkan Nilai & Vote Juri Saja", use_container_width=True):
                conn = get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM penilaian_detail")
                c.execute("DELETE FROM favorit_vote")
                c.execute("DELETE FROM juri_session")
                conn.commit()
                conn.close()
                sync_to_spreadsheet()
                st.toast("✅ Seluruh data nilai juri berhasil dikosongkan!")
                st.rerun()

            if r_col2.button("⚠️ Kosongkan Seluruh Data (Peserta, Instansi & Nilai)", use_container_width=True):
                conn = get_connection()
                c = conn.cursor()
                c.execute("DELETE FROM penilaian_detail")
                c.execute("DELETE FROM favorit_vote")
                c.execute("DELETE FROM juri_session")
                c.execute("DELETE FROM peserta")
                c.execute("DELETE FROM instansi")
                conn.commit()
                conn.close()
                sync_to_spreadsheet()
                st.toast("✅ Seluruh database & spreadsheet berhasil dikosongkan!")
                st.rerun()

        st.markdown("---")
        if st.button("🚪 Keluar dari Panel Administrator", use_container_width=True):
            st.session_state.admin_logged_in = False
            st.rerun()


# ==============================================================================
#                            MODE 2: HALAMAN DEWAN JURI
#                         URL Utama: http://localhost:8501/
# ==============================================================================
else:
    if "juri_logged_in" not in st.session_state:
        st.session_state.juri_logged_in = False
    if "juri_nama" not in st.session_state:
        st.session_state.juri_nama = ""
    if "juri_instansi" not in st.session_state:
        st.session_state.juri_instansi = ""
    if "juri_screen" not in st.session_state:
        st.session_state.juri_screen = "beranda"
    if "selected_peserta_id" not in st.session_state:
        st.session_state.selected_peserta_id = None
    if "last_saved_notif" not in st.session_state:
        st.session_state.last_saved_notif = None

    df_instansi = get_instansi_df()
    df_peserta = get_peserta_df()

    # --------------------------------------------------------------------------
    # LAYAR 1: LENGKAPI IDENTITAS (SESUAI GAMBAR KE-2 ATAS)
    # --------------------------------------------------------------------------
    if not st.session_state.juri_logged_in:
        render_top_header()
        st.markdown(
            """
            <div class="center-card">
                <div class="big-icon-circle" style="background:#dbe4f0; color:#0d2240;">👤✓</div>
                <h2 style="margin:0 0 6px 0; color:#0d2240; font-weight:800;">Lengkapi Identitas</h2>
                <p style="color:#64748b; font-size:14.5px; margin:0;">
                    Silakan isi nama dan instansi Anda untuk melanjutkan
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if df_instansi.empty or df_peserta.empty:
            st.info(
                "ℹ️ **Data Penilaian Belum Dibuka:** Administrator belum menginputkan daftar **Instansi** atau **Peserta**. "
                "Apabila Anda adalah Administrator, silakan masuk melalui URL `/admin/masuk` (atau `?page=admin/masuk`)."
            )
            st.stop()

        with st.form("form_identitas_juri"):
            input_nama_juri = st.text_input(
                "👤 Nama Dewan Juri",
                placeholder="Masukkan Nama Lengkap Dewan Juri...",
            )
            input_instansi_juri = st.selectbox(
                "🏢 Instansi",
                options=df_instansi["nama_instansi"].tolist(),
            )
            tombol_masuk = st.form_submit_button("Masuk", type="primary", use_container_width=True)

            if tombol_masuk:
                nama_clean = input_nama_juri.strip()
                if not nama_clean:
                    st.error("Silakan isi Nama Dewan Juri terlebih dahulu.")
                else:
                    existing_info = get_juri_info(nama_clean)
                    final_instansi = existing_info[1] if existing_info else input_instansi_juri
                    save_juri_login(nama_clean, final_instansi)
                    sync_to_spreadsheet()

                    st.session_state.juri_nama = nama_clean
                    st.session_state.juri_instansi = final_instansi
                    st.session_state.juri_logged_in = True
                    st.session_state.juri_screen = "beranda"
                    st.session_state.last_saved_notif = None
                    st.rerun()

        st.stop()

    # --------------------------------------------------------------------------
    # JURI SUDAH LOGIN -> AMBIL PROGRES PENILAIAN JURI
    # --------------------------------------------------------------------------
    nama_juri_aktif = st.session_state.juri_nama
    instansi_juri_aktif = st.session_state.juri_instansi
    scored_map = get_juri_scored_map(nama_juri_aktif)
    fav_choice = get_juri_favorit(nama_juri_aktif)

    total_peserta = len(df_peserta)
    sudah_dinilai = len(scored_map)
    belum_dinilai = max(total_peserta - sudah_dinilai, 0)
    label_favorit = fav_choice[1] if fav_choice else "Belum Dipilih"

    # --------------------------------------------------------------------------
    # HEADER & NAVIGASI DEWAN JURI
    # --------------------------------------------------------------------------
    render_top_header()

    jnav_cols = st.columns(4)
    juri_nav_items = [
        ("beranda", "🏠 Beranda"),
        ("penilaian", "📋 Penilaian"),
        ("favorit", "⭐ Favorit"),
        ("profil", "👤 Profil"),
    ]
    for idx, (scr_key, scr_label) in enumerate(juri_nav_items):
        b_type = "primary" if st.session_state.juri_screen == scr_key else "secondary"
        if jnav_cols[idx].button(scr_label, key=f"jnav_{scr_key}", type=b_type, use_container_width=True):
            st.session_state.juri_screen = scr_key
            st.session_state.last_saved_notif = None
            st.rerun()

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Tampilkan notifikasi berhasil langsung di halaman aktif (tanpa pindah halaman)
    if st.session_state.last_saved_notif:
        judul_notif, pesan_notif = st.session_state.last_saved_notif
        render_inline_success(judul_notif, pesan_notif)

    # ==========================================================================
    # TAB JURI 1: BERANDA (SESUAI GAMBAR KE-3 ATAS)
    # ==========================================================================
    if st.session_state.juri_screen == "beranda":
        st.markdown(
            f"""
            <div class="greeting-card">
                <div class="avatar-circle">👨‍⚖️</div>
                <div>
                    <p class="greeting-name">Halo, {nama_juri_aktif}</p>
                    <p class="greeting-inst">{instansi_juri_aktif}</p>
                </div>
            </div>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-blue">👥</div>
                    <div class="stat-label">Total Peserta</div>
                    <p class="stat-value">{total_peserta}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-green">✓</div>
                    <div class="stat-label">Sudah Dinilai</div>
                    <p class="stat-value">{sudah_dinilai}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-navy">🕒</div>
                    <div class="stat-label">Belum Dinilai</div>
                    <p class="stat-value">{belum_dinilai}</p>
                </div>
                <div class="stat-card">
                    <div class="stat-icon-wrap icon-gold">★</div>
                    <div class="stat-label">Peserta Favorit</div>
                    <p class="stat-value-sm">{label_favorit}</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("##### Daftar Peserta")
        kata_kunci = st.text_input(
            "Cari peserta",
            placeholder="🔍 Cari peserta...",
            label_visibility="collapsed",
        ).strip().lower()

        df_filtered = df_peserta
        if kata_kunci:
            df_filtered = df_peserta[
                df_peserta["nama_peserta"].str.lower().str.contains(kata_kunci)
                | df_peserta["asal_instansi"].str.lower().str.contains(kata_kunci)
                | df_peserta["judul_project"].str.lower().str.contains(kata_kunci)
            ]

        for _, prow in df_filtered.iterrows():
            pid = int(prow["id"])
            sudah = pid in scored_map
            photo_src = get_photo_src(prow["foto_base64"])
            judul_html = (
                f"<div style='font-size:12px; color:#153259; font-style:italic;'>{prow['judul_project']}</div>"
                if prow["judul_project"]
                else ""
            )
            badge_html = (
                f'<span class="badge-sudah">Sudah Dinilai ({scored_map[pid]["nilai_akhir"]:.2f})</span>'
                if sudah
                else '<span class="badge-belum">Belum Dinilai</span>'
            )

            col_info, col_act = st.columns([4.2, 1.3])
            with col_info:
                st.markdown(
                    f"""
                    <div class="peserta-row-card">
                        <div style="display:flex; align-items:center; gap:14px;">
                            <img src="{photo_src}" class="peserta-photo" />
                            <div>
                                <div style="font-weight:800; font-size:15px; color:#0d2240;">{prow['nama_peserta']}</div>
                                <div style="font-size:12.5px; color:#64748b;">{prow['asal_instansi']}</div>
                                {judul_html}
                            </div>
                        </div>
                        <div>{badge_html}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with col_act:
                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                if not sudah:
                    if st.button("Nilai ›", key=f"btn_nilai_{pid}", type="primary", use_container_width=True):
                        st.session_state.selected_peserta_id = pid
                        st.session_state.last_saved_notif = None
                        st.session_state.juri_screen = "penilaian"
                        st.rerun()
                else:
                    if st.button("✏️ Edit Nilai", key=f"btn_edit_{pid}", type="secondary", use_container_width=True):
                        st.session_state.selected_peserta_id = pid
                        st.session_state.last_saved_notif = None
                        st.session_state.juri_screen = "penilaian"
                        st.rerun()

    # ==========================================================================
    # TAB JURI 2: PENILAIAN PESERTA (SESUAI GAMBAR KANAN ATAS + BISA EDIT NILAI)
    # ==========================================================================
    elif st.session_state.juri_screen == "penilaian":
        st.markdown("#### Penilaian Peserta")

        if df_peserta.empty:
            st.info("Belum ada peserta yang terdaftar.")
            st.stop()

        option_labels = []
        label_to_row = {}
        default_idx = 0

        if st.session_state.selected_peserta_id is None:
            for _, r in df_peserta.iterrows():
                if int(r["id"]) not in scored_map:
                    st.session_state.selected_peserta_id = int(r["id"])
                    break

        for idx, (_, row) in enumerate(df_peserta.iterrows()):
            pid = int(row["id"])
            if pid in scored_map:
                status_str = f"✅ Sudah Dinilai ({scored_map[pid]['nilai_akhir']:.2f}) — Edit Nilai"
            else:
                status_str = "⏳ Belum Dinilai"
            lbl = f"{row['nama_peserta']} ({status_str})"
            option_labels.append(lbl)
            label_to_row[lbl] = row
            if st.session_state.selected_peserta_id == pid:
                default_idx = idx

        selected_label = st.selectbox(
            "Pilih Nama Peserta (Dropdown):",
            options=option_labels,
            index=default_idx,
        )
        p_terpilih = label_to_row[selected_label]
        pid_aktif = int(p_terpilih["id"])
        st.session_state.selected_peserta_id = pid_aktif

        is_edit_mode = pid_aktif in scored_map
        existing_aspek_scores = scored_map[pid_aktif]["aspek"] if is_edit_mode else [85] * 7
        photo_src = get_photo_src(p_terpilih["foto_base64"])
        judul_karya_html = (
            f"<p style='font-size:13px; color:#153259; font-weight:600; margin:4px 0 0 0;'>{p_terpilih['judul_project']}</p>"
            if p_terpilih["judul_project"]
            else ""
        )
        mode_badge = (
            "<span class='badge-sudah'>Mode Edit Nilai</span>"
            if is_edit_mode
            else "<span class='badge-belum'>Belum Dinilai</span>"
        )

        st.markdown(
            f"""
            <div class="greeting-card" style="padding:20px; justify-content:space-between; flex-wrap:wrap;">
                <div style="display:flex; align-items:center; gap:16px;">
                    <img src="{photo_src}" class="peserta-photo-lg" />
                    <div>
                        <p style="font-size:21px; font-weight:800; color:#0d2240; margin:0;">{p_terpilih['nama_peserta']}</p>
                        <p style="font-size:14px; color:#64748b; margin:2px 0 0 0;">{p_terpilih['asal_instansi']}</p>
                        {judul_karya_html}
                    </div>
                </div>
                <div>{mode_badge}</div>
            </div>
            <div class="info-banner-warm">
                <span style="font-size:20px;">📋</span>
                <span>Silakan berikan nilai pada setiap aspek penilaian (<b>0 – 100</b>)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form(f"form_7_aspek_{pid_aktif}"):
            nilai_aspek = []
            for idx, (col_key, label_aspek) in enumerate(ASPEK_PENILAIAN, start=1):
                c_label, c_input = st.columns([3.5, 1.2])
                with c_label:
                    st.markdown(
                        f"<div style='padding-top:8px; font-weight:600; color:#0d2240; font-size:14.5px;'>"
                        f"{idx}.&nbsp;&nbsp;{label_aspek}</div>",
                        unsafe_allow_html=True,
                    )
                with c_input:
                    val = st.number_input(
                        f"Aspek {idx}",
                        min_value=0,
                        max_value=100,
                        value=int(existing_aspek_scores[idx - 1]),
                        step=1,
                        key=f"in_{col_key}_{pid_aktif}",
                        label_visibility="collapsed",
                    )
                    nilai_aspek.append(int(val))

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            btn_text = "☑️ Simpan Perubahan Penilaian" if is_edit_mode else "☑️ Simpan Penilaian"
            simpan_btn = st.form_submit_button(btn_text, type="primary", use_container_width=True)

            if simpan_btn:
                nama_target = p_terpilih["nama_peserta"]
                rata_rata = sum(nilai_aspek) / len(nilai_aspek)
                conn = get_connection()
                c = conn.cursor()
                c.execute(
                    """
                    INSERT INTO penilaian_detail (
                        nama_juri, nama_juri_lower, instansi_juri, peserta_id,
                        aspek_1, aspek_2, aspek_3, aspek_4, aspek_5, aspek_6, aspek_7, nilai_akhir
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(nama_juri_lower, peserta_id) DO UPDATE SET
                        instansi_juri = excluded.instansi_juri,
                        aspek_1 = excluded.aspek_1,
                        aspek_2 = excluded.aspek_2,
                        aspek_3 = excluded.aspek_3,
                        aspek_4 = excluded.aspek_4,
                        aspek_5 = excluded.aspek_5,
                        aspek_6 = excluded.aspek_6,
                        aspek_7 = excluded.aspek_7,
                        nilai_akhir = excluded.nilai_akhir,
                        waktu_input = CURRENT_TIMESTAMP
                    """,
                    (
                        nama_juri_aktif,
                        nama_juri_aktif.lower(),
                        instansi_juri_aktif,
                        pid_aktif,
                        nilai_aspek[0],
                        nilai_aspek[1],
                        nilai_aspek[2],
                        nilai_aspek[3],
                        nilai_aspek[4],
                        nilai_aspek[5],
                        nilai_aspek[6],
                        rata_rata,
                    ),
                )
                conn.commit()
                conn.close()
                sync_to_spreadsheet()

                if is_edit_mode:
                    st.session_state.last_saved_notif = (
                        "Penilaian Berhasil Diperbarui!",
                        f"Perubahan nilai untuk {nama_target} (Rata-rata: {rata_rata:.2f}) telah tersimpan.",
                    )
                    st.toast(f"✅ Nilai {nama_target} berhasil diperbarui!")
                else:
                    st.session_state.selected_peserta_id = None
                    st.session_state.last_saved_notif = (
                        "Penilaian Berhasil!",
                        f"Terima kasih telah memberikan penilaian untuk {nama_target} (Rata-rata: {rata_rata:.2f}).",
                    )
                    st.toast(f"✅ Nilai {nama_target} berhasil disimpan!")
                st.rerun()

    # ==========================================================================
    # TAB JURI 3: PILIH PESERTA FAVORIT
    # ==========================================================================
    elif st.session_state.juri_screen == "favorit":
        st.markdown(
            """
            <div class="center-card" style="padding:24px 20px;">
                <div style="font-size:42px; margin-bottom:6px;">⭐</div>
                <h3 style="color:#0d2240; font-weight:800; margin:0 0 6px 0;">Pilih Peserta Favorit</h3>
                <p style="color:#64748b; font-size:14px; margin:0;">
                    Silakan pilih satu peserta yang menurut Anda paling layak menjadi peserta favorit.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if fav_choice is not None:
            st.markdown(
                f"""
                <div class="center-card" style="padding: 24px 20px;">
                    <div class="big-icon-circle" style="background:#fef3c7; color:#d97706; font-size:38px;">🏆</div>
                    <h3 style="color:#0d2240; font-weight:800; margin-bottom:6px;">Terima Kasih!</h3>
                    <p style="color:#0d2240; font-size:15px; margin-bottom:12px;">
                        Pilihan peserta favorit Anda (<b>{fav_choice[1]}</b>) berhasil disimpan.
                    </p>
                    <div class="info-banner-warm" style="text-align:left; margin-bottom:0;">
                        <span>ℹ️</span>
                        <span>Terima kasih atas partisipasi Anda dalam memberikan penilaian dan dukungan. Anda juga dapat memperbarui pilihan di bawah ini.</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.form("form_pilih_favorit"):
            pilihan_labels = [
                f"{row['nama_peserta']} — {row['asal_instansi']}" for _, row in df_peserta.iterrows()
            ]
            label_to_id = {
                f"{row['nama_peserta']} — {row['asal_instansi']}": int(row["id"])
                for _, row in df_peserta.iterrows()
            }

            default_fav_idx = 0
            if fav_choice is not None:
                for i, (_, r) in enumerate(df_peserta.iterrows()):
                    if int(r["id"]) == int(fav_choice[0]):
                        default_fav_idx = i
                        break

            selected_fav_label = st.radio(
                "Daftar Peserta:",
                options=pilihan_labels,
                index=default_fav_idx,
            )
            btn_fav_label = "Simpan Perubahan Pilihan" if fav_choice else "Simpan Pilihan"
            submit_fav = st.form_submit_button(btn_fav_label, type="primary", use_container_width=True)

            if submit_fav:
                fav_pid = label_to_id[selected_fav_label]
                conn = get_connection()
                c = conn.cursor()
                c.execute(
                    """
                    INSERT INTO favorit_vote (nama_juri, nama_juri_lower, instansi_juri, peserta_id)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(nama_juri_lower) DO UPDATE SET
                        instansi_juri = excluded.instansi_juri,
                        peserta_id = excluded.peserta_id,
                        waktu_input = CURRENT_TIMESTAMP
                    """,
                    (nama_juri_aktif, nama_juri_aktif.lower(), instansi_juri_aktif, fav_pid),
                )
                conn.commit()
                conn.close()
                sync_to_spreadsheet()
                st.session_state.last_saved_notif = (
                    "Terima Kasih!",
                    "Pilihan peserta favorit Anda berhasil disimpan.",
                )
                st.toast("🏆 Pilihan Peserta Favorit berhasil disimpan!")
                st.rerun()

    # ==========================================================================
    # TAB JURI 4: PROFIL DEWAN JURI
    # ==========================================================================
    elif st.session_state.juri_screen == "profil":
        st.markdown(
            f"""
            <div class="center-card">
                <div class="big-icon-circle" style="background:#dbe4f0; color:#0d2240;">👨‍⚖️</div>
                <h3 style="color:#0d2240; margin:0 0 4px 0; font-weight:800;">{nama_juri_aktif}</h3>
                <p style="color:#64748b; margin:0 0 14px 0;">{instansi_juri_aktif}</p>
                <p style="font-size:14px; color:#0d2240; margin:0;">
                    Progres Penilaian: <b>{sudah_dinilai} / {total_peserta} Peserta</b><br>
                    Peserta Favorit: <b>{label_favorit}</b>
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("🚪 Keluar / Ganti Akun Dewan Juri", use_container_width=True):
            st.session_state.juri_logged_in = False
            st.session_state.juri_nama = ""
            st.session_state.juri_instansi = ""
            st.session_state.juri_screen = "beranda"
            st.session_state.last_saved_notif = None
            st.rerun()
