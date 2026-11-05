"""Patterns mined from a device's own events. Fed to the LLM as context and used for rule-based advice.

Every number here is computed from database rows; nothing is estimated by the model.
"""
from collections import defaultdict
from datetime import date

from . import db, feeder
from .feeder import fmt, is_classification

SLOTS = (("pagi", 5, 10), ("siang", 10, 15), ("sore", 15, 19), ("malam", 19, 29))
LOW_CONFIDENCE = 0.80
WASTE_ALERT_PCT = 25.0
MIN_FEEDS_PER_SLOT = 3
CAMERA_SILENT_S = 120
MAX_PROACTIVE = 4
LEVEL_ORDER = {"mendesak": 0, "peringatan": 1, "saran": 2}


def slot_of(ts):
    hour = int(ts[11:13])
    hour = hour + 24 if hour < 5 else hour
    for name, start, end in SLOTS:
        if start <= hour < end:
            return name
    return "malam"


def mine(device, events=None):
    events = feeder.week_events(device) if events is None else events
    by_id = {e["id"]: e for e in events}
    has_waste = any(e["kind"] == "buang" for e in events)
    mode = device["mode"]

    slots = {name: {"n": 0, "fed": 0.0, "wasted": 0.0} for name, _, _ in SLOTS}
    for e in events:
        if e["kind"] == "beri" and e["grams"] > 0 and is_classification(e):
            slot = slots[slot_of(e["ts"])]
            slot["n"] += 1
            slot["fed"] += e["grams"]
    for e in events:
        parent = by_id.get(e["ref_id"]) if e["kind"] == "buang" else None
        if parent is not None and is_classification(parent):
            slots[slot_of(parent["ts"])]["wasted"] += e["grams"]
    for slot in slots.values():
        slot["pct"] = round(100 * slot["wasted"] / slot["fed"], 1) if slot["fed"] and has_waste else None

    sources = defaultdict(lambda: {"n": 0, "conf": []})
    for e in events:
        if is_classification(e):
            sources[e["source"]]["n"] += 1
            sources[e["source"]]["conf"].append(e["confidence"])
    source_stats = {s: {"n": v["n"], "conf": round(100 * sum(v["conf"]) / len(v["conf"]), 1)} for s, v in sources.items()}

    classified = [e for e in events if is_classification(e)]
    low = [e for e in classified if e["confidence"] < LOW_CONFIDENCE]
    held = [e for e in classified if e["kind"] == "tahan"]
    held_target = [e for e in held if e["label"] == mode]

    chart = feeder.daily_chart(events)
    fed_days = [d["keluar_g"] for d in chart if d["keluar_g"] > 0]
    trend = None
    if len(fed_days) >= 4:
        half = len(fed_days) // 2
        first, last = sum(fed_days[:half]) / half, sum(fed_days[-half:]) / half
        trend = round(100 * (last - first) / first, 1) if first else None

    return {"slots": slots, "sumber": source_stats, "total": len(classified), "rendah": len(low), "ditahan": len(held),
            "ditahan_target": len(held_target), "tren_pakan_pct": trend, "harian": chart}


def worst_slot(patterns):
    ranked = [(name, s) for name, s in patterns["slots"].items() if s["pct"] is not None and s["n"] >= MIN_FEEDS_PER_SLOT]
    return max(ranked, key=lambda item: item[1]["pct"], default=None)


def advice(device, events, patterns):
    """Advice with the numbers behind each line. Items: key (stable per day), level, teks."""
    out, today = [], date.today().isoformat()
    worst = worst_slot(patterns)
    if worst and worst[1]["pct"] >= WASTE_ALERT_PCT:
        name, s = worst
        eaten = (s["fed"] - s["wasted"]) / s["n"]
        out.append({"key": f"terbuang:{name}:{today}", "level": "saran",
                    "teks": f"Sisa terbuang terbanyak di waktu {name}: {fmt(s['pct'])}% dari {fmt(s['fed'])} g. "
                            f"Coba porsi {max(5, round(eaten / 5) * 5)} g."})
    if patterns["total"] and patterns["rendah"] / patterns["total"] >= 0.2:
        out.append({"key": f"conf:{today}", "level": "peringatan",
                    "teks": f"{patterns['rendah']} dari {patterns['total']} klasifikasi confidence di bawah 80%. "
                            "Cek posisi dan cahaya kamera."})
    if patterns["ditahan_target"]:
        out.append({"key": f"ditahan:{today}", "level": "saran",
                    "teks": f"{patterns['ditahan_target']} kali hewan sasaran ditahan karena confidence rendah."})
    if patterns["tren_pakan_pct"] is not None and abs(patterns["tren_pakan_pct"]) >= 15:
        arah = "naik" if patterns["tren_pakan_pct"] > 0 else "turun"
        out.append({"key": f"tren:{today}", "level": "saran",
                    "teks": f"Pakan keluar {arah} {fmt(abs(patterns['tren_pakan_pct']))}% dibanding awal minggu."})
    return out


def proactive(device, camera=None):
    """Messages Purr raises on its own, from live data. `camera` = {"umur_s", "n"} of the last ESP32-CAM frame."""
    events = feeder.week_events(device)
    stock = feeder.stock_summary(device)
    patterns = mine(device, events)
    items = []

    days = stock["perkiraan_habis_hari"]
    if stock["persen"] < 10:
        items.append({"key": "stok:10", "level": "mendesak",
                      "teks": f"Sisa pakan tinggal {fmt(stock['sisa_g'])} g ({fmt(stock['persen'])}%). Isi ulang tabung."})
    elif stock["persen"] < 20:
        items.append({"key": "stok:20", "level": "peringatan",
                      "teks": f"Sisa pakan {fmt(stock['sisa_g'])} g ({fmt(stock['persen'])}%). Siapkan isi ulang."})
    elif days is not None and days <= 3:
        items.append({"key": f"habis:{int(days)}", "level": "peringatan",
                      "teks": f"Pakan habis dalam ±{days:.0f} hari. Sisa {fmt(stock['sisa_g'])} g."})

    if camera is not None and camera["umur_s"] > CAMERA_SILENT_S:
        items.append({"key": f"kamera:{camera['n']}", "level": "peringatan",
                      "teks": f"ESP32-CAM tidak mengirim gambar sejak {camera['umur_s'] / 60:.0f} menit lalu. Cek daya dan Wi-Fi alat."})

    items += advice(device, events, patterns)
    items.sort(key=lambda i: LEVEL_ORDER[i["level"]])
    return [{"id": i["key"], "level": i["level"], "teks": i["teks"]} for i in items[:MAX_PROACTIVE]]


def context(device, events=None):
    """Plain-text DATA ALAT block for the LLM prompt."""
    events = feeder.week_events(device) if events is None else events
    mode, hewan = device["mode"], feeder.KELAS[device["mode"]]
    stock = feeder.stock_summary(device)
    total = feeder.totals(events, mode)
    patterns = mine(device, events)
    lines = [f"Alat {device['code']}, untuk {hewan}. Porsi {fmt(device['portion_g'])} g. Data 7 hari terakhir.",
             f"Sisa pakan {fmt(stock['sisa_g'])} g ({fmt(stock['persen'])}% dari {fmt(stock['kapasitas_g'])} g)."]
    if stock["perkiraan_habis_hari"] is not None:
        lines.append(f"Perkiraan habis {fmt(stock['perkiraan_habis_hari'])} hari (rata-rata {fmt(stock['rata_harian_g'])} g per hari).")
    else:
        lines.append("Perkiraan habis belum bisa dihitung (butuh minimal 3 hari data).")
    lines.append(f"Klasifikasi: {total['total']} total, {total['hewan']} {hewan}, {total['bukan']} Bukan Keduanya.")
    if total["rasio_terbuang"] is not None:
        lines.append(f"Pakan keluar {fmt(total['pakan_keluar_g'])} g, terbuang {fmt(total['pakan_terbuang_g'])} g (rasio {fmt(total['rasio_terbuang'])}%).")
    else:
        lines.append(f"Pakan keluar {fmt(total['pakan_keluar_g'])} g. Data pakan terbuang belum ada (alat belum melaporkan sisa), jangan menyimpulkan apa pun soal terbuang.")

    lines.append("POLA:")
    for name, s in patterns["slots"].items():
        if s["n"]:
            waste = f", terbuang {fmt(s['pct'])}%" if s["pct"] is not None else ""
            lines.append(f"- {name}: {s['n']} kali beri, rata-rata {fmt(s['fed'] / s['n'])} g{waste}")
    for source, s in patterns["sumber"].items():
        lines.append(f"- sumber {feeder.SUMBER[source]}: {s['n']} klasifikasi, confidence rata-rata {fmt(s['conf'])}%")
    lines.append(f"- confidence di bawah 80%: {patterns['rendah']} dari {patterns['total']}")
    lines.append(f"- ditahan: {patterns['ditahan']} (hewan sasaran ikut ditahan: {patterns['ditahan_target']})")
    if patterns["tren_pakan_pct"] is not None:
        lines.append(f"- tren pakan keluar paruh akhir vs awal minggu: {fmt(patterns['tren_pakan_pct'])}%")

    lines.append("PER HARI (keluar g, terbuang g, confidence %):")
    for d in patterns["harian"]:
        lines.append(f"- {d['tanggal']}: {fmt(d['keluar_g'])}, {fmt(d['terbuang_g'])}, "
                     f"{fmt(d['confidence']) if d['confidence'] is not None else '-'}")

    suggestions = advice(device, events, patterns)
    lines.append("SARAN OTOMATIS:" + ("" if suggestions else " belum ada pola yang perlu ditindak."))
    lines += [f"- {s['teks']}" for s in suggestions]

    last = feeder.latest_label(device)
    if last is not None:
        lines.append(f"Klasifikasi terakhir: {feeder.kelas_of(last['label'])}, {fmt(100 * last['confidence'])}%, "
                     f"{last['ts'][11:16]}, {feeder.SUMBER[last['source']]}, {feeder.action_text(last)}.")
    return "\n".join(lines)
