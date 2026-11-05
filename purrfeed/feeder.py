import base64
import io
import random
from datetime import date, datetime, timedelta

from flask import current_app

from . import db
from .decision import Decision
from .features import load_rgb

HISTORY_DAYS = 7
MIN_DAYS_FOR_FORECAST = 3
THUMBNAIL_SIZE = (96, 96)
PORTION_STEP_G = 5

KELAS = {"kucing": "Kucing", "anjing": "Anjing"}
BUKAN = "Bukan Keduanya"
SUMBER = {"upload": "Upload", "esp32cam": "ESP32-CAM", "servo": "Servo", "sistem": "Sistem"}
IKON_KELAS = {"Kucing": "cat", "Anjing": "dog", BUKAN: "ban"}


def kelas_of(label):
    """Three display classes. Any label that is not a target animal (e.g. 'other', 'nonkucing') is 'Bukan Keduanya'."""
    return KELAS.get(label, BUKAN) if label else None


def device_json(device, registry):
    return {
        "code": device["code"],
        "mode": device["mode"],
        "hewan": KELAS[device["mode"]],
        "kapasitas_g": device["capacity_g"],
        "sisa_g": round(device["stock_g"], 1),
        "porsi_g": device["portion_g"],
        "model_tersedia": registry.available(device["mode"]),
        "model_masalah": registry.rejected.get(device["mode"]),
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
        notes.append({"level": "mendesak", "pesan": "Sisa pakan di bawah 10%."})
    elif stock["persen"] < 20:
        notes.append({"level": "peringatan", "pesan": "Sisa pakan di bawah 20%."})
    if days_left is not None and days_left <= 1:
        notes.append({"level": "mendesak", "pesan": "Pakan habis dalam ±1 hari."})
    elif days_left is not None and days_left <= 3:
        notes.append({"level": "peringatan", "pesan": f"Pakan habis dalam ±{days_left:.0f} hari."})
    return notes


def window_start():
    return date.today() - timedelta(days=HISTORY_DAYS - 1)


def week_events(device):
    return db.events_since(device["code"], device["mode"], window_start())


def is_classification(event):
    return event["kind"] in ("beri", "tahan") and event["confidence"] is not None


def totals(events, mode):
    classified = [e for e in events if is_classification(e)]
    animals = sum(1 for e in classified if e["label"] == mode)
    fed = sum(e["grams"] for e in events if e["kind"] == "beri")
    waste_events = [e for e in events if e["kind"] == "buang"]
    disposed = sum(e["grams"] for e in waste_events)
    return {
        "total": len(classified),
        "hewan": animals,
        "bukan": len(classified) - animals,
        "pakan_keluar_g": round(fed, 1),
        "pakan_terbuang_g": round(disposed, 1),
        "rasio_terbuang": round(100 * disposed / fed, 1) if fed and waste_events else None,
    }


def daily_chart(events):
    start = window_start()
    days = {(start + timedelta(days=i)).isoformat(): {"keluar_g": 0.0, "terbuang_g": 0.0, "conf": []}
            for i in range(HISTORY_DAYS)}
    for e in events:
        day = days.get(e["ts"][:10])
        if day is None:
            continue
        if e["kind"] == "beri":
            day["keluar_g"] += e["grams"]
        elif e["kind"] == "buang":
            day["terbuang_g"] += e["grams"]
        if is_classification(e):
            day["conf"].append(e["confidence"])
    return [{"tanggal": d, "keluar_g": round(v["keluar_g"], 1), "terbuang_g": round(v["terbuang_g"], 1),
             "confidence": round(100 * sum(v["conf"]) / len(v["conf"]), 1) if v["conf"] else None}
            for d, v in days.items()]


def action_text(event):
    grams = f"{event['grams']:.1f}".replace(".", ",")
    return {
        "beri": f"Beri pakan {grams} g",
        "tahan": "Ditahan",
        "buang": f"Buang sisa {grams} g",
        "isi_ulang": f"Isi ulang {grams} g",
    }[event["kind"]]


def history_item(event):
    kelas = kelas_of(event["label"]) if is_classification(event) else None
    if event["kind"] == "buang":
        ikon = "utensils"
    elif event["kind"] == "isi_ulang":
        ikon = "package"
    else:
        ikon = IKON_KELAS.get(kelas, "utensils")
    return {"id": event["id"], "ts": event["ts"], "jenis": event["kind"], "sumber": event["source"],
            "sumber_label": SUMBER[event["source"]], "kelas": kelas, "ikon": ikon,
            "confidence": event["confidence"], "waktu_ms": event["elapsed_ms"], "tindakan": action_text(event),
            "gram": event["grams"], "thumb": event["thumbnail"]}


def history(device, events=None):
    events = week_events(device) if events is None else events
    return [history_item(e) for e in events]


def suggestions(device, events, stock):
    """Short advice cards, each derived from numbers shown on the dashboard."""
    mode = device["mode"]
    total = totals(events, mode)
    cards = []

    feeds = [e for e in events if e["kind"] == "beri" and e["grams"] > 0 and is_classification(e)]
    if total["rasio_terbuang"] is not None and feeds:
        eaten = (total["pakan_keluar_g"] - total["pakan_terbuang_g"]) / len(feeds)
        portion = max(PORTION_STEP_G, round(eaten / PORTION_STEP_G) * PORTION_STEP_G)
        text = f"Rasio terbuang {fmt(total['rasio_terbuang'])}%. Coba porsi {portion} g."
    else:
        text = "Belum ada data pakan terbuang."
    cards.append({"ikon": "trending-up", "teks": text, "tanya": "Berapa rasio pakan terbuang?"})

    if stock["perkiraan_habis_hari"] is not None:
        text = f"Sisa pakan {fmt(stock['sisa_g'])} g, habis ±{stock['perkiraan_habis_hari']:.0f} hari."
    else:
        text = f"Sisa pakan {fmt(stock['sisa_g'])} g."
    cards.append({"ikon": "package", "teks": text, "tanya": "Berapa sisa pakan?"})

    confidences = [e["confidence"] for e in events if is_classification(e)]
    if confidences:
        average = 100 * sum(confidences) / len(confidences)
        text = f"Confidence rata-rata {fmt(average)}%."
        if average < 90:
            text += " Cek posisi kamera."
    else:
        text = "Belum ada hasil klasifikasi."
    cards.append({"ikon": "lightbulb", "teks": text, "tanya": "Bagaimana confidence kamera?"})
    return cards


def fmt(value, digits=1):
    return f"{value:.{digits}f}".replace(".", ",").removesuffix(",0")


def dashboard(device, registry):
    events = week_events(device)
    stock = stock_summary(device)
    return {
        "device": device_json(device, registry),
        "stok": stock,
        "ringkasan": totals(events, device["mode"]),
        "notifikasi": notifications(stock),
        "grafik": daily_chart(events),
        "riwayat": history(device, events),
        "saran": suggestions(device, events, stock),
        "simulasi": True,
    }


def thumbnail(image_bytes):
    image = load_rgb(io.BytesIO(image_bytes))
    image.thumbnail(THUMBNAIL_SIZE)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=70)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def portion_grams(device):
    noise = current_app.config["PORTION_NOISE_G"]
    return min(device["stock_g"], round(device["portion_g"] + random.uniform(-noise, noise), 1))


def dispense(device, decision, prediction, image_bytes, source="esp32cam"):
    """Simulated feeder: release one portion (with load-cell noise) or hold, and log the event."""
    if decision.feed and device["stock_g"] < device["portion_g"]:
        decision = Decision(False, "stok pakan habis")

    grams = portion_grams(device) if decision.feed else 0.0
    with db.get_db() as conn:
        if grams:
            conn.execute("UPDATE devices SET stock_g = stock_g - ? WHERE code = ?", (grams, device["code"]))
        db.record_event(conn, device["code"], "beri" if grams else "tahan", grams, prediction.label,
                        prediction.confidence, thumbnail(image_bytes), device["mode"], source, prediction.elapsed_ms)
    return decision, grams


def refill(device):
    added = round(device["capacity_g"] - device["stock_g"], 1)
    with db.get_db() as conn:
        conn.execute("UPDATE devices SET stock_g = capacity_g WHERE code = ?", (device["code"],))
        db.record_event(conn, device["code"], "isi_ulang", added, source="sistem")
    return added


def latest_label(device):
    for event in week_events(device):
        if is_classification(event):
            return event
    return None


def export_rows(device):
    """Rows for the 7-day export, oldest first, active animal mode only."""
    rows = []
    for item in reversed(history(device)):
        if item["jenis"] == "isi_ulang":
            continue
        rows.append([item["ts"], item["sumber_label"], item["kelas"] or "-",
                     fmt(100 * item["confidence"]) + "%" if item["confidence"] is not None else "-",
                     f"{item['waktu_ms']:.0f}" if item["waktu_ms"] is not None else "-",
                     item["tindakan"]])
    return ["Waktu", "Sumber", "Kelas", "Confidence", "Waktu proses (ms)", "Tindakan servo"], rows


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M")
