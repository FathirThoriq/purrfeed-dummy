# models/

Tempat menaruh hasil training. Satu hewan satu file:

| File | Untuk |
|---|---|
| `kucing.joblib` | alat mode Kucing |
| `anjing.joblib` | alat mode Anjing |

Cara pasang: salin file hasil Jupyter ke sini, lalu **restart server**. Buka `/api/health` untuk memastikan.
`model_siap` berisi hewan yang berhasil dimuat. `model_ditolak` berisi alasan bila file ditolak.

## Isi file (joblib, dictionary)

| Kunci | Isi |
|---|---|
| `classifier` | pipeline/model dengan `predict_proba` dan `classes_`, masukan vektor 1280 fitur |
| `target` | kelas hewan yang diberi pakan, sama dengan nama file (`kucing` atau `anjing`) |
| `tau` | ambang confidence 0 sampai 1 (mis. 0.6) |
| `algorithm` | nama algoritma (hanya untuk catatan, tidak tampil di UI) |
| `feature_version` | harus `mobilenetv2-tf-imagenet-seg127-1280` (lihat `purrfeed/features.py`) |
| `trained_at` | opsional, waktu training |

Model boleh 3 kelas (`anjing`, `kucing`, `other`): file `kucing.joblib` dan `anjing.joblib` boleh berisi classifier yang sama,
yang beda hanya `target`. Kelas selain `target` (mis. `other`) ditahan dan tampil sebagai "Bukan Keduanya".
Fitur dibuat server: foto -> segmentasi rembg -> latar abu-abu 127 -> 224x224 -> MobileNetV2 TensorFlow -> 1280.
Model harus dilatih di atas fitur yang sama (notebook Google Colab).

Disimpan dengan: `joblib.dump({...}, "kucing.joblib")`. Pakai versi scikit-learn yang sama dengan `.venv` web.
