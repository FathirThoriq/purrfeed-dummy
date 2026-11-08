# PURR-FEED — Website + Sistem Cerdas Pet Feeder

Purwarupa lokal smart pet feeder untuk kucing dan anjing. **ESP32-CAM memotret otomatis tiap ±9 detik**
(`INTERVAL_MS` di sketch; polling dashboard tiap 2 detik) dan mengirim ke `POST /api/predict`; server
mengklasifikasikan dengan **rembg (segmentasi) + MobileNetV2 (ekstraksi fitur) + SVM RBF**, memutuskan **BERI PAKAN** atau **TAHAN**,
lalu mengurangi stok tabung. Tab upload di dashboard memakai endpoint dan model yang sama (hanya `source`-nya
berbeda). Alat asli cukup memanggil endpoint yang sama.

Dashboard mulai **kosong**: tidak ada data contoh. Riwayat, statistik, dan grafik terisi hanya dari klasifikasi
sungguhan (ESP32-CAM atau Upload). Stok tabung tetap simulasi (porsi ±30 g dengan derau, bukan load cell).
Model dilatih terpisah di Google Colab; repo ini hanya memuat hasilnya (`models/`).

## Arsitektur

```text
 Browser / ESP32-CAM / Postman
              │ HTTP
              ▼
 ┌────────────────────── Flask (app.py) ──────────────────────┐
 │ routes.py   halaman web + endpoint /api/*                  │
 │ models.py   memuat model sekali saat start                 │
 │   └ features.py  rembg + MobileNetV2 → vektor 1280 fitur   │
 │   └ SVM RBF (scikit-learn) → probabilitas kelas           │
 │ decision.py keputusan BERI PAKAN / TAHAN (ambang τ)        │
 │ feeder.py   simulasi tabung, prakiraan habis, notifikasi,  │
 │             statistik, riwayat, export                    │
 │ assistant.py Purr Assistant (jawaban dari data DB)        │
 │ db.py       SQLite: alat & log kejadian                    │
 └─────────────────────────────────────────────────────────────┘
```

Alur satu foto:

```text
foto (esp32cam/upload/webcam) → rembg (potong objek, latar abu-abu) → MobileNetV2 (1280 fitur)
     → StandardScaler → SVM RBF (kalibrasi sigmoid) → p(kucing / anjing / other)
     → label = target & p ≥ τ (0,9) ? BERI PAKAN : TAHAN
     → stok berkurang ±30 g, kejadian dicatat → dashboard
```

## Struktur folder

```
purrfeed-dummy/
├── app.py                    titik masuk: python app.py
├── requirements.txt
├── purrfeed/                 paket aplikasi
│   ├── __init__.py           create_app(): konfigurasi, database, model, blueprint
│   ├── config.py             path, kapasitas tabung, porsi, ID alat terdaftar, API pribadi
│   ├── features.py           FeatureExtractor (rembg + MobileNetV2) + load_rgb (orientasi EXIF)
│   ├── models.py             ModelRegistry: satu model per mode (kucing / anjing)
│   ├── decision.py           aturan keputusan dan format persen
│   ├── feeder.py             tabung, stok, statistik, grafik, riwayat, saran, export
│   ├── assistant.py          Purr Assistant: jawaban berbasis data (tanpa LLM, tanpa angka karangan)
│   ├── db.py                 skema SQLite, query
│   ├── routes.py             halaman dan endpoint API
│   └── static/               index.html (masuk), dashboard.html/.js, style.css, theme.js,
│                             vendor/lucide.min.js, fonts/ (self-host), mascot-sprite.svg, favicon.svg
├── models/                   hasil training: kucing.joblib, anjing.joblib (lihat models/README.md)
├── persona.md                gaya bicara Purr Assistant
├── .env.example              contoh konfigurasi API pribadi
└── instance/feeder.db        dibuat otomatis saat server pertama jalan
```

## Persiapan

Python 3.12 (TensorFlow belum mendukung 3.14). Dari folder proyek:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Ekstraksi fitur memakai TensorFlow (MobileNetV2) dan rembg (segmentasi), sama dengan notebook training. Semuanya CPU,
tidak perlu GPU. Bobot MobileNetV2 dan model segmentasi (`~/.u2net/isnet-general-use.onnx`) diunduh otomatis saat
pertama dijalankan.

## Menjalankan

```bash
python app.py
```

Buka http://127.0.0.1:5000, masukkan ID alat, pilih **Kucing** atau **Anjing**, lalu:

- **ESP32-CAM** (tab bawaan): hasil kamera tampil otomatis tiap ada frame baru (`POST /api/predict`
  dengan `source=esp32cam`, polling `/api/latest` tiap 2 detik);
- **Upload Gambar**: pilih file lalu **Klasifikasi Gambar** (endpoint sama, `source=upload`).

| ID alat | Hewan awal |
|---|---|
| `FEED-0001` | kucing |
| `FEED-0002` | anjing |
| `FEED-0003` | kucing |

Semua ID mulai dengan tabung penuh (2.000 g) dan tanpa riwayat. Hewan dipilih ulang tiap masuk.

Kode `PF-XXXXX` dari halaman setup ESP32-CAM (`~/Arduino/purrfeed_provisioning`) tidak perlu didaftarkan:
server mendaftarkannya otomatis saat foto pertama masuk atau saat kode itu dipakai login.
Format: `PF-` + 5 karakter dari `23456789ABCDEFGHJKLMNPQRSTUVWXYZ`; format lain tetap ditolak.

Variabel lingkungan opsional: `PORT` (default 5000), `HOST` (default 127.0.0.1; pakai `0.0.0.0` agar bisa
diakses perangkat lain di Wi-Fi yang sama), `PURRFEED_DB`, `PURRFEED_MODEL_DIR`.

Reset semua data: matikan server, hapus `instance/feeder.db`, nyalakan lagi (ID alat dibuat ulang, riwayat kosong).

## Model hasil training

Training dilakukan di Google Colab. Repo web ini hanya **memuat** hasilnya dari `models/`:

| File | Untuk |
|---|---|
| `models/kucing.joblib` | alat mode Kucing |
| `models/anjing.joblib` | alat mode Anjing |

Model yang terpasang: MobileNetV2 (ImageNet, beku) + SVM RBF (C=10, gamma=1e-4), 3 kelas (`anjing`, `kucing`, `other`),
dikalibrasi sigmoid, τ = 0,9. Kedua file berisi classifier yang sama; yang beda hanya `target`.

Cara memasang model baru:

1. Latih di Colab dengan fitur yang sama (segmentasi rembg `isnet-general-use`, crop persegi di latar abu-abu 127,
   224x224, JPEG, `preprocess_input` MobileNetV2).
2. Simpan sebagai `models/<hewan>.joblib` (format di `models/README.md`) dengan scikit-learn versi sama dengan `.venv`.
3. Restart server, lalu buka `/api/health`. Hewan harus ada di `model_siap`. Bila ditolak, alasannya ada di
   `model_ditolak` dan tampil sebagai notifikasi di dashboard.

Server memeriksa isi file saat dimuat: kunci wajib (`classifier`, `target`, `tau`, `algorithm`), `feature_version`
harus sama dengan `purrfeed/features.py`, jumlah fitur 1280, `target` sama dengan nama file. Model yang tidak
cocok ditolak, bukan dipakai dengan prediksi yang diam-diam salah.

Ubah backbone atau preprocessing di `purrfeed/features.py` berarti naikkan `FEATURE_VERSION`, lalu latih ulang model.

## Aturan keputusan

| Kondisi | Keputusan | Alasan (`alasan`) |
|---|---|---|
| label ≠ target mode (mis. `other`) | TAHAN | `terdeteksi other, bukan target (kucing)` |
| label = target, keyakinan < τ | TAHAN | `keyakinan 54,2% < τ 0,90` |
| label = target, keyakinan ≥ τ, stok cukup | BERI PAKAN | `keyakinan 99,9% ≥ τ 0,90` |
| BERI PAKAN tetapi stok < satu porsi | TAHAN | `stok pakan habis` |

τ = 0,9 disimpan di dalam model (kunci `tau` pada file `.joblib`). Keyakinan ≥ 99,95% ditampilkan sebagai "> 99,9%".

## Simulasi alat

| Parameter (`purrfeed/config.py`) | Nilai |
|---|---|
| Kapasitas tabung | 2.000 g |
| Porsi | 30 g ± 2 g (meniru ketidaktelitian load cell) |
| Prakiraan habis | sisa ÷ rata-rata pakan harian 7 hari terakhir (hari tanpa pakan diabaikan; minimal 3 hari data) |
| Notifikasi | ≤ 3 hari: `peringatan` · ≤ 1 hari: `mendesak` · stok < 10%: `mendesak` · < 3 hari data & stok < 20%: `peringatan` |

## Endpoint API

Semua balasan berupa JSON. Error selalu berbentuk `{"error": "pesan"}` dengan kode HTTP yang sesuai.

| Metode | Endpoint | Fungsi |
|---|---|---|
| GET | `/api/health` | status server dan model yang siap |
| POST | `/api/devices/claim` | daftarkan ID alat dan pilih hewan |
| GET | `/api/dashboard?code=…` | semua data dashboard satu alat |
| POST | `/api/predict` | klasifikasi foto + keputusan pakan (`source`: `esp32cam`/`upload`/`webcam`) |
| GET | `/api/latest`, `/api/latest.jpg` | frame + hasil terakhir ESP32-CAM (polling dashboard) |
| POST | `/api/refill` | isi ulang tabung sampai penuh |
| POST | `/api/chat` | Purr Assistant (jawaban dari data alat, hanya membaca) |
| GET | `/api/proaktif?code=…` | pesan yang Purr sampaikan sendiri (badge merah) |
| GET | `/api/export?code=…&format=csv\|xlsx` | unduh riwayat 7 hari terakhir |
| GET | `/`, `/dashboard` | halaman web |

### GET /api/health

```bash
curl http://127.0.0.1:5000/api/health
```

```json
{"status": "ok", "model_siap": ["kucing", "anjing"], "model": {"kucing": {"algoritma": "...", "tau": 0.9, "dilatih": "2026-11-01T22:34:43"}},
 "model_ditolak": {}}
```

### POST /api/devices/claim

Body JSON: `code` (wajib, tidak peka huruf besar/kecil), `mode` (`kucing` | `anjing`, default `kucing`).

```bash
curl -X POST http://127.0.0.1:5000/api/devices/claim \
     -H "Content-Type: application/json" -d '{"code": "FEED-0001", "mode": "kucing"}'
```

```json
{"device": {"code": "FEED-0001", "mode": "kucing", "kapasitas_g": 2000.0, "sisa_g": 1306.4,
            "porsi_g": 30.0, "model_tersedia": true}}
```

| Kode | Kapan |
|---|---|
| 400 | `mode` bukan `kucing` / `anjing` |
| 404 | kode alat tidak ditemukan |

### POST /api/predict

Body `multipart/form-data`:

| Field | Wajib | Keterangan |
|---|---|---|
| `file` | ya | gambar JPG/PNG/WebP, maks 8 MB |
| `code` | tidak | ID alat; bila ada, stok dikurangi dan kejadian dicatat |
| `mode` | tidak | `kucing` / `anjing`; default mode alat, atau `kucing` |
| `source` | tidak | `esp32cam` (default, mengisi `/api/latest`), `upload`, atau `webcam` |

```bash
curl -X POST http://127.0.0.1:5000/api/predict \
     -F "file=@foto_kucing.jpg" -F "code=FEED-0001"
```

```json
{
  "label": "kucing",
  "confidence": 0.9994,
  "probabilitas": {"anjing": 0.0004, "kucing": 0.9994, "other": 0.0002},
  "keputusan": "BERI PAKAN",
  "alasan": "keyakinan 99,9% ≥ τ 0,90",
  "pakan_keluar_g": 29.1,
  "stok": {"sisa_g": 1277.3, "kapasitas_g": 2000.0, "persen": 63.9, "rata_harian_g": 99.1,
           "perkiraan_habis_hari": 12.9, "perkiraan_habis_tanggal": "2026-11-13", "hari_data": 7},
  "waktu_ms": 88.3,
  "model": "SVM RBF",
  "mode": "kucing",
  "tau": 0.9,
  "kode": "FEED-0001",
  "simulasi": true
}
```

Tanpa `code`, hanya klasifikasi: `pakan_keluar_g` = 0 dan `stok` = `null`.

| Kode | Kapan |
|---|---|
| 400 | `file` tidak ada, file bukan gambar, atau `mode` tidak dikenal |
| 404 | `code` diisi tetapi tidak ditemukan |
| 409 | model untuk hewan tersebut belum ada atau ditolak |
| 413 | file lebih dari 8 MB |

Di Postman: *Body* → *form-data* → key `file` bertipe *File*, key `code` bertipe *Text*.

### GET /api/dashboard?code=FEED-0001

```json
{
  "device": {"code": "FEED-0001", "mode": "kucing", "kapasitas_g": 2000.0, "sisa_g": 1277.3,
             "porsi_g": 30.0, "model_tersedia": true},
  "stok": {"sisa_g": 1277.3, "kapasitas_g": 2000.0, "persen": 63.9, "rata_harian_g": 99.1,
           "perkiraan_habis_hari": 12.9, "perkiraan_habis_tanggal": "2026-11-13", "hari_data": 7},
  "hari_ini": {"pakan_g": 29.1, "beri": 1, "tahan": 1},
  "notifikasi": [],
  "grafik": [{"tanggal": "2026-10-26", "pakan_g": 91.2, "beri": 3, "tahan": 0}, "… 7 hari …"],
  "riwayat": [{"ts": "2026-11-01 22:21:39", "jenis": "tahan", "gram": 0.0, "label": "other",
               "confidence": 1.0, "thumb": "data:image/jpeg;base64,…"}, "… maks 20 …"],
  "simulasi": true
}
```

`jenis` riwayat: `beri`, `tahan`, `isi_ulang` (`buang` disiapkan untuk laporan sisa dari alat asli). `sumber`: `esp32cam`,
`upload`, `webcam`, `sistem`. `notifikasi[].level`: `peringatan`, `mendesak`.
Kode 404 bila alat tidak ditemukan.

### POST /api/refill

```bash
curl -X POST http://127.0.0.1:5000/api/refill \
     -H "Content-Type: application/json" -d '{"code": "FEED-0001"}'
```

```json
{"ditambahkan_g": 722.7, "stok": {"sisa_g": 2000.0, "persen": 100.0, "perkiraan_habis_hari": 20.2, "…": "…"}}
```

Kode 404 bila alat tidak ditemukan.

## Purr Assistant dengan API pribadi

Tanpa konfigurasi, chat memakai jawaban aturan (`assistant.rule_reply`). Dengan API kompatibel OpenAI
(`POST {URL}/chat/completions`), jawaban dibuat LLM dari **persona + data alat**:

Cara termudah: `cp .env.example .env`, isi `PURRFEED_LLM_URL`, `PURRFEED_LLM_MODEL`, `PURRFEED_LLM_KEY`, lalu
nyalakan ulang server (`.env` hanya dibaca saat start). `.env` ada di `.gitignore`. Atau lewat shell:

```bash
export PURRFEED_LLM_URL=https://api-kamu.example/v1     # boleh sampai /chat/completions
export PURRFEED_LLM_KEY=...                              # opsional, dikirim sebagai Bearer
export PURRFEED_LLM_MODEL=nama-model
export PURRFEED_LLM_HEADERS='{"X-Header": "nilai"}'      # opsional, header tambahan (JSON)
python app.py                                            # fish: set -x PURRFEED_LLM_URL ...
```

Opsional: `PURRFEED_LLM_TEMPERATURE` (0,4), `PURRFEED_LLM_MAX_TOKENS` (300), `PURRFEED_LLM_TIMEOUT` (15 dtk),
`PURRFEED_PERSONA` (path file persona).

| File | Fungsi |
|---|---|
| `persona.md` | gaya bicara, cakupan, larangan. Dibaca ulang tiap pesan: edit, simpan, langsung berlaku |
| `purrfeed/insights.py` | "belajar dari data": menghitung pola dari riwayat 7 hari (terbuang per waktu makan, confidence per sumber, tren pakan, hewan sasaran ditahan) + saran otomatis, dikirim ke LLM sebagai blok `DATA ALAT` |
| `purrfeed/llm.py` | klien API, parsing keluaran JSON `{"teks", "aksi"}`, pembersih (emoji, markdown, nama model) |

Purr hanya **membaca**: menjelaskan data dan memberi saran, tidak menggerakkan servo. Permintaan seperti
"buang sisa pakan" dijawab bahwa Purr hanya bisa memberi saran.

Pengaman:
- Angka hanya dari blok `DATA ALAT`; persona melarang mengarang. Bila belum ada data (mis. pakan terbuang),
  konteks menyuruh model bilang belum ada, bukan menebak.
- Jawaban yang mengaku "sudah dibuang/diberi" ditolak dan diganti jawaban aturan.
- API mati, timeout, HTTP error, atau balasan kosong/rusak: otomatis jawaban aturan. Respons `/api/chat`
  memuat `sumber` (`llm` / `aturan`).
- Konteks 6 giliran terakhir ikut dikirim; isi persona dan kunci API tidak pernah dikirim ke browser.

**Inisiatif Purr.** Dashboard memeriksa `/api/proaktif` tiap 30 detik; bila ada hal yang perlu disampaikan, badge
merah berisi angka muncul di tombol Purr dan pesannya masuk ke chat saat dibuka (stok < 20% / < 10%, perkiraan habis
≤ 3 hari, ESP32-CAM diam > 2 menit, pola dari data). Dihitung dengan aturan, tanpa memakai API. Status "sudah dibaca"
disimpan di browser. Tombol tempat sampah di header chat membersihkan percakapan.

## Database (SQLite, `instance/feeder.db`)

| Tabel | Kolom |
|---|---|
| `devices` | `code` (PK), `mode`, `claimed`, `capacity_g`, `stock_g`, `portion_g` |
| `events` | `id`, `code`, `ts`, `kind` (`beri`/`tahan`/`isi_ulang`; `buang` untuk laporan sisa dari alat), `grams`, `label`, `confidence`, `thumbnail`, `mode`, `source` (`esp32cam`/`upload`/`webcam`/`servo`/`sistem`), `elapsed_ms`, `ref_id` |

Skema v4: database dengan skema lebih lama dimigrasi (v3 ke v4 tanpa kehilangan riwayat) atau dipindah ke
`instance/feeder.db.v<versi>-<waktu>.bak` dan dibuat ulang tanpa riwayat.

## Ke alat asli (ESP32-CAM + 2 servo)

Sketch: `~/Arduino/esp32cam_purrfeed/esp32cam_purrfeed.ino` (AI Thinker, `INTERVAL_MS` 5000, XGA q10).

1. Jalankan server dengan `HOST=0.0.0.0 PORT=5055 python app.py` (samakan `SERVER_HOST`/`SERVER_PORT`
   dengan IP laptop; interval di sketch: tiap 5 detik, prototipe web mensimulasikan tiap ±9 detik).
2. ESP32-CAM memotret otomatis dan mengirim `POST /api/predict` dengan `file` dan `code`
   (`source` default `esp32cam` → tampil di tab ESP32-CAM; dashboard polling `/api/latest` tiap 2 detik).
3. Bila `keputusan == "BERI PAKAN"`, sketch menggerakkan servo penyalur sendiri (server tidak punya kontrol
   servo manual). Berat dari load cell bisa menggantikan nilai `pakan_keluar_g` simulasi.

## Keterbatasan

- Foto cetak atau layar HP berisi kucing/anjing masih bisa lolos sebagai hewan asli (model belum dilatih dengan contoh itu).
- Kucing/anjing yang kepalanya tidak terlihat sering jatuh ke `other` (ditahan), kadang salah kelas.
- Orang di depan kamera dengan latar silau bisa salah terbaca bila segmentasi gagal (kotak "seluruh frame").
- Stok tabung dan berat porsi masih simulasi (belum ada load cell).
- Tidak ada autentikasi; jangan dibuka ke internet publik tanpa menambahkan API key.
