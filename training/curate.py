"""Select a compact, diverse non-target set from one or more image pools.

Every image gets a category from its file name. Near-duplicates are dropped first; then, per category,
k-means on MobileNetV2 features picks the image closest to each cluster centre, so a small subset keeps
the variety of the whole pool.

    python -m training.curate --source pool_a pool_b --out dataset/nonkucing
"""
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans

from purrfeed.features import FeatureExtractor, load_rgb
from training.augment import shrink

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# (file-name pattern, category, quota per category; None keeps every image). First match wins.
RULES = [
    (r"^(?:home_train_|home_test_|benda_)", "benda_rumah", 120),
    (r"^palsu_", "kucing_palsu", None),
    (r"^hewan_(mouse|rat|hamster|squirrel)_", "hewan_{}", 20),
    (r"^hewan_(lizard|cockroach|snake)_", "hewan_{}", 10),
    (r"^(?:hewan|alam)_dog_", "anjing", 20),
    (r"^hewan_([a-z]+)_", "hewan_{}", 6),
    (r"^alam_([a-z]+)_", "alam_{}", 10),
    (r"^boneka_kucing_", "boneka_kucing", None),
    (r"^(maneki_neko|kucing_mainan)_", "{}", 30),
    (r"^(hello_kitty|boneka_hewan|boneka)_", "{}", 20),
]


def categorize(name):
    for pattern, category, quota in RULES:
        match = re.match(pattern, name)
        if match:
            return category.format(*match.groups()), quota
    return "lainnya", None


def output_name(path):
    name = re.sub(r"^home_(?:train|test)_", "benda_", path.stem)
    return f"{name}.jpg"


def drop_near_duplicates(features, threshold):
    keep = []
    for i, vector in enumerate(features):
        if not keep or (features[keep] @ vector).max() < threshold:
            keep.append(i)
    return keep


def representatives(features, quota, seed):
    if quota is None or len(features) <= quota:
        return list(range(len(features)))
    kmeans = KMeans(n_clusters=quota, n_init=10, random_state=seed).fit(features)
    chosen = []
    for cluster, centre in enumerate(kmeans.cluster_centers_):
        members = np.flatnonzero(kmeans.labels_ == cluster)
        chosen.append(members[np.argmin(np.linalg.norm(features[members] - centre, axis=1))])
    return sorted(chosen)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--duplicate-threshold", type=float, default=0.97, help="cosine similarity")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    paths = sorted({p for source in args.source for p in Path(source).rglob("*") if p.suffix.lower() in IMAGE_EXT})
    features = FeatureExtractor()(paths)
    features /= np.linalg.norm(features, axis=1, keepdims=True)

    unique = set(drop_near_duplicates(features, args.duplicate_threshold))
    groups = defaultdict(list)
    for i, path in enumerate(paths):
        if i in unique:
            groups[categorize(path.name)].append(i)

    selected = set()
    for (category, quota), members in sorted(groups.items()):
        picks = representatives(features[members], quota, args.seed)
        selected.update(members[k] for k in picks)
        print(f"  {category:<22} {len(picks):>4} / {len(members)}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out.parent / f"{out.name}_kurasi.csv", "w", newline="") as report:
        writer = csv.writer(report)
        writer.writerow(["file", "kategori", "status"])
        for i, path in enumerate(paths):
            status = "dipilih" if i in selected else ("tidak_dipilih" if i in unique else "duplikat")
            writer.writerow([str(path), categorize(path.name)[0], status])
            if i in selected:
                shrink(load_rgb(path)).save(out / output_name(path), quality=90)

    print(f"Dipilih {len(selected)} dari {len(paths)} gambar ({len(paths) - len(unique)} nyaris duplikat dibuang) -> {out}")


if __name__ == "__main__":
    main()
