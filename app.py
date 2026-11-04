import sqlite3
import pandas as pd
import streamlit as st

# Konfigurasi Halaman
st.set_page_config(
    page_title="Aplikasi Penilaian Juri",
    page_icon="🏆",
    layout="wide",
)

DB_FILE = "penilaian_juri.db"
MAX_PESERTA = 12


# ==================== DATABASE SETUP ====================
def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Tabel Instansi
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS instansi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_instansi TEXT UNIQUE NOT NULL
        )
        """
    )

    # Tabel Peserta (Maksimal 12 Peserta)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS peserta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_peserta TEXT UNIQUE NOT NULL
        )
        """
    )

    # Tabel Penilaian
    # Kombinasi nama_juri (case-insensitive) dan peserta_id dibuat unik
    # agar juri yang sama tidak bisa menginputkan nilai 2 kali.
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS penilaian (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_juri TEXT NOT NULL,
            nama_juri_lower TEXT NOT NULL,
            instansi_id INTEGER NOT NULL,
            peserta_id INTEGER NOT NULL,
            nilai INTEGER NOT NULL CHECK(nilai >= 0 AND nilai <= 100),
            waktu_input TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             UNIQUE(nama_juri_lower, peserta_id),
            FOREIGN KEY(instansi_id) REFERENCES instansi(id) ON DELETE CASCADE,
            FOREIGN KEY(peserta_id) REFERENCES peserta(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# ==================== HELPER FUNCTIONS ====================
def get_instansi_list():
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, nama_instansi FROM instansi ORDER BY id ASC", conn)
    conn.close()
    return df


def get_peserta_list():
    conn = get_connection()
    df = pd.read_sql_query("SELECT id, nama_peserta FROM peserta ORDER BY id ASC", conn)
    conn.close()
    return df


def get_all_scores():
    conn = get_connection()
    query = """
        SELECT 
            pn.id,
            p.nama_peserta AS "Nama Peserta",
            pn.nama_juri AS "Nama Juri",
            i.nama_instansi AS "Instansi Juri",
            pn.nilai AS "Nilai",
            pn.waktu_input AS "Waktu Input"
        FROM penilaian pn
        JOIN peserta p ON pn.peserta_id = p.id
        JOIN instansi i ON pn.instansi_id = i.id
        ORDER BY p.id ASC, pn.waktu_input DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_summary_scores():
    conn = get_connection()
    query = """
        SELECT 
            p.id AS "No",
            p.nama_peserta AS "Nama Peserta",
            COUNT(pn.id) AS "Jumlah Juri Menilai",
             COALESCE(ROUND(AVG(pn.nilai), 2), 0) AS "Rata-rata Nilai",
            COALESCE(SUM(pn.nilai), 0) AS "Total Nilai",
            COALESCE(MIN(pn.nilai), 0) AS "Nilai Terendah",
            COALESCE(MAX(pn.nilai), 0) AS "Nilai Tertinggi"
        FROM peserta p
        LEFT JOIN penilaian pn ON p.id = pn.peserta_id
        GROUP BY p.id, p.nama_peserta
        ORDER BY "Rata-rata Nilai" DESC, p.id ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def get_scored_peserta_by_juri(nama_juri: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT peserta_id, nilai, instansi_id
        FROM penilaian
        WHERE nama_juri_lower = ?
        """,
        (nama_juri.strip().lower(),),
    )
    rows = c.fetchall()
    conn.close()
    return {row[0]: {"nilai": row[1], "instansi_id": row[2]} for row in rows}


# ==================== UI SIDEBAR ====================
st.sidebar.title("🧭 Navigasi Aktor")
role = st.sidebar.radio("Pilih Peran (Role):", ["Juri", "Admin"])

st.sidebar.markdown("---")
st.sidebar.info(
    "**Ketentuan Sistem:**\n"
    "- **Admin**: Menginputkan nama instansi, menginputkan nama peserta (12 peserta), dan melihat seluruh daftar nilai.\n"
    "- **Juri**: Memilih nama instansi (dropdown), memilih nama peserta (dropdown), dan mengisi nilai (0–100). Juri tidak dapat menginputkan nilai 2 kali."
)


# ==================== HALAMAN ADMIN ====================
if role == "Admin":
    st.title("🛠️ Panel Admin - Sistem Penilaian")

    tab_peserta, tab_instansi, tab_nilai = st.tabs(
        [
            "👥 Input Nama Peserta (12 Peserta)",
            "🏢 Input Nama Instansi",
            "📊 Daftar Nilai Seluruh Peserta",
        ]
    )

    # --- TAB 1: INPUT PESERTA ---
    with tab_peserta:
        st.subheader(f"Kelola Daftar Peserta (Maksimal {MAX_PESERTA} Peserta)")
        df_peserta = get_peserta_list()
        jumlah_saat_ini = len(df_peserta)

        st.progress(
            min(jumlah_saat_ini / MAX_PESERTA, 1.0),
            text=f"Jumlah Peserta Terdaftar: {jumlah_saat_ini} / {MAX_PESERTA} Peserta",
        )

        col_input, col_list = st.columns([1, 1.3])

        with col_input:
            if jumlah_saat_ini < MAX_PESERTA:
                with st.form("form_tambah_peserta", clear_on_submit=True):
                    nama_peserta_baru = st.text_input(
                        f"Nama Peserta ke-{jumlah_saat_ini + 1}",
                        placeholder="Masukkan nama peserta...",
                    )
                    submit_peserta = st.form_submit_button("➕ Tambah Peserta", use_container_width=True)

                    if submit_peserta:
                        nama_bersih = nama_peserta_baru.strip()
                        if not nama_bersih:
                            st.error("Nama peserta tidak boleh kosong!")
                        else:
                            try:
                                conn = get_connection()
                                c = conn.cursor()
                                c.execute(
                                    "INSERT INTO peserta (nama_peserta) VALUES (?)",
                                    (nama_bersih,),
                                )
                                conn.commit()
                                conn.close()
                                st.success(f"Peserta '{nama_bersih}' berhasil ditambahkan!")
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("Nama peserta tersebut sudah terdaftar!")
            else:
                st.success(f"✅ Kuota {MAX_PESERTA} peserta sudah terpenuhi.")

            # Opsi isi cepat 12 peserta jika masih kurang
            if jumlah_saat_ini == 0:
                st.markdown("---")
                if st.button("⚡ Isi Otomatis 12 Peserta Contoh", use_container_width=True):
                    conn = get_connection()
                    c = conn.cursor()
                    for i in range(1, MAX_PESERTA + 1):
                        c.execute(
                            "INSERT OR IGNORE INTO peserta (nama_peserta) VALUES (?)",
                            (f"Peserta {i:02d}",),
                        )
                    conn.commit()
                    conn.close()
                    st.rerun()

        with col_list:
            st.markdown("##### Daftar Peserta Saat Ini")
            if df_peserta.empty:
                st.warning("Belum ada peserta yang diinputkan.")
            else:
                for idx, row in df_peserta.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"**{idx + 1}.** {row['nama_peserta']}")
                    if c2.button("🗑️", key=f"del_p_{row['id']}", help="Hapus peserta ini"):
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM peserta WHERE id = ?", (row["id"],))
                        conn.commit()
                        conn.close()
                        st.rerun()

    # --- TAB 2: INPUT INSTANSI ---
    with tab_instansi:
        st.subheader("Kelola Daftar Instansi")
        df_instansi = get_instansi_list()

        col_inst_in, col_inst_list = st.columns([1, 1.3])

        with col_inst_in:
            with st.form("form_tambah_instansi", clear_on_submit=True):
                nama_instansi_baru = st.text_input(
                    "Nama Instansi",
                    placeholder="Contoh: Dinas Komunikasi dan Informatika...",
                )
                submit_instansi = st.form_submit_button("➕ Tambah Instansi", use_container_width=True)

                if submit_instansi:
                    inst_bersih = nama_instansi_baru.strip()
                    if not inst_bersih:
                        st.error("Nama instansi tidak boleh kosong!")
                    else:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                "INSERT INTO instansi (nama_instansi) VALUES (?)",
                                (inst_bersih,),
                            )
                            conn.commit()
                            conn.close()
                            st.success(f"Instansi '{inst_bersih}' berhasil ditambahkan!")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("Nama instansi tersebut sudah ada!")

        with col_inst_list:
            st.markdown("##### Daftar Instansi Terdaftar")
            if df_instansi.empty:
                st.warning("Belum ada instansi yang diinputkan.")
            else:
                for idx, row in df_instansi.iterrows():
                    c1, c2 = st.columns([4, 1])
                    c1.write(f"**{idx + 1}.** {row['nama_instansi']}")
                    if c2.button("🗑️", key=f"del_i_{row['id']}", help="Hapus instansi ini"):
                        conn = get_connection()
                        c = conn.cursor()
                        c.execute("DELETE FROM instansi WHERE id = ?", (row["id"],))
                        conn.commit()
                        conn.close()
                        st.rerun()

    # --- TAB 3: DAFTAR NILAI SELURUH PESERTA ---
    with tab_nilai:
        st.subheader("📊 Rekapitulasi Nilai Seluruh Peserta")
        df_summary = get_summary_scores()
        df_detail = get_all_scores()

        if df_summary.empty:
            st.info("Belum ada data peserta.")
        else:
            st.markdown("#### 🏆 Peringkat & Rata-rata Nilai Peserta")
            df_ranking = df_summary.copy()
            df_ranking.insert(0, "Peringkat", range(1, len(df_ranking) + 1))
            st.dataframe(df_ranking.drop(columns=["No"]), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 📝 Rincian Penilaian dari Setiap Juri")
        if df_detail.empty:
            st.info("Belum ada nilai yang masuk dari Juri.")
        else:
            # Tabel Matriks Juri x Peserta
            pivot_df = df_detail.pivot_table(
                index="Nama Peserta",
                columns="Nama Juri",
                values="Nilai",
                aggfunc="first",
            )
            st.markdown("##### Matriks Nilai (Peserta vs Juri)")
            st.dataframe(pivot_df, use_container_width=True)

            st.markdown("##### Log Riwayat Input Nilai Juri")
            st.dataframe(df_detail.drop(columns=["id"]), use_container_width=True, hide_index=True)

            csv_data = df_detail.drop(columns=["id"]).to_csv(index=False).encode("utf-8")
            st.download_button(
                label="⬇️ Download Daftar Nilai (CSV)",
                data=csv_data,
                file_name="daftar_nilai_peserta.csv",
                mime="text/csv",
            )


# ==================== HALAMAN JURI ====================
elif role == "Juri":
    st.title("⚖️ Form Penilaian Juri")

    df_instansi = get_instansi_list()
    df_peserta = get_peserta_list()

    if df_instansi.empty or df_peserta.empty:
        st.warning(
            "⚠️ **Data belum siap!** Mohon minta **Admin** untuk menginputkan daftar **Nama Instansi** dan **Nama Peserta** terlebih dahulu."
        )
        st.stop()

    st.markdown(
        "Silakan masukkan **Nama Juri**, pilih **Nama Instansi** dari dropdown, lalu pilih **Nama Peserta** dan masukkan nilai (**0 - 100**)."
    )

    col_juri, col_inst = st.columns(2)

    with col_juri:
        nama_juri = st.text_input(
            "Nama Lengkap Juri",
            placeholder="Ketik nama lengkap Anda...",
        ).strip()

    # Cek riwayat penilaian juri ini
    scored_map = get_scored_peserta_by_juri(nama_juri) if nama_juri else {}

    # Jika juri ini sudah pernah memilih instansi sebelumnya, kunci ke instansi yang sama
    instansi_dict = dict(zip(df_instansi["nama_instansi"], df_instansi["id"]))
    id_to_instansi = dict(zip(df_instansi["id"], df_instansi["nama_instansi"]))

    default_inst_index = 0
    locked_instansi_id = None
    if scored_map:
        first_record = next(iter(scored_map.values()))
        locked_instansi_id = first_record["instansi_id"]
        if locked_instansi_id in id_to_instansi:
            locked_inst_name = id_to_instansi[locked_instansi_id]
            default_inst_index = list(instansi_dict.keys()).index(locked_inst_name)

    with col_inst:
        selected_instansi_nama = st.selectbox(
            "Pilih Nama Instansi (Dropdown)",
            options=list(instansi_dict.keys()),
            index=default_inst_index,
            disabled=(locked_instansi_id is not None),
            help="Nama instansi dipilih melalui dropdown sesuai daftar dari Admin.",
        )
        selected_instansi_id = instansi_dict[selected_instansi_nama]

    if not nama_juri:
        st.info("👆 Masukkan **Nama Lengkap Juri** terlebih dahulu untuk mulai menilai peserta.")
        st.stop()

    total_peserta = len(df_peserta)
    jumlah_dinilai = len(scored_map)

    st.markdown("---")
    st.progress(
        min(jumlah_dinilai / total_peserta, 1.0),
        text=f"Progres Penilaian Juri '{nama_juri}': {jumlah_dinilai} dari {total_peserta} Peserta telah dinilai",
    )

    # Filter peserta yang BELUM dinilai oleh juri ini
    peserta_belum_dinilai = df_peserta[~df_peserta["id"].isin(scored_map.keys())]

    if peserta_belum_dinilai.empty:
        st.error(
            f"🔒 **Akses Terkunci:** Juri dengan nama **{nama_juri}** telah selesai menilai seluruh ({total_peserta}) peserta. "
            "Sesuai ketentuan sistem, Juri tidak dapat menginputkan nilai 2 kali!"
        )
    else:
        col_form, col_status = st.columns([1.2, 1])

        with col_form:
            st.subheader("📝 Input Nilai Peserta")
            with st.form("form_penilaian_juri"):
                peserta_options = dict(
                    zip(peserta_belum_dinilai["nama_peserta"], peserta_belum_dinilai["id"])
                )

                selected_peserta_nama = st.selectbox(
                    "Pilih Nama Peserta (Dropdown)",
                    options=list(peserta_options.keys()),
                )

                nilai_input = st.number_input(
                    "Nilai Peserta (Rentang 0 - 100)",
                    min_value=0,
                    max_value=100,
                    value=80,
                    step=1,
                )

                submit_nilai = st.form_submit_button("💾 Simpan Nilai Peserta", use_container_width=True)

                if submit_nilai:
                    peserta_id = peserta_options[selected_peserta_nama]
                    # Validasi ganda di sisi database agar tidak bisa input 2 kali
                    if peserta_id in get_scored_peserta_by_juri(nama_juri):
                        st.error(
                            f"❌ Juri '{nama_juri}' sudah pernah menilai peserta '{selected_peserta_nama}'. Tidak dapat menginputkan 2 kali!"
                        )
                    else:
                        try:
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                """
                                INSERT INTO penilaian (nama_juri, nama_juri_lower, instansi_id, peserta_id, nilai)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (
                                    nama_juri,
                                    nama_juri.lower(),
                                    selected_instansi_id,
                                    peserta_id,
                                    int(nilai_input),
                                ),
                            )
                            conn.commit()
                            conn.close()
                            st.success(
                                f"✅ Nilai **{nilai_input}** untuk **{selected_peserta_nama}** berhasil disimpan!"
                            )
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(
                                "❌ Anda sudah pernah memasukkan nilai untuk peserta ini! Juri tidak dapat menginputkan 2 kali."
                            )

        with col_status:
            st.subheader("📋 Status Penilaian Anda")
            status_rows = []
            for _, row in df_peserta.iterrows():
                pid = row["id"]
                udah = pid in scored_map
                status_rows.append(
                    {
                        "Nama Peserta": row["nama_peserta"],
                        "Status": "✅ Sudah Dinilai" if udah else "⏳ Belum Dinilai",
                    }
                )
            st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

