import re

from flask import current_app

from . import feeder, insights, llm
from .feeder import fmt, kelas_of

MAX_TURNS = 6
CLAIMS_DONE = re.compile(r"\\b(sudah|telah|udah)\\s+(ku|aku\\s+)?(buang|beri|keluarkan|kasih)|\\b(dibuang|diberi|dikeluarkan)\\b", re.I)
CANNOT_ACT = "Aku cuma bisa membaca data dan memberi saran, tidak bisa menggerakkan servo."
FORMAT_RULES = """FORMAT KELUARAN (wajib): balas dengan satu objek JSON saja, tanpa teks lain, tanpa blok kode:
{"teks": "jawabanmu untuk pengguna"}"""

FALLBACK = "Aku belum paham. Coba tanya sisa pakan, pakan terbuang, hasil terakhir, atau confidence."

INTENTS = [
    ("aksi", r"\b(kosongkan|bersihkan|keluarkan|sajikan|gerakkan|nyalakan)\b|\b(tolong|coba|ayo)\b.*\b(buang|beri|kasih)\b|\b(buang|beri|kasih)\b.*\b(sekarang|manual|sisa)\b"),
    ("terbuang", r"terbuang|dibuang|rasio|sisa makan|mubazir"),
    ("stok", r"sisa pakan|stok|habis|tangki|tabung|isi ulang"),
    ("terakhir", r"terakhir|barusan|baru saja|terbaru"),
    ("confidence", r"confidence|keyakinan|yakin|kamera|akurasi"),
    ("total", r"total|berapa kali|jumlah|terdeteksi|statistik"),
]


def intent_of(text):
    text = text.lower()
    for name, pattern in INTENTS:
        if re.search(pattern, text):
            return name
    return None


def rule_reply(device, text):
    mode, hewan = device["mode"], feeder.KELAS[device["mode"]]
    events = feeder.week_events(device)
    total = feeder.totals(events, mode)
    stock = feeder.stock_summary(device)
    intent = intent_of(text)

    if intent == "stok":
        out = f"Sisa pakan {fmt(stock['sisa_g'])} g ({fmt(stock['persen'])}%)."
        if stock["perkiraan_habis_hari"] is not None:
            out += f" Habis ±{stock['perkiraan_habis_hari']:.0f} hari."
        return {"teks": out}

    if intent == "terbuang":
        if total["rasio_terbuang"] is None:
            return {"teks": "Belum ada data pakan terbuang. Alat belum melaporkan sisa pakan."}
        return {"teks": f"7 hari terakhir: {fmt(total['pakan_terbuang_g'])} g dari {fmt(total['pakan_keluar_g'])} g "
                        f"terbuang ({fmt(total['rasio_terbuang'])}%)."}

    if intent == "terakhir":
        last = feeder.latest_label(device)
        if last is None:
            return {"teks": "Belum ada hasil klasifikasi."}
        return {"teks": f"{kelas_of(last['label'])}, {fmt(100 * last['confidence'])}%, {last['ts'][11:16]}. "
                        f"{feeder.action_text(last)}."}

    if intent == "confidence":
        values = [e["confidence"] for e in events if feeder.is_classification(e)]
        if not values:
            return {"teks": "Belum ada hasil klasifikasi."}
        return {"teks": f"Confidence rata-rata {fmt(100 * sum(values) / len(values))}% dari {len(values)} klasifikasi."}

    if intent == "total":
        return {"teks": f"{total['total']} klasifikasi: {total['hewan']} {hewan}, {total['bukan']} Bukan Keduanya."}

    if intent == "aksi":
        return {"teks": CANNOT_ACT}

    return {"teks": FALLBACK}


def persona():
    path = current_app.config["PERSONA_FILE"]
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "Kamu Purr, asisten feeder PurrFeed. Jawab singkat dalam Bahasa Indonesia, hanya seputar PurrFeed."


def clean_history(turns):
    out = []
    for turn in (turns or [])[-MAX_TURNS:]:
        if isinstance(turn, dict) and turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            out.append({"role": turn["role"], "content": turn["content"][:400]})
    while out and out[0]["role"] == "assistant":
        out.pop(0)   # riwayat harus diawali giliran pengguna (pesan inisiatif Purr tidak boleh jadi pembuka)
    return out


def llm_reply(device, text, turns):
    cfg = current_app.config
    system = f"{persona()}\n\n{FORMAT_RULES}\n\nDATA ALAT (sumber kebenaran, jangan keluar dari angka ini):\n{insights.context(device)}"
    messages = [{"role": "system", "content": system}, *clean_history(turns), {"role": "user", "content": text}]
    answer = llm.parse_reply(llm.complete(cfg, messages))
    if not answer:
        raise llm.LLMError("jawaban kosong setelah dibersihkan")
    if CLAIMS_DONE.search(answer):
        raise llm.LLMError("jawaban mengaku servo sudah bergerak")
    return {"teks": answer}


def reply(device, text, turns=None):
    """LLM first (if configured), rule-based fallback on any failure. `sumber` tells the UI which one answered."""
    cfg = current_app.config
    if llm.configured(cfg):
        try:
            return {**llm_reply(device, text, turns), "sumber": "llm"}
        except llm.LLMError as exc:
            current_app.logger.warning("Purr Assistant: LLM gagal (%s), pakai jawaban aturan", exc)
    return {**rule_reply(device, text), "sumber": "aturan"}
