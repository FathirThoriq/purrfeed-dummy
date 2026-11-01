# PURR-FEED Dummy — Website + Sistem Cerdas Smart Cat Feeder

Purwarupa lokal smart cat feeder. Alat fisik belum dirakit, jadi **website berperan sebagai alat**: foto diunggah,
server mengklasifikasikan foto dengan **MobileNetV2 (ekstraksi fitur) + SVM (klasifikasi)**, memutuskan
**BERI PAKAN** atau **TAHAN**, lalu mengurangi stok tabung. Alat asli nanti cukup memanggil endpoint yang sama.

Semua data stok dan riwayat di dashboard adalah **data simulasi**.

## Arsitektur

```
 Browser / Postman / (nanti) ESP32
              │ HTTP
              ▼
 ┌────────────────────── Flask (app.py) ──────────────────────┐
 │ routes.py   halaman web + endpoint /api/*                  │
 │ models.py   memuat model sekali saat start                 │
 │   └ features.py  MobileNetV2 → vektor 1280 fitur           │
 │   └ SVM (scikit-learn) → probabilitas kucing / nonkucing   │
 │ decision.py keputusan BERI PAKAN / TAHAN (ambang τ)        │
 │ feeder.py   simulasi tabung, prakiraan habis, notifikasi   │
 │ db.py       SQLite: alat & log kejadian                    │
 └─────────────────────────────────────────────────────────────┘
```

Alur satu foto:

```
foto → MobileNetV2 (1280 fitur) → StandardScaler → SVM linear (Platt scaling) → p(kucing)
     → label = kucing & p ≥ τ (0,6)  ? BERI PAKAN : TAHAN
     → stok berkurang ±30 g, kejadian dicatat → dashboard
```

## Struktur folder

```
purrfeed-dummy/
├── app.py                    titik masuk: python app.py
├── requirements.txt
├── purrfeed/                 paket aplikasi
│   ├── __init__.py           create_app(): konfigurasi, database, model, blueprint
│   ├── config.py             path, kapasitas tabung, porsi, kode alat demo
│   ├── features.py           FeatureExtractor (MobileNetV2) + load_rgb (orientasi EXIF)
│   ├── models.py             ModelRegistry: satu model per mode (kucing / anjing)
│   ├── decision.py           aturan keputusan dan format persen
│   ├── feeder.py             simulasi alat: keluarkan porsi, isi ulang, stok, notifikasi, data dashboard
│   ├── db.py                 skema SQLite, data demo 7 hari, query
│   ├── routes.py             halaman dan endpoint API
│   └── static/               index.html (masuk), dashboard.html/.js, style.css
├── training/
│   ├── train.py              latih + evaluasi + simpan model
│   ├── augment.py            augmentasi: kucing hitam-putih, kucing dicetak / di layar HP
│   └── curate.py             kurasi kelas nonkucing (buang duplikat + k-means per kategori)
├── dataset/
│   ├── kucing/               266 foto kucing sendiri (data primer)
│   └── nonkucing/            551 hasil kurasi dari 1.916 gambar nonkucing
├── dataset_uji/              470 gambar khusus uji, tidak pernah dipakai latih
├── models/mobilenetv2_svm.joblib     model terlatih
├── reports/
│   ├── mobilenetv2_svm_metrics.json  metrik pelatihan terakhir
│   └── nonkucing_kurasi.csv          daftar 1.916 gambar: dipilih / tidak dipilih / duplikat
├── contoh_foto/              foto untuk dicoba di website
└── instance/feeder.db        dibuat otomatis saat server pertama jalan
```

## Persiapan

Python 3.10+. Dari folder proyek:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

PyTorch yang terpasang adalah versi CPU (tidak perlu GPU). Bobot MobileNetV2 (±14 MB) diunduh otomatis
saat pertama dijalankan.

## Menjalankan

```bash
python app.py
```

Buka http://127.0.0.1:5000, masukkan kode alat **FEED-0001**, pilih **Kucing**, lalu unggah foto dari
`contoh_foto/` di kartu *Simulasi alat*.

| Kode alat | Isi awal |
|---|---|
| `FEED-0001` | riwayat pakan 7 hari (grafik & prakiraan langsung terisi) |
| `FEED-0002`, `FEED-0003` | kosong, tabung penuh |

Variabel lingkungan opsional: `PORT` (default 5000), `HOST` (default 127.0.0.1; pakai `0.0.0.0` agar bisa
diakses perangkat lain di Wi-Fi yang sama), `PURRFEED_DB`, `PURRFEED_MODEL_DIR`.

Reset data simulasi: matikan server, hapus folder `instance/`, nyalakan lagi.

## Melatih ulang model

```bash
python -m training.train
```

Langkahnya:

1. Membaca `dataset/` (subfolder = kelas: `kucing`, `nonkucing`).
2. Membagi data asli secara bertingkat: 80% latih, 20% uji (seed 42).
3. Membuat augmentasi **di memori, hanya dari bagian latih** (tidak bocor ke data uji):
   - versi hitam-putih setiap foto kucing → kelas `kucing` (kamera malam);
   - 100 foto kucing "dicetak" / tampil di layar HP di atas foto benda rumah (`benda_*`) → kelas `nonkucing`.
4. Ekstraksi fitur MobileNetV2, latih SVM, evaluasi.
5. Melatih ulang dengan seluruh data, lalu menyimpan `models/mobilenetv2_svm.joblib` dan
   `reports/mobilenetv2_svm_metrics.json`.

Opsi: `--data`, `--extra`, `--background-prefix`, `--test-dir`, `--target`, `--negative`, `--prints`, `--test-size`, `--seed`,
`--tau`, `--C`, `--out`, `--no-refit`. Server harus dinyalakan ulang setelah model diganti.

### Hasil pelatihan terakhir

| Data uji (tidak dipakai saat latih) | Benar |
|---|---|
| Uji 20% (53 kucing + 111 nonkucing) | 164/164 — akurasi 100% (CI95 97,7–100%), macro-F1 1,000 |
| Kucing uji versi hitam-putih (diberi pakan) | 52/53 |
| Kucing uji versi cetak / layar HP (ditahan) | 33/33 |
| `dataset_uji/hewan_rumah` (27 jenis × 10) | 270/270 ditahan |
| `dataset_uji/mainan_*` (boneka, maneki-neko, Hello Kitty, mainan kucing) | 187/187 ditahan |
| `dataset_uji/hewan_lain` (anjing) | 9/10 ditahan |
| `dataset_uji/foto_user` (tikus, pipa busa, kucing cetak dari uji website) | 3/3 ditahan |

Waktu inferensi ±30–90 ms per foto di CPU laptop. Angka 100% berasal dari 164 foto uji; tulis sebagai
"akurasi ≥ 97% (CI 95%)" di laporan, bukan "sempurna".

## Dataset

**817 gambar asli**: 266 kucing (data primer, foto sendiri) dan 551 nonkucing (hasil kurasi). Rasio ±1 : 2,
ditangani `class_weight="balanced"`. Augmentasi (266 kucing hitam-putih + 100 kucing cetak/layar) dibuat
otomatis saat pelatihan, tidak disimpan sebagai file.

### Kurasi kelas nonkucing

Kelas nonkucing awalnya 1.916 gambar dari beberapa sumber (data sekunder). Agar tidak berlebihan dibanding
data primer, semuanya digabung lalu dikurasi dengan `training/curate.py`:

1. Ekstraksi fitur MobileNetV2 semua gambar.
2. Buang gambar nyaris kembar (kemiripan kosinus ≥ 0,97): 37 gambar.
3. Kelompokkan per kategori (dari nama file) dan beri kuota.
4. Per kategori, k-means dengan k = kuota; ambil satu gambar terdekat ke setiap pusat klaster sehingga
   variasi kategori tetap terwakili.

| Kategori | Dipilih / tersedia | Sumber |
|---|---|---|
| Benda rumah (`benda_*`) | 120 / 224 | dataset PURR-FEED |
| Gambar kucing palsu (`palsu_*`) | 13 / 13 | dataset PURR-FEED |
| Tikus, tikus got, hamster, tupai | 20 per jenis (80) | Kaggle `iamsouravbanerjee/animal-image-dataset-90-different-animals` |
| Cicak/kadal, kecoa, ular | 10 per jenis (30) | idem |
| 19 hewan rumah/pekarangan lain (kelelawar, merpati, burung gereja, gagak, bebek, kalkun, beo, kelinci, possum, kura-kura, 9 jenis serangga) | 6 per jenis (114) | idem |
| Anjing | 20 / 130 | Kaggle 90 animals, `antobenedetti/animals`, `prasunroy/natural-images` |
| Bunga, buah, orang | 10 per kategori (30) | Kaggle `prasunroy/natural-images` |
| Maneki-neko, mainan kucing | 30 per kategori (60) | Wikimedia Commons |
| Boneka kucing | 24 / 24 | Wikimedia Commons |
| Hello Kitty, boneka, boneka hewan | 20 per kategori (60) | Wikimedia Commons |
| **Total** | **551 / 1.916** | |

Rincian per file ada di `reports/nonkucing_kurasi.csv`. Data luar hanya untuk objek yang realistis ada di
dalam rumah (tidak ada pesawat, mobil, gajah, dsb.); gambar Commons yang memuat kucing asli sudah dibuang.

### Bukti kurasi tidak menurunkan kualitas

Dua model dilatih dengan kucing latih yang sama; satu memakai seluruh 1.916 nonkucing, satu hanya hasil kurasi.

| Data uji | Seluruh nonkucing | Hasil kurasi |
|---|---|---|
| Kucing uji (diberi pakan) | 53/54 | 53/54 |
| Kucing uji hitam-putih | 51/54 | 54/54 |
| Kucing uji cetak/layar (ditahan) | 32/33 | 33/33 |
| `dataset_uji` (470, ditahan) | 470/470 | 469/470 |
| 1.365 gambar yang **tidak terpilih** kurasi (ditahan) | (ikut dilatih) | 1.362/1.365 |

Preprocessing yang dijalankan otomatis: orientasi EXIF dari foto HP diterapkan, resize 232 → crop tengah
224×224, normalisasi ImageNet. Gambar hasil kurasi diperkecil ke maksimal 512 px.

## Aturan keputusan

| Kondisi | Keputusan | Alasan (`alasan`) |
|---|---|---|
| label ≠ target mode (mis. `nonkucing`) | TAHAN | `terdeteksi nonkucing, bukan target (kucing)` |
| label = target, keyakinan < τ | TAHAN | `keyakinan 54,2% < τ 0,60` |
| label = target, keyakinan ≥ τ, stok cukup | BERI PAKAN | `keyakinan 99,9% ≥ τ 0,60` |
| BERI PAKAN tetapi stok < satu porsi | TAHAN | `stok pakan habis` |

τ = 0,6 disimpan di dalam model (`--tau` saat latih). Keyakinan ≥ 99,95% ditampilkan sebagai "> 99,9%".

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
| POST | `/api/devices/claim` | daftarkan kode alat dan pilih mode |
| GET | `/api/dashboard?code=…` | semua data dashboard satu alat |
| POST | `/api/predict` | klasifikasi foto + keputusan pakan (+ simulasi stok bila ada `code`) |
| POST | `/api/refill` | isi ulang tabung sampai penuh |
| GET | `/`, `/dashboard` | halaman web |

### GET /api/health

```bash
curl http://127.0.0.1:5000/api/health
```

```json
{"status": "ok", "model_siap": ["kucing"], "model": {"kucing": "MobileNetV2 + SVM"}}
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
| `code` | tidak | kode alat; bila ada, stok dikurangi dan kejadian dicatat |
| `mode` | tidak | `kucing` / `anjing`; default mode alat, atau `kucing` |

```bash
curl -X POST http://127.0.0.1:5000/api/predict \
     -F "file=@contoh_foto/kucing/Copy of cat6.jpg" -F "code=FEED-0001"
```

```json
{
  "label": "kucing",
  "confidence": 0.9994,
  "probabilitas": {"kucing": 0.9994, "nonkucing": 0.0006},
  "keputusan": "BERI PAKAN",
  "alasan": "keyakinan 99,9% ≥ τ 0,60",
  "pakan_keluar_g": 29.1,
  "stok": {"sisa_g": 1277.3, "kapasitas_g": 2000.0, "persen": 63.9, "rata_harian_g": 99.1,
           "perkiraan_habis_hari": 12.9, "perkiraan_habis_tanggal": "2026-11-13", "hari_data": 7},
  "waktu_ms": 88.3,
  "model": "MobileNetV2 + SVM",
  "mode": "kucing",
  "tau": 0.6,
  "kode": "FEED-0001",
  "simulasi": true
}
```

Tanpa `code`, hanya klasifikasi: `pakan_keluar_g` = 0 dan `stok` = `null`.

| Kode | Kapan |
|---|---|
| 400 | `file` tidak ada, file bukan gambar, atau `mode` tidak dikenal |
| 404 | `code` diisi tetapi tidak ditemukan |
| 409 | model untuk mode tersebut belum ada (mis. `anjing`) |
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
  "riwayat": [{"ts": "2026-11-01 22:21:39", "jenis": "tahan", "gram": 0.0, "label": "nonkucing",
               "confidence": 1.0, "thumb": "data:image/jpeg;base64,…"}, "… maks 20 …"],
  "simulasi": true
}
```

`jenis` riwayat: `beri`, `tahan`, `isi_ulang`. `notifikasi[].level`: `info`, `peringatan`, `mendesak`.
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

## Database (SQLite, `instance/feeder.db`)

| Tabel | Kolom |
|---|---|
| `devices` | `code` (PK), `mode`, `claimed`, `capacity_g`, `stock_g`, `portion_g` |
| `events` | `id`, `code`, `ts`, `kind` (`beri`/`tahan`/`isi_ulang`), `grams`, `label`, `confidence`, `thumbnail` |

## Ke alat asli (ESP32-CAM)

1. Jalankan server dengan `HOST=0.0.0.0 python app.py`.
2. Saat sensor mendeteksi hewan, ESP32 memotret dan mengirim `POST /api/predict` dengan `file` dan `code`.
3. Bila `keputusan == "BERI PAKAN"`, ESP32 menggerakkan servo; berat dari load cell bisa menggantikan nilai
   `pakan_keluar_g` simulasi.

## Keterbatasan

- Mode `anjing` belum punya model (`models/mobilenetv2_svm_anjing.joblib`), sehingga membalas 409.
- Contoh kucing cetak/layar dibuat sintetis; foto cetak/layar sungguhan dan boneka yang benar-benar ada di
  rumah sebaiknya ditambahkan ke `dataset/nonkucing`.
- Foto di `contoh_foto/kucing` diambil dari `dataset/` (ikut dilatih); foto lain di `contoh_foto/` berasal
  dari `dataset_uji/`.
- Data primer hanya kelas kucing (266). Untuk versi akhir, foto benda dan hewan di sekitar feeder yang
  dipotret sendiri sebaiknya menggantikan sebagian data sekunder.
- Tidak ada autentikasi; jangan dibuka ke internet publik tanpa menambahkan API key.
