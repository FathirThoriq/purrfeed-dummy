import io

from flask import Blueprint, current_app, jsonify, request
from PIL import Image

from . import db, feeder
from .decision import decide

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")


def registry():
    return current_app.extensions["models"]


def error(message, status):
    return jsonify({"error": message}), status


def normalize_code(value):
    return str(value or "").strip().upper()


def is_image(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        return True
    except Exception:
        return False


@pages.get("/")
def index():
    return current_app.send_static_file("index.html")


@pages.get("/dashboard")
def dashboard_page():
    return current_app.send_static_file("dashboard.html")


@api.app_errorhandler(413)
def too_large(_error):
    return error("Ukuran file maksimal 8 MB.", 413)


@api.get("/health")
def health():
    models = registry()
    return jsonify({"status": "ok", "model_siap": sorted(models.bundles), "model": models.describe()})


@api.post("/devices/claim")
def claim_device():
    body = request.get_json(silent=True) or {}
    code = normalize_code(body.get("code"))
    mode = body.get("mode", "kucing")
    if mode not in registry().modes:
        return error(f"Mode harus salah satu dari {registry().modes}.", 400)
    if db.get_device(code) is None:
        return error("Kode alat tidak ditemukan.", 404)
    db.claim_device(code, mode)
    return jsonify({"device": feeder.device_json(db.get_device(code), registry())})


@api.get("/dashboard")
def dashboard():
    device = db.get_device(normalize_code(request.args.get("code")))
    if device is None:
        return error("Kode alat tidak ditemukan.", 404)
    return jsonify(feeder.dashboard(device, registry()))


@api.post("/predict")
def predict():
    upload = request.files.get("file")
    if upload is None:
        return error("Field 'file' (gambar) wajib diisi.", 400)
    image_bytes = upload.read()
    if not is_image(image_bytes):
        return error("File bukan gambar yang valid.", 400)

    code = normalize_code(request.form.get("code"))
    device = db.get_device(code) if code else None
    if code and device is None:
        return error("Kode alat tidak ditemukan.", 404)

    mode = request.form.get("mode") or (device["mode"] if device else "kucing")
    if mode not in registry().modes:
        return error(f"Mode harus salah satu dari {registry().modes}.", 400)
    if not registry().available(mode):
        return error(f"Model untuk mode '{mode}' belum tersedia. Latih modelnya terlebih dahulu.", 409)

    prediction = registry().predict(mode, image_bytes)
    decision = decide(prediction)
    grams, stock = 0.0, None
    if device is not None:
        decision, grams = feeder.dispense(device, decision, prediction, image_bytes)
        stock = feeder.stock_summary(db.get_device(code))

    return jsonify({
        "label": prediction.label,
        "confidence": prediction.confidence,
        "probabilitas": prediction.probabilities,
        "keputusan": decision.label,
        "alasan": decision.reason,
        "pakan_keluar_g": grams,
        "stok": stock,
        "waktu_ms": prediction.elapsed_ms,
        "model": prediction.algorithm,
        "mode": mode,
        "tau": prediction.tau,
        "kode": code or None,
        "simulasi": True,
    })


@api.post("/refill")
def refill():
    body = request.get_json(silent=True) or {}
    device = db.get_device(normalize_code(body.get("code")))
    if device is None:
        return error("Kode alat tidak ditemukan.", 404)
    added = feeder.refill(device)
    return jsonify({"ditambahkan_g": added, "stok": feeder.stock_summary(db.get_device(device["code"]))})
