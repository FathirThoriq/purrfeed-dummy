import csv
import io
import re
import time

from flask import Blueprint, Response, current_app, jsonify, request
from PIL import Image

from . import assistant, db, feeder, insights
from .decision import decide

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")
LATEST = {}   # kode alat -> frame + hasil terakhir dari ESP32-CAM (memori)


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


PROVISIONED_CODE = re.compile(r"PF-[2-9A-HJ-NP-Z]{5}")   # dibuat firmware provisioning ESP32-CAM


def device_for(code, mode="kucing"):
    """Registered device, or a provisioned PF-XXXXX device auto-registered on first contact."""
    device = db.get_device(code)
    if device is None and PROVISIONED_CODE.fullmatch(code):
        device = db.register_device(code, mode if mode in registry().modes else "kucing")
    return device


def device_or_error(code):
    device = db.get_device(normalize_code(code))
    if device is None:
        return None, error("ID alat tidak ditemukan.", 404)
    return device, None


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
    return jsonify({"status": "ok", "model_siap": sorted(models.bundles), "model": models.describe(),
                    "model_ditolak": models.rejected})


@api.post("/devices/claim")
def claim_device():
    body = request.get_json(silent=True) or {}
    code = normalize_code(body.get("code"))
    mode = body.get("mode", "kucing")
    if mode not in registry().modes:
        return error(f"Mode harus salah satu dari {registry().modes}.", 400)
    if device_for(code, mode) is None:
        return error("ID alat tidak ditemukan.", 404)
    db.claim_device(code, mode)
    return jsonify({"device": feeder.device_json(db.get_device(code), registry())})


@api.get("/dashboard")
def dashboard():
    device, failure = device_or_error(request.args.get("code"))
    if failure:
        return failure
    return jsonify(feeder.dashboard(device, registry()))


def result_json(prediction, decision, grams, stock, mode, code, source):
    return {
        "label": prediction.label,
        "kelas": feeder.kelas_of(prediction.label),
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
        "sumber": source,
        "jam": time.strftime("%H:%M:%S"),
        "simulasi": True,
    }


@api.post("/predict")
def predict():
    """Used by the ESP32-CAM (default source) and by the dashboard upload tab (source=upload)."""
    upload = request.files.get("file")
    if upload is None:
        return error("Field 'file' (gambar) wajib diisi.", 400)
    image_bytes = upload.read()
    if not is_image(image_bytes):
        return error("File bukan gambar yang valid.", 400)

    code = normalize_code(request.form.get("code"))
    device = device_for(code, request.form.get("mode", "kucing")) if code else None
    if code and device is None:
        return error("ID alat tidak ditemukan.", 404)

    source = request.form.get("source", "esp32cam")
    if source not in ("esp32cam", "upload"):
        return error("source harus 'esp32cam' atau 'upload'.", 400)

    mode = request.form.get("mode") or (device["mode"] if device else "kucing")
    if mode not in registry().modes:
        return error(f"Mode harus salah satu dari {registry().modes}.", 400)
    if not registry().available(mode):
        return error(f"Model untuk hewan '{mode}' belum tersedia.", 409)

    prediction = registry().predict(mode, image_bytes)
    decision = decide(prediction)
    grams, stock = 0.0, None
    if device is not None:
        decision, grams = feeder.dispense(device, decision, prediction, image_bytes, source)
        stock = feeder.stock_summary(db.get_device(code))

    result = result_json(prediction, decision, grams, stock, mode, code, source)
    if code and source == "esp32cam":
        LATEST[code] = {"jpg": image_bytes, "hasil": result, "t": time.time(),
                        "n": LATEST.get(code, {}).get("n", 0) + 1}
    return jsonify(result)


@api.get("/latest")
def latest():
    code = normalize_code(request.args.get("code"))
    item = LATEST.get(code)
    if item is None:
        return jsonify({"ada": False})
    return jsonify({"ada": True, "umur_s": round(time.time() - item["t"], 1), "n": item["n"], "hasil": item["hasil"]})


@api.get("/latest.jpg")
def latest_jpg():
    item = LATEST.get(normalize_code(request.args.get("code")))
    if item is None:
        return error("Belum ada frame dari ESP32-CAM.", 404)
    return Response(item["jpg"], mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@api.post("/refill")
def refill():
    body = request.get_json(silent=True) or {}
    device, failure = device_or_error(body.get("code"))
    if failure:
        return failure
    added = feeder.refill(device)
    return jsonify({"ditambahkan_g": added, "stok": feeder.stock_summary(db.get_device(device["code"]))})


@api.post("/chat")
def chat():
    body = request.get_json(silent=True) or {}
    device, failure = device_or_error(body.get("code"))
    if failure:
        return failure
    text = str(body.get("pesan") or "").strip()[:300]
    if not text:
        return error("Pesan kosong.", 400)
    return jsonify(assistant.reply(device, text, body.get("riwayat")))


@api.get("/proaktif")
def proactive():
    """Messages Purr raises without being asked; the browser shows a badge and tracks which ones were read."""
    device, failure = device_or_error(request.args.get("code"))
    if failure:
        return failure
    item = LATEST.get(device["code"])
    camera = {"umur_s": time.time() - item["t"], "n": item["n"]} if item else None
    return jsonify({"pesan": insights.proactive(device, camera)})


@api.get("/export")
def export():
    device, failure = device_or_error(request.args.get("code"))
    if failure:
        return failure
    kind = request.args.get("format", "csv")
    header, rows = feeder.export_rows(device)
    name = f"riwayat-purrfeed-7-hari-{device['mode']}"

    if kind == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
        body, mimetype, ext = "\ufeff" + buffer.getvalue(), "text/csv; charset=utf-8", "csv"
    elif kind == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font
        book = Workbook()
        sheet = book.active
        sheet.title = "Riwayat 7 hari"
        sheet.append(header)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(row)
        for column, width in zip("ABCDEF", (20, 12, 16, 12, 18, 22)):
            sheet.column_dimensions[column].width = width
        buffer = io.BytesIO()
        book.save(buffer)
        body = buffer.getvalue()
        mimetype, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    else:
        return error("format harus 'csv' atau 'xlsx'.", 400)
    return Response(body, mimetype=mimetype,
                    headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"', "Cache-Control": "no-store"})
