"""Train and evaluate the MobileNetV2 + SVM cat / non-cat classifier.

    python -m training.train

Augmented images (grey cats, cats printed or on a phone screen) are generated in memory from the
split they belong to, so no copy of a test photo ever reaches the training set.
"""
import argparse
import json
import math
import random
import time
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from purrfeed.features import FeatureExtractor, load_rgb
from training.augment import fake_print, grayscale, shrink

ALGORITHM = "MobileNetV2 + SVM"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default="dataset", help="own dataset, one subfolder per class")
    parser.add_argument("--extra", nargs="*", default=[], help="extra datasets with the same class names")
    parser.add_argument("--background-prefix", default="benda_", help="non-target images used as rooms for printed-cat samples")
    parser.add_argument("--test-dir", default="dataset_uji", help="extra test folders; every image is non-target")
    parser.add_argument("--target", default="kucing")
    parser.add_argument("--negative", default="nonkucing")
    parser.add_argument("--prints", type=int, default=100, help="number of printed/screen cat samples")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tau", type=float, default=0.6, help="minimum confidence to feed")
    parser.add_argument("--C", type=float, default=1.0, help="SVM regularisation")
    parser.add_argument("--out", default="models/mobilenetv2_svm.joblib")
    parser.add_argument("--no-refit", action="store_true", help="keep the model trained on the training split only")
    return parser.parse_args()


def list_images(folder):
    return sorted(p for p in Path(folder).rglob("*") if p.suffix.lower() in IMAGE_EXT)


def load_dataset(roots):
    paths, labels = [], []
    for root in roots:
        for class_dir in sorted(d for d in Path(root).iterdir() if d.is_dir()):
            files = list_images(class_dir)
            paths += files
            labels += [class_dir.name] * len(files)
    return paths, np.array(labels)


def build_classifier(labels, C):
    folds = int(max(2, min(5, np.unique(labels, return_counts=True)[1].min())))
    svm = SVC(kernel="linear", C=C, class_weight="balanced")
    return make_pipeline(StandardScaler(), CalibratedClassifierCV(svm, method="sigmoid", cv=folds, ensemble=False))


def augment(cats, backgrounds, n_prints, seed):
    rnd = random.Random(seed)
    grey = [grayscale(shrink(load_rgb(p))) for p in cats]
    prints = [fake_print(shrink(load_rgb(cats[i % len(cats)])), shrink(load_rgb(rnd.choice(backgrounds))), rnd)
              for i in range(n_prints)]
    return grey, prints


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def feed_probability(classifier, features, target):
    return classifier.predict_proba(features)[:, list(classifier.classes_).index(target)]


def evaluate(classifier, features, labels, args):
    predicted = classifier.classes_[classifier.predict_proba(features).argmax(1)]
    fed = feed_probability(classifier, features, args.target) >= args.tau
    is_target = labels == args.target
    correct = int((predicted == labels).sum())
    return {
        "n": len(labels),
        "akurasi": correct / len(labels),
        "ci95": wilson(correct, len(labels)),
        "macro_f1": float(f1_score(labels, predicted, average="macro")),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=[args.target, args.negative]).tolist(),
        "salah_beri_pakan": int((fed & ~is_target).sum()),
        "kucing_ditahan": int((~fed & is_target).sum()),
    }


def decision_rate(classifier, features, expect_feed, args):
    fed = feed_probability(classifier, features, args.target) >= args.tau
    return int((fed == expect_feed).sum()), len(fed)


def main():
    args = parse_args()
    extractor = FeatureExtractor()
    paths, labels = load_dataset([args.data, *args.extra])
    if set(labels) != {args.target, args.negative}:
        raise SystemExit(f"Kelas harus {args.target} dan {args.negative}, ditemukan {sorted(set(labels))}")
    negatives = list_images(Path(args.data) / args.negative)
    rooms = {p for p in negatives if p.name.startswith(args.background_prefix)} or set(negatives)

    index = np.arange(len(paths))
    train_idx, test_idx = train_test_split(index, test_size=args.test_size, stratify=labels, random_state=args.seed)
    counts = ", ".join(f"{c} {n}" for c, n in zip(*np.unique(labels, return_counts=True)))
    print(f"[{ALGORITHM}] {len(paths)} gambar asli ({counts}) "
          f"-> latih {len(train_idx)}, uji {len(test_idx)}")

    started = time.perf_counter()
    features = extractor(paths)
    print(f"  ekstraksi fitur: {features.shape} dalam {time.perf_counter() - started:.0f} s")

    def augmented(idx, n_prints, seed):
        cats = [paths[i] for i in idx if labels[i] == args.target]
        backgrounds = [paths[i] for i in idx if paths[i] in rooms]
        grey, prints = augment(cats, backgrounds, n_prints, seed)
        return extractor(grey), extractor(prints)

    def fit(idx, seed):
        grey, prints = augmented(idx, args.prints, seed)
        X = np.concatenate([features[idx], grey, prints])
        y = np.concatenate([labels[idx], [args.target] * len(grey), [args.negative] * len(prints)])
        return build_classifier(y, args.C).fit(X, y), len(y)

    classifier, n_train = fit(train_idx, args.seed)
    print(f"  data latih termasuk augmentasi: {n_train} gambar")

    started = time.perf_counter()
    report = {"uji": evaluate(classifier, features[test_idx], labels[test_idx], args)}
    test_grey, test_prints = augmented(test_idx, max(10, args.prints // 3), args.seed + 1)
    report["uji_kucing_hitam_putih"] = decision_rate(classifier, test_grey, True, args)
    report["uji_kucing_cetak_layar"] = decision_rate(classifier, test_prints, False, args)
    if Path(args.test_dir).is_dir():
        for folder in sorted(d for d in Path(args.test_dir).iterdir() if d.is_dir()):
            report[f"{args.test_dir}/{folder.name}"] = decision_rate(classifier, extractor(list_images(folder)), False, args)
    report["inferensi_ms_per_gambar"] = round((time.perf_counter() - started) * 1000 / len(test_idx), 1)

    main_test = report["uji"]
    low, high = main_test["ci95"]
    print(f"\n  Uji 20%           : akurasi {main_test['akurasi']:.1%} (CI95 {low:.1%}-{high:.1%}), macro-F1 {main_test['macro_f1']:.3f}")
    print(f"  Salah beri pakan  : {main_test['salah_beri_pakan']}   kucing ditahan: {main_test['kucing_ditahan']}   (tau {args.tau})")
    print(f"  Confusion matrix  : {main_test['confusion_matrix']}  (baris asli, kolom prediksi: {args.target}, {args.negative})")
    for name, value in report.items():
        if isinstance(value, tuple):
            print(f"  {name:<38} benar {value[0]}/{value[1]}")

    if not args.no_refit:
        classifier, n_train = fit(index, args.seed)
        print(f"\n  Model akhir dilatih ulang dengan seluruh data ({n_train} gambar).")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"classifier": classifier, "classes": [str(c) for c in classifier.classes_], "target": args.target,
                 "tau": args.tau, "algorithm": ALGORITHM, "trained_at": datetime.now().isoformat(timespec="seconds")}, out)
    metrics = Path("reports") / f"{out.stem}_metrics.json"
    metrics.parent.mkdir(exist_ok=True)
    metrics.write_text(json.dumps({"algoritma": ALGORITHM, "parameter": vars(args), **report}, indent=2, ensure_ascii=False))
    print(f"  Model  : {out}\n  Metrik : {metrics}")


if __name__ == "__main__":
    main()
