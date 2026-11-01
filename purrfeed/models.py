import io
import threading
import time
from dataclasses import dataclass

import joblib

from .features import FeatureExtractor


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    probabilities: dict
    elapsed_ms: float
    algorithm: str
    target: str
    tau: float


class ModelRegistry:
    """Loads one classifier per feeder mode at startup and shares a single feature extractor."""

    def __init__(self, model_dir, files):
        self.model_dir = model_dir
        self.files = files
        self.bundles = {}
        self.extractor = None
        self._lock = threading.Lock()

    def load(self):
        for mode, filename in self.files.items():
            path = self.model_dir / filename
            if path.exists():
                self.bundles[mode] = joblib.load(path)
        if self.bundles:
            self.extractor = FeatureExtractor()

    @property
    def modes(self):
        return sorted(self.files)

    def available(self, mode):
        return mode in self.bundles

    def describe(self):
        return {mode: bundle["algorithm"] for mode, bundle in sorted(self.bundles.items())}

    def predict(self, mode, image_bytes):
        bundle = self.bundles[mode]
        classifier = bundle["classifier"]
        with self._lock:
            started = time.perf_counter()
            features = self.extractor([io.BytesIO(image_bytes)])
            probabilities = classifier.predict_proba(features)[0]
            elapsed_ms = (time.perf_counter() - started) * 1000

        by_class = {str(c): round(float(p), 4) for c, p in zip(classifier.classes_, probabilities)}
        label = max(by_class, key=by_class.get)
        return Prediction(label, by_class[label], by_class, round(elapsed_ms, 1),
                          bundle["algorithm"], bundle["target"], float(bundle["tau"]))
