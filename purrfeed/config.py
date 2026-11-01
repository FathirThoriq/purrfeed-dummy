import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    DATABASE = Path(os.environ.get("PURRFEED_DB", BASE_DIR / "instance" / "feeder.db"))
    MODEL_DIR = Path(os.environ.get("PURRFEED_MODEL_DIR", BASE_DIR / "models"))
    MODEL_FILES = {
        "kucing": "mobilenetv2_svm.joblib",
        "anjing": "mobilenetv2_svm_anjing.joblib",
    }
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024

    TANK_CAPACITY_G = 2000.0
    PORTION_G = 30.0
    PORTION_NOISE_G = 2.0
    SEED_DEVICES = {"FEED-0001": True, "FEED-0002": False, "FEED-0003": False}
