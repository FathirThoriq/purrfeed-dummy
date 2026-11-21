import csv
import io
import re
import time
import os
import json
import paho.mqtt.publish as publish
import hmac

from functools import wraps
from flask import Blueprint, Response, current_app, jsonify, request
from PIL import Image

from . import assistant, db, feeder, insights
from .decision import decide
from .serial_feeder import trigger_feed_async

pages = Blueprint("pages", __name__)
api = Blueprint("api", __name__, url_prefix="/api")
LATEST = {}   # kode alat -> frame + hasil terakhir dari ESP32-CAM (memori)
SERVO_COMMANDS = {}   # kode alat -> perintah servo untuk ESP32 via HTTP
LATEST_MOTION = {}    # kode alat -> data deteksi objek HC-SR04 terakhir
MOTION_COUNTER = 0

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        expected_key = os.getenv("API_SECRET_KEY", "").strip()
        if not expected_key:
            return jsonify({"error": "Server API_SECRET_KEY belum dikonfigurasi."}), 500

        # 1. Jalur resmi IoT / camera_worker.py via Header X-API-Key
        provided_key = request.headers.get("X-API-Key", "").strip()
        if provided_key and hmac.compare_digest(provided_key, expected_key):
            return f(*args, **kwargs)

        # 2. Jalur halaman web dashboard sendiri (tanpa mengekspos secret key ke browser)
        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")
        same_origin = (
            (origin and origin.split("://")[-1].split("/")[0] == request.host)
            or (referer and referer.split("://")[-1].split("/")[0] == request.host)
        )
        if same_origin and request.form.get("source") in ("upload", "webcam"):
            return f(*args, **kwargs)

        return jsonify({"error": "Unauthorized: API Key tidak valid."}), 401
    return decorated_function

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
        "kotak": prediction.box,
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
        "servo_terpicu": bool(decision.feed),
    }


@api.post("/motion")
def motion():
    """Laporan deteksi objek mendekat dari sensor ESP32."""
    global MOTION_COUNTER
    body = request.get_json(silent=True) or {}
    code = normalize_code(body.get("code")) or "FEED-0001"
    jarak = body.get("jarak_cm")
    try:
        jarak_cm = round(float(jarak), 1) if jarak is not None else None
    except (ValueError, TypeError):
        jarak_cm = None
    MOTION_COUNTER += 1
    info = {
        "id": MOTION_COUNTER,
        "jarak_cm": jarak_cm,
        "ts": time.time(),
        "code": code,
    }
    LATEST_MOTION[code] = info
    LATEST_MOTION["_any"] = info
    print(f"[MOTION] Objek mendekat terdeteksi pada alat {code}! Jarak: {jarak_cm} cm (Event #{MOTION_COUNTER})")
    return jsonify({"capture": True, "code": code, "motion_id": MOTION_COUNTER, "jarak_cm": jarak_cm})


@api.get("/motion")
def get_motion():
    """Status gerakan terakhir (untuk polling web dashboard)."""
    code = normalize_code(request.args.get("code"))
    info = LATEST_MOTION.get(code) or LATEST_MOTION.get("_any")
    if not info:
        return jsonify({"ada": False})
    umur = time.time() - info["ts"]
    return jsonify({
        "ada": umur <= 25.0,
        "id": info["id"],
        "jarak_cm": info["jarak_cm"],
        "umur_s": round(umur, 1),
        "code": info["code"],
    })


@api.get("/command")
def get_command():
    """Polling perintah servo untuk ESP32 (HTTP polling fallback)."""
    code = normalize_code(request.args.get("code"))
    cmd = SERVO_COMMANDS.get(code)
    return jsonify({"servo": cmd})


@api.post("/servo")
def ack_servo():
    """Konfirmasi eksekusi servo dari ESP32."""
    body = request.get_json(silent=True) or {}
    code = normalize_code(body.get("code"))
    SERVO_COMMANDS.pop(code, None)
    return jsonify({"status": "ok", "code": code})

def publish_feed_mqtt(code: str, grams: float):
    broker_host = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
    broker_port = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    mqtt_user = os.getenv("MQTT_USER")
    mqtt_pass = os.getenv("MQTT_PASS")

    auth = {"username": mqtt_user, "password": mqtt_pass} if mqtt_user else None
    topic = f"purrfeed/{code}/command"
    payload = json.dumps({"perintah": "FEED", "pakan_g": grams})

    try:
        publish.single(
            topic,
            payload=payload,
            hostname=broker_host,
            port=broker_port,
            auth=auth,
        )
    except Exception as e:
        current_app.logger.warning(f"Gagal publish MQTT ke {topic}: {e}")

@api.post("/predict")
@require_api_key
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
    if source not in ("esp32cam", "upload", "webcam"):
        return error("source harus 'esp32cam', 'upload', atau 'webcam'.", 400)

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

    # Jika keputusan BERI PAKAN (kucing terdeteksi), gerakkan servo via COM12 & antrean HTTP
    if decision.feed:
        if current_app.config.get("SERIAL_ENABLED", True):
            serial_port = current_app.config.get("SERIAL_PORT", "COM12")
            baudrate = current_app.config.get("SERIAL_BAUDRATE", 115200)
            trigger_feed_async(serial_port, baudrate)
        if code:
            SERVO_COMMANDS[code] = {"perintah": "buka", "pakan_g": grams or 30.0, "ts": time.time()}
            publish_feed_mqtt(code, grams or 30.0)

    result = result_json(prediction, decision, grams, stock, mode, code, source)
    if code and source == "esp32cam":
        LATEST[code] = {"jpg": image_bytes, "hasil": result, "t": time.time(),
                        "n": LATEST.get(code, {}).get("n", 0) + 1}
    return jsonify(result)


@api.get("/latest")
def latest():
    code = normalize_code(request.args.get("code"))
    item = LATEST.get(code)
    m = LATEST_MOTION.get(code) or LATEST_MOTION.get("_any")
    motion_info = None
    if m:
        umur = time.time() - m["ts"]
        if umur <= 25.0:
            motion_info = {
                "id": m["id"],
                "jarak_cm": m["jarak_cm"],
                "umur_s": round(umur, 1),
                "code": m["code"],
            }
    res: dict[str, object] = {"motion": motion_info}
    if item is None:
        res["ada"] = False
        return jsonify(res)
    res.update({"ada": True, "umur_s": round(time.time() - item["t"], 1), "n": item["n"], "hasil": item["hasil"]})
    return jsonify(res)


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
