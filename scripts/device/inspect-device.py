"""Capture current-device evidence; optional single tap guarded by current OCR.

This host-side development tool does not start daily tasks or claim task success.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

import cv2
import numpy as np
from rapidocr import RapidOCR

ROOT = Path(__file__).resolve().parents[2]
ADB = "D:/Program Files/Netease/MuMu/nx_main/adb.exe"


def adb(device: str, *args: str) -> bytes:
    result = subprocess.run([ADB, "-s", device, *args], capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError("ADB operation failed; device identifiers suppressed")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--label", default="observe")
    parser.add_argument("--tap", nargs=2, type=int)
    parser.add_argument("--expect", help="Required OCR text before a development tap")
    parser.add_argument("--expect-template", type=Path, help="Alternative current-frame template guard")
    parser.add_argument("--no-ocr", action="store_true", help="Fast screenshot-only observation")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.label):
        raise ValueError("Invalid evidence label")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = ROOT / "debug-runs" / run_id
    (folder / "res").mkdir(parents=True)
    (folder / "log").mkdir()
    if args.no_ocr and args.tap and not args.expect_template:
        raise ValueError("Screenshot-only taps require a template guard")
    if args.tap:
        from dfx_device import Device
        transport = Device(args.device)
        try:
            transport.authorize()
            if transport.status() != 'f00':
                raise RuntimeError('Device script is running; development tap forbidden')
        finally:
            transport.close()
    engine = None if args.no_ocr else RapidOCR()

    def capture(label: str) -> dict:
        remote = f"/storage/emulated/0/TouchSprite/res/daily_{run_id}_{label}.png"
        adb(args.device, "shell", "screencap", "-p", remote)
        local = folder / "res" / f"daily_{run_id}_{label}.png"
        adb(args.device, "pull", remote, str(local))
        frame = cv2.imdecode(np.fromfile(local, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Unreadable screenshot")
        result = engine(frame) if engine else None
        words = []
        if result is not None and result.txts is not None:
            for text, score, box in zip(result.txts, result.scores, result.boxes):
                words.append({"text": text, "score": float(score), "box": box.tolist()})
        record = {"run_id": run_id, "label": label, "path": str(local),
                  "size": [frame.shape[1], frame.shape[0]], "words": words}
        (folder / "log" / f"{label}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return record

    before = capture(args.label)
    if args.tap:
        matched = bool(args.expect and any(args.expect in word["text"] for word in before["words"]))
        if args.expect_template:
            current = cv2.imdecode(np.fromfile(before["path"], dtype=np.uint8), cv2.IMREAD_COLOR)
            template = cv2.imdecode(np.fromfile(args.expect_template, dtype=np.uint8), cv2.IMREAD_COLOR)
            if template is None:
                raise ValueError("Unreadable guard template")
            score = float(cv2.minMaxLoc(cv2.matchTemplate(current, template, cv2.TM_CCOEFF_NORMED))[1])
            matched = score >= 0.90
        if not matched:
            raise RuntimeError("Expected page text absent; no tap sent")
        x, y = args.tap
        if not (0 <= x < before["size"][0] and 0 <= y < before["size"][1]):
            raise ValueError("Tap outside screen")
        adb(args.device, "shell", "input", "tap", str(x), str(y))
        (folder / "log" / "action.json").write_text(json.dumps({
            "expected": args.expect, "tap": [x, y], "before": before["path"]}), encoding="utf-8")
        time.sleep(2)
        before = capture(args.label + "_after")
    # Full OCR stays in local evidence, where account/role labels can be reviewed privately.
    print(json.dumps({"path": before["path"], "run_id": run_id,
                      "size": before["size"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
