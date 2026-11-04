/**
 * ============================================================================
 * GOOGLE APPS SCRIPT - DATABASE SPREADSHEET PENILAIAN DEWAN JURI (CLOUD DEPLOY)
 * ============================================================================
 * CARA MENGHUBUNGKAN KE GOOGLE SPREADSHEET:
 * 1. Buka Google Spreadsheet baru di https://sheets.google.com
 * 2. Klik menu "Ekstensi" (Extensions) -> "Apps Script"
 * 3. Hapus semua kode bawaan, lalu PASTE seluruh kode ini.
 * 4. Klik ikon Simpan (💾), lalu klik "Terapkan" (Deploy) -> "Deployment baru" (New deployment).
 * 5. Pilih jenis: "Aplikasi Web" (Web app):
 *    - Jalankan sebagai (Execute as): "Saya" (Me)
 *    - Siapa yang memiliki akses (Who has access): "Siapa saja" (Anyone)
 * 6. Klik "Terapkan" (Deploy), berikan izin akses (Authorize access), lalu COPY "URL Aplikasi Web".
 * 7. Tempelkan URL tersebut di halaman Admin (/admin/masuk -> Kelola Data -> Koneksi Google Spreadsheet)
 *    atau di Streamlit Cloud Secrets: GSHEET_WEBAPP_URL = "https://script.google.com/macros/s/.../exec"
 * ============================================================================
 */

const SHEETS_CONFIG = {
  "Peserta": ["id", "nama_peserta", "asal_instansi", "judul_project"],
  "Instansi": ["id", "nama_instansi"],
  "Penilaian_Juri": [
    "Nama Peserta", "Instansi Peserta", "Nama Dewan Juri", "Instansi Juri",
    "1. Riset & Inovasi", "2. Generative AI", "3. Relevansi Industri",
    "4. Kualitas Project", "5. Potensi Manfaat", "6. Presentasi",
    "7. Akurasi & Etika AI", "Rata-rata Nilai", "Waktu Penilaian"
  ],
  "Vote_Favorit": ["Nama Dewan Juri", "Instansi Juri", "Peserta Favorit Pilihan", "Waktu Vote"],
  "Ranking_Final": ["Peringkat", "Nama Peserta", "Instansi Peserta", "Judul Project", "Jumlah Juri Menilai", "Nilai Akhir"]
};

function ensureSheetsExist() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  for (const [sheetName, headers] of Object.entries(SHEETS_CONFIG)) {
    let sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }
    if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
      sheet.getRange(1, 1, 1, headers.length)
        .setBackground("#0d2240")
        .setFontColor("#f5d78e")
        .setFontWeight("bold");
      sheet.setFrozenRows(1);
    }
  }
}

function writeSheetData(sheetName, rows) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const headers = SHEETS_CONFIG[sheetName];
  if (!headers) return;

  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
  }
  sheet.clearContents();
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length)
    .setBackground("#0d2240")
    .setFontColor("#f5d78e")
    .setFontWeight("bold");

  if (rows && rows.length > 0) {
    const matrix = rows.map(r => headers.map(h => (r[h] !== undefined && r[h] !== null) ? r[h] : ""));
    sheet.getRange(2, 1, matrix.length, headers.length).setValues(matrix);
  }
}

function doGet(e) {
  ensureSheetsExist();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const result = {};

  for (const sheetName of Object.keys(SHEETS_CONFIG)) {
    const sheet = ss.getSheetByName(sheetName);
    const data = sheet.getDataRange().getValues();
    if (data.length <= 1) {
      result[sheetName] = [];
    } else {
      const headers = data[0];
      result[sheetName] = data.slice(1).map(row => {
        const obj = {};
        headers.forEach((h, i) => { obj[h] = row[i]; });
        return obj;
      });
    }
  }

  return ContentService
    .createTextOutput(JSON.stringify({ status: "ok", data: result }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  try {
    ensureSheetsExist();
    const payload = JSON.parse(e.postData.contents);
    if (payload.sheets) {
      for (const [sheetName, rows] of Object.entries(payload.sheets)) {
        writeSheetData(sheetName, rows);
      }
    }
    return ContentService
      .createTextOutput(JSON.stringify({ status: "ok", message: "Spreadsheet berhasil diperbarui!" }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: "error", message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
