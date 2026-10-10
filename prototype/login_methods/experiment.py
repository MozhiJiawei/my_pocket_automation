"""Repeatable login-entry experiments. Secrets stay outside the repository.

Native methods execute Lua via ts-cli; UI/OCR methods execute on this host.
No credentials are entered and the entry confirmation is never accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import numpy as np

ROOT = Path("D:/Agent Repo/my_pocket_automation")
HERE = ROOT / "prototype/login_methods"
REMOTE = "/storage/emulated/0/TouchSprite"
APP = "com.netease.mhxyhtb"
METHODS = ("fixed", "relative", "multicolor", "template", "controls", "ocr")
BASE_SIZE = (1600, 900)
LABEL_RECT = (1502, 739, 1569, 774)
TAP = (1534, 716)
POWERSHELL = shutil.which("pwsh") or "powershell"


def run_command(args: list[str], timeout: int = 40) -> str:
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        # ADB output can include identifiers; do not include it in exceptions.
        raise RuntimeError(f"{Path(args[0]).name} failed (exit {result.returncode})")
    return result.stdout.decode("utf-8", errors="replace").strip()


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Unreadable image")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", image)[1].tofile(path)


def template_match(image: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int]]:
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, pos = cv2.minMaxLoc(scores)
    return float(score), pos


def calibrate(paths: list[Path]) -> None:
    frames = [read_image(path) for path in paths]
    image = frames[0]
    if any((frame.shape[1], frame.shape[0]) != BASE_SIZE for frame in frames):
        raise ValueError("Calibration requires the inspected 1600x900 landscape page")
    x1, y1, x2, y2 = LABEL_RECT
    template = image[y1:y2, x1:x2].copy()
    # A small pattern over the lettering; never store the character/account panel.
    stack = np.stack([frame[y1:y2, x1:x2] for frame in frames])
    ys, xs = np.where(np.min(stack, axis=(0, 3)) > 240)
    if len(xs) < 12:
        raise ValueError("Insufficient lettering features")
    selected = [(int(xs[i]), int(ys[i])) for i in np.linspace(0, len(xs) - 1, 12, dtype=int)]
    ax, ay = selected[0]
    points = []
    for x, y in selected:
        b, g, r = map(int, template[y, x])
        points.append([x - ax, y - ay, (r << 16) | (g << 8) | b])
    config = {"base_w": 1600, "base_h": 900, "tap_x": TAP[0], "tap_y": TAP[1],
              "anchor_x": x1 + ax, "anchor_y": y1 + ay, "points": points,
              "template_rect": list(LABEL_RECT), "template_threshold": 0.92,
              "feature_selection": f"12 white lettering pixels stable across {len(frames)} real frames"}
    (HERE / "assets").mkdir(exist_ok=True)
    write_image(HERE / "assets/pocket_label.png", template)
    (HERE / "calibration.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Calibration saved: public pocket label and pixel features only", flush=True)


class Device:
    def __init__(self, adb: str, device: str | None):
        self.adb = adb
        if not device:
            candidates = re.findall(r"^(\S+)\s+device$", run_command([adb, "devices"]), re.M)
            if len(candidates) != 1:
                raise RuntimeError("Supply --device when connected-device count is not one")
            device = candidates[0]
        self.device = device
        self.port: str | None = None
        self.auth: str | None = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def adb_call(self, *args: str, timeout: int = 40) -> str:
        return run_command([self.adb, "-s", self.device, *args], timeout)

    def request(self, url: str, body: dict | None = None, authenticated: bool = False) -> str:
        headers = {"Connection": "close"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        if authenticated:
            headers["auth"] = self.auth
        try:
            with self.http.open(urllib.request.Request(url, data=data, headers=headers), timeout=30) as response:
                return response.read().decode().strip()
        except Exception:
            raise RuntimeError("TouchSprite HTTP request failed (details suppressed)") from None

    def authorize(self) -> None:
        self.port = self.adb_call("forward", "tcp:0", "tcp:50005")
        if not self.port.isdigit():
            raise RuntimeError("Invalid forwarded port")
        identity = self.request(f"http://127.0.0.1:{self.port}/deviceid")
        if not re.fullmatch(r"[\w-]{16,64}", identity):
            raise RuntimeError("Unexpected API identity response")
        key_path = Path.home() / ".my_pocket_automation/touchsprite-access-key"
        reply = json.loads(self.request("https://openapi.touchsprite.com/api/openapi", {
            "action": "getAuth", "key": key_path.read_text(encoding="utf-8").strip(),
            "devices": [identity], "valid": 3600, "time": int(time.time())}))
        if reply.get("status") != 200 or not reply.get("auth"):
            raise RuntimeError(f"getAuth rejected (status={reply.get('status')}; details suppressed)")
        self.auth = reply["auth"]

    def status(self) -> str:
        return self.request(f"http://127.0.0.1:{self.port}/status", authenticated=True)

    def close(self) -> None:
        if self.port and self.port.isdigit():
            self.adb_call("forward", "--remove", f"tcp:{self.port}")
        self.auth = None


class Experiment:
    def __init__(self, device: Device):
        self.device = device
        self.config = json.loads((HERE / "calibration.json").read_text())
        self.template = read_image(HERE / "assets/pocket_label.png")
        self.confirmation_template = read_image(HERE / "assets/confirmation_label.png")
        self.ocr_engine = None
        self.summary = []

    def log(self, event: str, **fields) -> None:
        entry = {"run_id": self.run_id, "method": self.method,
                 "event": event, "elapsed_ms": round((time.perf_counter() - self.start) * 1000, 2), **fields}
        with (self.run_dir / "log" / f"hello_world_{self.run_id}_host.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    def screenshot(self, label: str) -> tuple[Path, np.ndarray]:
        name = f"hello_world_{self.run_id}_{label}.png"
        remote = f"{REMOTE}/res/{name}"
        local = self.run_dir / "res" / name
        self.device.adb_call("shell", "screencap", "-p", remote)
        self.device.adb_call("pull", remote, str(local))
        self.log("screenshot", device_path=remote, archive_path=str(local))
        return local, read_image(local)

    def ready(self, image: np.ndarray) -> bool:
        h, w = image.shape[:2]
        if (w, h) != BASE_SIZE:
            return False
        score, pos = template_match(image[int(h * .5):, int(w * .75):], self.template)
        return score >= .80 and not self.modal_present(image)

    def modal_present(self, image: np.ndarray) -> bool:
        score, _ = template_match(image[200:650, 350:1250], self.confirmation_template)
        return score >= .85

    def reset(self) -> np.ndarray:
        if self.device.status() != "f00":
            raise RuntimeError("TouchSprite is not idle; finish prior script before resetting")
        _, current = self.screenshot("reset_before")
        if self.ready(current):
            self.log("entry_page_ready", reset="already_ready")
            return current
        if self.modal_present(current):
            output = self.ocr(current[250:650, 400:1200])
            cancels = []
            for box, text in zip(output.boxes if output.boxes is not None else [], output.txts or []):
                if text.replace(" ", "") == "取消":
                    center = np.mean(box, axis=0)
                    cancels.append((round(float(center[0])) + 400, round(float(center[1])) + 250))
            if len(cancels) != 1:
                raise RuntimeError("Cannot locate confirmation cancel button for repeatable reset")
            self.device.adb_call("shell", "input", "tap", str(cancels[0][0]), str(cancels[0][1]))
            self.log("reset_cancel", backend="host_OCR", position=cancels[0])
            time.sleep(1)
            _, current = self.screenshot("reset_cancelled")
            if self.ready(current):
                self.log("entry_page_ready", reset="cancel")
                return current
        # Cancel the game's entry confirmation first; do not accept it or clear data.
        self.device.adb_call("shell", "input", "keyevent", "4")
        time.sleep(1)
        _, current = self.screenshot("reset_back")
        if self.ready(current):
            self.log("entry_page_ready", reset="back")
            return current
        self.device.adb_call("shell", "am", "force-stop", APP)
        self.device.adb_call("shell", "monkey", "-p", APP, "-c", "android.intent.category.LAUNCHER", "1")
        for attempt in range(35):
            time.sleep(2)
            _, image = self.screenshot(f"ready_{attempt:02d}")
            if self.ready(image):
                self.log("entry_page_ready", screen=[image.shape[1], image.shape[0]])
                return image
        raise RuntimeError("Entry page readiness timed out; evidence preserved")

    def ocr(self, image: np.ndarray):
        if self.ocr_engine is None:
            from rapidocr import RapidOCR
            start = time.perf_counter()
            self.ocr_engine = RapidOCR()
            self.log("ocr_engine_loaded", load_ms=round((time.perf_counter() - start) * 1000, 2), backend="RapidOCR/ONNX CPU")
        return self.ocr_engine(image)

    def control_locator(self) -> tuple[tuple[int, int] | None, dict]:
        remote = f"{REMOTE}/res/hello_world_{self.run_id}_tree.xml"
        self.device.adb_call("shell", "uiautomator", "dump", remote, timeout=30)
        tree = ET.fromstring(self.device.adb_call("shell", "cat", remote))
        nodes = list(tree.iter("node"))
        targets = []
        sanitized = []
        for node in nodes:
            attrs = node.attrib
            label = attrs.get("text", "") or attrs.get("content-desc", "")
            is_target = label.strip() == "口袋"
            sanitized.append({"class": attrs.get("class"), "bounds": attrs.get("bounds"),
                              "clickable": attrs.get("clickable"), "target_label": "口袋" if is_target else "[redacted]"})
            if is_target:
                values = list(map(int, re.findall(r"\d+", attrs.get("bounds", ""))))
                if len(values) == 4:
                    targets.append(((values[0] + values[2]) // 2, (values[1] + values[3]) // 2))
        (self.run_dir / "ui-tree-redacted.json").write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
        # Raw hierarchy is never pulled to Windows; only the sanitized tree is archived.
        return (targets[0] if len(targets) == 1 else None), {"node_count": len(nodes), "target_nodes": len(targets)}

    def ocr_locator(self, image: np.ndarray) -> tuple[tuple[int, int] | None, dict]:
        h, w = image.shape[:2]
        left, top = int(w * .75), int(h * .5)
        output = self.ocr(image[top:, left:])
        candidates = []
        target_scores = []
        refinement_used = False
        if output.txts is not None:
            for box, text, score in zip(output.boxes, output.txts, output.scores):
                accepted = text.replace(" ", "") == "口袋" and float(score) >= .8
                if not accepted and "袋" in text:
                    # The broad detector sometimes reads the stylized 口 as 白.
                    # Re-recognize a padded enlarged crop; never accept 白袋 as an alias.
                    bx1, by1 = np.floor(np.min(box, axis=0)).astype(int)
                    bx2, by2 = np.ceil(np.max(box, axis=0)).astype(int)
                    crop = image[max(0, by1 + top - 20):min(h, by2 + top + 20),
                                 max(0, bx1 + left - 20):min(w, bx2 + left + 20)]
                    refined = self.ocr(cv2.resize(crop, None, fx=2, fy=2))
                    refinement_used = True
                    for refined_text, refined_score in zip(refined.txts or [], refined.scores if refined.scores is not None else []):
                        if refined_text.replace(" ", "") == "口袋" and float(refined_score) >= .8:
                            accepted, score = True, refined_score
                if accepted:
                    center = np.mean(box, axis=0)
                    candidates.append((round(float(center[0])) + left, round(float(center[1])) + top))
                    target_scores.append(round(float(score), 4))
        tile_rescan_used = not candidates
        if tile_rescan_used:
            # A broad OCR detector can miss small lettering entirely. Re-scan
            # overlapping tiles at 2x; coordinates still come from recognized boxes.
            mid_x, mid_y = (left + w) // 2, (top + h) // 2
            for tx1, ty1, tx2, ty2 in ((left, top, mid_x + 24, mid_y + 24),
                                      (mid_x - 24, top, w, mid_y + 24),
                                      (left, mid_y - 24, mid_x + 24, h),
                                      (mid_x - 24, mid_y - 24, w, h)):
                tiled = self.ocr(cv2.resize(image[ty1:ty2, tx1:tx2], None, fx=2, fy=2))
                for box, text, confidence in zip(tiled.boxes if tiled.boxes is not None else [],
                                                 tiled.txts or [], tiled.scores if tiled.scores is not None else []):
                    if text.replace(" ", "") != "口袋" or float(confidence) < .8:
                        continue
                    center = np.mean(box, axis=0) / 2
                    point = (round(float(center[0])) + tx1, round(float(center[1])) + ty1)
                    if not any(abs(point[0] - other[0]) < 15 and abs(point[1] - other[1]) < 15 for other in candidates):
                        candidates.append(point)
                        target_scores.append(round(float(confidence), 4))
        return (candidates[0] if len(candidates) == 1 else None), {"target_count": len(candidates), "target_scores": target_scores, "refinement_used": refinement_used, "tile_rescan_used": tile_rescan_used}

    def native(self, method: str) -> None:
        c = self.config
        colors = c["points"]
        offsets = ",".join(f"{dx}|{dy}|0x{rgb:06x}" for dx, dy, rgb in colors[1:])
        fields = {"run_id": self.run_id, "method": method, "click": True,
                  "base_w": c["base_w"], "base_h": c["base_h"], "tap_x": c["tap_x"], "tap_y": c["tap_y"],
                  "anchor_color": colors[0][2], "offset_colors": offsets,
                  "click_dx": c["tap_x"] - c["anchor_x"], "click_dy": c["tap_y"] - c["anchor_y"],
                  "template_path": f"{REMOTE}/res/login_probe_pocket_label.png",
                  "template_click_dx": c["tap_x"] - LABEL_RECT[0], "template_click_dy": c["tap_y"] - LABEL_RECT[1]}
        config_path = self.run_dir / "config.lua"
        config_path.write_text("return {\n" + ",\n".join(f"  {k} = {str(v).lower() if isinstance(v, bool) else json.dumps(v)}" for k, v in fields.items()) + "\n}\n", encoding="utf-8")
        for source, destination in [(config_path, f"{REMOTE}/res/login_probe_config.lua"),
                                    (HERE / "assets/pocket_label.png", f"{REMOTE}/res/login_probe_pocket_label.png")]:
            self.device.adb_call("push", str(source), destination)
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            actual = self.device.adb_call("shell", "sha256sum", destination).split()[0]
            if actual != expected:
                raise RuntimeError("Experiment resource hash mismatch")
        env = os.environ.copy()
        env["TOUCHSPRITE_AUTH"] = self.device.auth
        start = time.perf_counter()
        result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "scripts/device/ts-cli.ps1"), "run", "-AdbPath", self.device.adb,
            "-Device", self.device.device, "-SourcePath", str(HERE / "main.lua")],
            capture_output=True, env=env, timeout=40)
        env.pop("TOUCHSPRITE_AUTH", None)
        if result.returncode:
            diagnostic = result.stderr.decode("utf-8", errors="replace")
            for secret in (self.device.auth, self.device.device):
                if secret:
                    diagnostic = diagnostic.replace(secret, "[redacted]")
            self.log("cli_failure", diagnostic=diagnostic[:2500])
            raise RuntimeError("CLI run failed; sanitized diagnostic archived")
        self.log("published_start_accepted", publish_and_request_ms=round((time.perf_counter() - start) * 1000, 2))
        for _ in range(25):
            time.sleep(.5)
            if self.device.status() == "f00":
                break
        else:
            raise RuntimeError("Native script did not finish before timeout")
        time.sleep(2)  # Let TouchSprite's own end-of-script toast disappear.
        remote_log = f"{REMOTE}/log/hello_world_{self.run_id}.log"
        local_log = self.run_dir / "log" / f"hello_world_{self.run_id}.log"
        self.device.adb_call("pull", remote_log, str(local_log))
        text = local_log.read_text(encoding="utf-8")
        self.log("native_finished", script_finished="script_finished" in text,
                 tap_sent="action=tap" in text, native_error="result=error" in text)

    def verify(self, image: np.ndarray) -> str:
        h, w = image.shape[:2]
        output = self.ocr(image[int(h * .2):int(h * .85), int(w * .15):int(w * .85)])
        text = "".join(output.txts or [])
        confirmation = self.modal_present(image) and "口袋" in text and any(word in text for word in ("进入", "是否", "确定"))
        self.log("postcondition", entry_still_visible=self.ready(image), confirmation_text_detected=confirmation)
        return "confirmation_verified" if confirmation else "transition_unverified"

    def collect(self) -> None:
        run_command([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / "scripts/device/collect-debug.ps1"), "-RunId", self.run_id,
            "-AdbPath", self.device.adb, "-Device", self.device.device])

    def once(self, method: str) -> None:
        self.method = method
        self.run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
        self.run_dir = ROOT / "debug-runs" / self.run_id
        self.run_dir.mkdir(exist_ok=False)
        (self.run_dir / "log").mkdir()
        (self.run_dir / "res").mkdir()
        shutil.copyfile(HERE / "main.lua", self.run_dir / "script-source.lua")
        shutil.copyfile(HERE / "calibration.json", self.run_dir / "calibration.json")
        self.start = time.perf_counter()
        row = {"run_id": self.run_id, "method": method}
        try:
            image = self.reset()
            if method in METHODS[:4]:
                self.native(method)
                local_log = self.run_dir / "log" / f"hello_world_{self.run_id}.log"
                log_text = local_log.read_text(encoding="utf-8")
                match = re.search(r"locate_cpu_ms=([\d.]+)", log_text)
                row["native_locate_cpu_ms"] = float(match[1]) if match else None
                if "action=tap" not in log_text:
                    raise RuntimeError("Native locator did not send a tap; inspect native log")
            else:
                start = time.perf_counter()
                pos, details = self.control_locator() if method == "controls" else self.ocr_locator(image)
                row["host_locate_wall_ms"] = round((time.perf_counter() - start) * 1000, 2)
                self.log("located", position=pos, locate_wall_ms=row["host_locate_wall_ms"], **details)
                if pos is None:
                    row["result"] = "not_found"
                    return
                if not (1200 <= pos[0] < 1600 and 450 <= pos[1] < 900):
                    raise RuntimeError("Candidate outside entry region")
                # OCR/control locators click their own returned point, no fixed-coordinate fallback.
                self.device.adb_call("shell", "input", "tap", str(pos[0]), str(pos[1]))
                self.log("tap_sent", x=pos[0], y=pos[1], backend="ADB")
                time.sleep(2)
            _, after = self.screenshot("feedback")
            row["result"] = self.verify(after)
        except Exception as error:
            row["result"] = "error"
            self.log("failure", reason=str(error))
            self.screenshot("failure")
        finally:
            self.collect()
            self.log("run_finished", result=row.get("result"))
            row["total_wall_ms"] = round((time.perf_counter() - self.start) * 1000, 2)
            (self.run_dir / "result.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
            self.summary.append(row)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", default="D:/Users/37274/AppData/Local/Programs/TS Studio/resource/core/adb/adb.exe")
    parser.add_argument("--device")
    parser.add_argument("--method", choices=(*METHODS, "all"), default="all")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--calibrate", type=Path, nargs="+")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.calibrate:
        calibrate(args.calibrate)
        return
    device = Device(args.adb, args.device)
    try:
        device.authorize()
        experiment = Experiment(device)
        for _ in range(args.repeats):
            for method in METHODS if args.method == "all" else (args.method,):
                experiment.once(method)
        summary = ROOT / "debug-runs" / experiment.summary[0]["run_id"] / "suite-summary.json"
        summary.write_text(json.dumps(experiment.summary, indent=2), encoding="utf-8")
        print(f"Suite summary: {summary}", flush=True)
    finally:
        device.close()


if __name__ == "__main__":
    main()
