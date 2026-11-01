import base64
import io
import random
from datetime import date, timedelta

from flask import current_app

from . import db
from .decision import Decision
from .features import load_rgb

HISTORY_DAYS = 7
MIN_DAYS_FOR_FORECAST = 3
THUMBNAIL_SIZE = (96, 96)


def device_json(device, registry):
    return {
        "code": device["code"],
        "mode": device["mode"],
        "kapasitas_g": device["capacity_g"],
        "sisa_g": round(device["stock_g"], 1),
        "porsi_g": device["portion_g"],
        "model_tersedia": registry.available(device["mode"]),
    }


def stock_summary(device):
    """Remaining stock and forecast: stock / average daily feed over the last 7 days (days without feeding ignored)."""
    today = date.today()
    rows = db.daily_totals(device["code"], today - timedelta(days=HISTORY_DAYS))
    daily = [r["grams"] for r in rows if r["kind"] == "beri" and r["day"] < today.isoformat() and r["grams"] > 0]

    summary = {
        "sisa_g": round(device["stock_g"], 1),
        "kapasitas_g": device["capacity_g"],
        "persen": round(100 * device["stock_g"] / device["capacity_g"], 1),
        "rata_harian_g": None,
        "perkiraan_habis_hari": None,
        "perkiraan_habis_tanggal": None,
        "hari_data": len(daily),
    }
    if len(daily) >= MIN_DAYS_FOR_FORECAST:
        average = sum(daily) / len(daily)
        days_left = device["stock_g"] / average
        summary.update(rata_harian_g=round(average, 1), perkiraan_habis_hari=round(days_left, 1),
                       perkiraan_habis_tanggal=(today + timedelta(days=int(days_left))).isoformat())
    return summary


def notifications(stock):
    notes = []
    days_left = stock["perkiraan_habis_hari"]
    if stock["persen"] < 10:
        notes.append({"level": "mendesak", "pesan": "Stok pakan di bawah 10%. Segera isi ulang tabung."})
    if days_left is None:
        if stock["persen"] < 20:
            notes.append({"level": "peringatan", "pesan": "Stok pakan di bawah 20%."})
        notes.append({"level": "info", "pesan": "Prediksi hari habis aktif setelah 3 hari data pemberian pakan."})
    elif days_left <= 1:
        notes.append({"level": "mendesak", "pesan": "Pakan diperkirakan habis dalam ±1 hari."})
    elif days_left <= 3:
        notes.append({"level": "peringatan",
                      "pesan": f"Pakan diperkirakan habis dalam ±{days_left:.0f} hari ({stock['perkiraan_habis_tanggal']})."})
    return notes


def daily_chart(code):
    today = date.today()
    start = today - timedelta(days=HISTORY_DAYS - 1)
    chart = {(start + timedelta(days=i)).isoformat(): {"pakan_g": 0.0, "beri": 0, "tahan": 0}
             for i in range(HISTORY_DAYS)}
    for row in db.daily_totals(code, start):
        day = chart.get(row["day"])
        if day is None:
            continue
        if row["kind"] == "beri":
            day.update(pakan_g=round(row["grams"], 1), beri=row["n"])
        else:
            day["tahan"] = row["n"]
    return [{"tanggal": day, **values} for day, values in chart.items()]


def history(code):
    return [{"ts": r["ts"], "jenis": r["kind"], "gram": r["grams"], "label": r["label"],
             "confidence": r["confidence"], "thumb": r["thumbnail"]} for r in db.recent_events(code)]


def dashboard(device, registry):
    stock = stock_summary(device)
    chart = daily_chart(device["code"])
    return {
        "device": device_json(device, registry),
        "stok": stock,
        "hari_ini": {k: v for k, v in chart[-1].items() if k != "tanggal"},
        "notifikasi": notifications(stock),
        "grafik": chart,
        "riwayat": history(device["code"]),
        "simulasi": True,
    }


def thumbnail(image_bytes):
    image = load_rgb(io.BytesIO(image_bytes))
    image.thumbnail(THUMBNAIL_SIZE)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def dispense(device, decision, prediction, image_bytes):
    """Simulated feeder: release one portion (with load-cell noise) or hold, and log the event."""
    if decision.feed and device["stock_g"] < device["portion_g"]:
        decision = Decision(False, "stok pakan habis")

    grams = 0.0
    if decision.feed:
        noise = current_app.config["PORTION_NOISE_G"]
        grams = min(device["stock_g"], round(device["portion_g"] + random.uniform(-noise, noise), 1))

    with db.get_db() as conn:
        if grams:
            conn.execute("UPDATE devices SET stock_g = stock_g - ? WHERE code = ?", (grams, device["code"]))
        db.record_event(conn, device["code"], "beri" if grams else "tahan", grams,
                        prediction.label, prediction.confidence, thumbnail(image_bytes))
    return decision, grams


def refill(device):
    added = round(device["capacity_g"] - device["stock_g"], 1)
    with db.get_db() as conn:
        conn.execute("UPDATE devices SET stock_g = capacity_g WHERE code = ?", (device["code"],))
        db.record_event(conn, device["code"], "isi_ulang", added)
    return added
