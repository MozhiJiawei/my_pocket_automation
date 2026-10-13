"""Host-only perturbation experiments; never change device resolution or click.

OpenCV/color implementations here are models of the principles, not substitutes
for measurements of the TouchSprite native functions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from rapidocr import RapidOCR

from image_models import OCRProbe, HERE, ROOT, TAP, read_image, template_match


def colors(image: np.ndarray, config: dict) -> tuple[int, int] | None:
    h, w = image.shape[:2]
    x1, y1 = int(w * .75), int(h * .5)
    x2, y2 = w, h
    points = config["points"]
    min_dx, max_dx = min(p[0] for p in points), max(p[0] for p in points)
    min_dy, max_dy = min(p[1] for p in points), max(p[1] for p in points)
    x1, y1 = max(x1, -min_dx), max(y1, -min_dy)
    x2, y2 = min(x2, w - max_dx), min(y2, h - max_dy)
    mask = np.ones((y2 - y1, x2 - x1), dtype=bool)
    for dx, dy, rgb in points:
        expected = np.array([rgb & 255, (rgb >> 8) & 255, (rgb >> 16) & 255])
        patch = image[y1 + dy:y2 + dy, x1 + dx:x2 + dx].astype(np.int16)
        mask &= np.max(np.abs(patch - expected), axis=2) <= 13
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    return (int(xs[0]) + x1 + TAP[0] - config["anchor_x"],
            int(ys[0]) + y1 + TAP[1] - config["anchor_y"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    image = read_image(args.input)
    config = json.loads((HERE / "calibration.json").read_text())
    template = read_image(HERE / "assets/pocket_label.png")
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    destination = ROOT / "debug-runs" / run_id
    (destination / "log").mkdir(parents=True, exist_ok=False)
    cases = [("real_later_frame", image, (1., 0, 0), True)]
    shifted = cv2.warpAffine(image, np.float32([[1, 0, -160], [0, 1, -100]]), (1600, 900))
    cases.append(("translate_minus160_minus100", shifted, (1., -160, -100), True))
    for scale in (.8, 1.2):
        cases.append((f"uniform_scale_{scale}", cv2.resize(image, None, fx=scale, fy=scale), (scale, 0, 0), True))
    cases.append(("brightness_60percent", (image * .6).astype(np.uint8), (1., 0, 0), True))
    missing = image.copy()
    missing[655:790, 1470:1600] = 0
    cases.append(("target_removed", missing, (1., 0, 0), False))
    start = time.perf_counter()
    engine = RapidOCR()
    load_ms = (time.perf_counter() - start) * 1000
    ocr_probe = OCRProbe(engine)
    rows = []
    for name, frame, transform, exists in cases:
        scale, dx, dy = transform
        h, w = frame.shape[:2]
        expected = (round(TAP[0] * scale + dx), round(TAP[1] * scale + dy))
        for method in ("fixed", "relative", "edge_offset", "multicolor", "template", "ocr"):
            start = time.perf_counter()
            score = None
            if method == "fixed":
                pos = TAP
            elif method == "relative":
                pos = (round(TAP[0] / 1600 * w), round(TAP[1] / 900 * h))
            elif method == "edge_offset":
                pos = (w - (1600 - TAP[0]), h - (900 - TAP[1]))
            elif method == "multicolor":
                pos = colors(frame, config)
            elif method == "template":
                score, loc = template_match(frame[int(h * .5):, int(w * .75):], template)
                pos = (loc[0] + int(w * .75) + TAP[0] - 1502,
                       loc[1] + int(h * .5) + TAP[1] - 739) if score >= .92 else None
            else:
                pos, details = ocr_probe.ocr_locator(frame)
                score = details["target_scores"][0] if details["target_scores"] else None
            # The button includes both the icon and its lettering below the icon.
            hit = bool(exists and pos and abs(pos[0] - expected[0]) <= 50 * scale
                       and -50 * scale <= pos[1] - expected[1] <= 65 * scale)
            row = {"case": name, "method": method, "position": pos, "target_exists": exists,
                   "expected_center": expected, "hits_button_region": hit,
                   "false_candidate_when_absent": bool(not exists and pos),
                   "score": score, "wall_ms": round((time.perf_counter() - start) * 1000, 3)}
            rows.append(row)
    result = {"kind": "host_image_perturbation_not_device_test", "source": str(args.input),
              "ocr_cold_load_ms": round(load_ms, 3), "results": rows}
    path = destination / "boundary-results.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "log" / f"hello_world_{run_id}_boundary.log").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    print(f"Boundary evidence: {path}", flush=True)
    for row in rows:
        print(f"{row['case']} {row['method']} hit={row['hits_button_region']} absent_candidate={row['false_candidate_when_absent']} ms={row['wall_ms']}")


if __name__ == "__main__":
    main()
