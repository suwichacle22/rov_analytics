"""Compare a track CSV against the synthetic ground truth.

Usage: python scripts/eval_synthetic.py data/tracks/game_testjungler_blue.csv data/synthetic/game.truth.csv
"""

from __future__ import annotations

import csv
import sys

MINIMAP_PX = 220


def main(track_csv: str, truth_csv: str) -> None:
    truth = {round(float(r["t"]), 2): (float(r["x"]), float(r["y"])) for r in csv.DictReader(open(truth_csv))}
    errs, bad = [], []
    for r in csv.DictReader(open(track_csv)):
        t = round(float(r["game_sec"]), 2)
        if not r["x_norm"] or t not in truth:
            continue
        tx, ty = truth[t]
        e = ((float(r["x_norm"]) - tx) ** 2 + (float(r["y_norm"]) - ty) ** 2) ** 0.5 * MINIMAP_PX
        errs.append(e)
        if e > 6:
            bad.append((t, round(e, 1), r["status"]))
    errs.sort()
    n = len(errs)
    print(f"samples={n} mean_px={sum(errs)/n:.2f} median_px={errs[n//2]:.2f} p95_px={errs[int(n*0.95)]:.2f} max_px={errs[-1]:.2f}")
    print("frames with error > 6 px:", bad)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
