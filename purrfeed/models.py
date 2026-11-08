import io
import threading
import time
from dataclasses import dataclass

import joblib

from .features import FEATURE_DIM, FEATURE_VERSION, FeatureExtractor

REQUIRED_KEYS = ("classifier", "target", "tau", "algorithm")


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    probabilities: dict
    elapsed_ms: float
    algorithm: str
    target: str
    tau: float
    box: list | None = None   # [x0, y0, x1, y1] 0..1, area yang dilihat model; None = seluruh frame


def validate(bundle, mode):
    """Return an Indonesian error message if a trained bundle cannot be served for `mode`, else None."""
    if not isinstance(bundle, dict):
        return "isi file bukan dictionary hasil training"
    missing = [key for key in REQUIRED_KEYS if key not in bundle]
    if missing:
        return f"kunci hilang: {', '.join(missing)}"
    classifier = bundle["classifier"]
    if not hasattr(classifier, "predict_proba") or not hasattr(classifier, "classes_"):
        return "classifier tidak punya predict_proba/classes_ (pakai CalibratedClassifierCV atau model probabilistik)"
    version = bundle.get("feature_version")
    if version != FEATURE_VERSION:
        return f"feature_version '{version}' tidak cocok dengan server ('{FEATURE_VERSION}'): fitur dibuat dengan backbone berbeda"
    dim = getattr(classifier, "n_features_in_", FEATURE_DIM)
    if dim != FEATURE_DIM:
        return f"classifier menerima {dim} fitur, server menghasilkan {FEATURE_DIM}"
    if bundle["target"] != mode:
        return f"target model '{bundle['target']}' tidak sama dengan hewan '{mode}'"
    if str(bundle["target"]) not in {str(c) for c in classifier.classes_}:
        return f"kelas target '{bundle['target']}' tidak ada di classes_ {list(classifier.classes_)}"
    if not 0 < float(bundle["tau"]) < 1:
        return f"tau {bundle['tau']} harus di antara 0 dan 1"
    return None


class ModelRegistry:
    """Loads one classifier per animal mode at startup and shares a single feature extractor.

    A model file is `<MODEL_DIR>/<mode>.joblib`. A file that fails validation is skipped, not served:
    the reason is kept in `self.rejected` so the dashboard/health endpoint can show it.
    """

    def __init__(self, model_dir, modes):
        self.model_dir = model_dir
        self._modes = tuple(modes)
        self.bundles = {}
        self.rejected = {}
        self.extractor = None
        self._lock = threading.Lock()

    def load(self):
        self.bundles.clear()
        self.rejected.clear()
        for mode in self._modes:
            path = self.model_dir / f"{mode}.joblib"
            if not path.exists():
                continue
            try:
                bundle = joblib.load(path)
            except Exception as exc:   # corrupt file, wrong sklearn version, missing class, ...
                self.rejected[mode] = f"gagal dibaca: {type(exc).__name__}: {str(exc)[:160]}"
                continue
            problem = validate(bundle, mode)
            if problem:
                self.rejected[mode] = problem
            else:
                self.bundles[mode] = bundle
        if self.bundles and self.extractor is None:
            self.extractor = FeatureExtractor()

    @property
    def modes(self):
        return sorted(self._modes)

    def available(self, mode):
        return mode in self.bundles

    def describe(self):
        return {mode: {"algoritma": b["algorithm"], "tau": float(b["tau"]), "dilatih": b.get("trained_at")}
                for mode, b in sorted(self.bundles.items())}

    def predict(self, mode, image_bytes):
        bundle = self.bundles[mode]
        classifier = bundle["classifier"]
        with self._lock:
            started = time.perf_counter()
            features = self.extractor([io.BytesIO(image_bytes)])
            probabilities = classifier.predict_proba(features)[0]
            box = self.extractor.last_boxes[0]
            elapsed_ms = (time.perf_counter() - started) * 1000

        by_class = {str(c): round(float(p), 4) for c, p in zip(classifier.classes_, probabilities)}
        label = max(by_class, key=by_class.get)
        return Prediction(label, by_class[label], by_class, round(elapsed_ms, 1),
                          bundle["algorithm"], bundle["target"], float(bundle["tau"]), box)
