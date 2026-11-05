import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """KEY=value per baris ke os.environ. Env yang sudah diset di shell tidak ditimpa."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip().removeprefix("export "), value)


_load_dotenv(BASE_DIR / ".env")


def _headers():
    """Extra HTTP headers for the LLM API, as a JSON object in PURRFEED_LLM_HEADERS."""
    try:
        data = json.loads(os.environ.get("PURRFEED_LLM_HEADERS", "{}"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except ValueError:
        return {}


class Config:
    DATABASE = Path(os.environ.get("PURRFEED_DB", BASE_DIR / "instance" / "feeder.db"))
    MODEL_DIR = Path(os.environ.get("PURRFEED_MODEL_DIR", BASE_DIR / "models"))
    MODEL_MODES = ("kucing", "anjing")   # satu hewan = satu file models/<hewan>.joblib
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024

    TANK_CAPACITY_G = 2000.0
    PORTION_G = 30.0
    PORTION_NOISE_G = 2.0
    # ID alat terdaftar -> hewan awal (dipilih ulang saat masuk). Tanpa riwayat.
    SEED_DEVICES = {"FEED-0001": "kucing", "FEED-0002": "anjing", "FEED-0003": "kucing"}

    # Purr Assistant: API pribadi kompatibel OpenAI (POST {URL}/chat/completions). Kosong = jawaban aturan.
    LLM_URL = os.environ.get("PURRFEED_LLM_URL", "")
    LLM_KEY = os.environ.get("PURRFEED_LLM_KEY", "")
    LLM_MODEL = os.environ.get("PURRFEED_LLM_MODEL", "")
    LLM_HEADERS = _headers()
    # 1 = gateway mengabaikan role "system": persona + data digabung ke pesan user pertama.
    LLM_SYSTEM_AS_USER = os.environ.get("PURRFEED_LLM_SYSTEM_AS_USER", "1") == "1"
    LLM_TEMPERATURE = float(os.environ.get("PURRFEED_LLM_TEMPERATURE", 0.4))
    LLM_MAX_TOKENS = int(os.environ.get("PURRFEED_LLM_MAX_TOKENS", 300))
    LLM_TIMEOUT_S = float(os.environ.get("PURRFEED_LLM_TIMEOUT", 15))
    PERSONA_FILE = Path(os.environ.get("PURRFEED_PERSONA", BASE_DIR / "persona.md"))
