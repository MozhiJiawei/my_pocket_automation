"""Exercise the read-only screenshot CLI without a connected device."""

from contextlib import redirect_stdout
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEVICE = "127.0.0.1:16544"
DEVICE_SCRIPTS = ROOT / "scripts/device"
spec = importlib.util.spec_from_file_location("inspect_device", DEVICE_SCRIPTS / "inspect-device.py")
inspect_device = importlib.util.module_from_spec(spec)
with patch.object(sys, "path", [str(DEVICE_SCRIPTS), *sys.path]):
    spec.loader.exec_module(inspect_device)
    import dfx_device


class InspectDeviceTest(unittest.TestCase):
    def setUp(self):
        workspace = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(workspace) / "截图 evidence"
        self.enterContext(patch.object(inspect_device, "ROOT", self.root))
        self.ocr = self.enterContext(patch.object(inspect_device, "RapidOCR"))
        self.run_adb = self.enterContext(patch.object(inspect_device.subprocess, "run"))
        self.command = [inspect_device.ADB, "-s", DEVICE, "exec-out", "screencap", "-p"]
        self.frame = np.arange(7 * 13 * 3, dtype=np.uint8).reshape(7, 13, 3)
        success, encoded = cv2.imencode(".png", self.frame, [cv2.IMWRITE_PNG_COMPRESSION, 0])
        self.assertTrue(success)
        self.png = encoded.tobytes()
        self.run_adb.return_value = subprocess.CompletedProcess(self.command, 0, stdout=self.png)

    def invoke(self, output, *options):
        with patch.object(sys, "argv", ["inspect-device.py", "--device", DEVICE, *options]):
            with redirect_stdout(output):
                inspect_device.main()

    def assert_capture(self, output, label, words):
        payload = json.loads(output.getvalue())
        run_id = payload["run_id"]
        self.assertRegex(run_id, r"^\d{8}_\d{6}$")
        archive = self.root / "debug-runs" / run_id
        png = archive / "res" / f"daily_{run_id}_{label}.png"
        self.assertEqual(png.read_bytes(), self.png)
        expected = {"path": str(png), "run_id": run_id, "size": [13, 7]}
        self.assertEqual(payload, expected)
        record = json.loads((archive / "log" / f"{label}.json").read_text(encoding="utf-8"))
        self.assertEqual(record, {**expected, "label": label, "words": words})
        return run_id

    def test_screenshot_only_saves_exact_binary_output_and_default_label(self):
        output = io.StringIO()
        self.invoke(output, "--no-ocr")

        self.run_adb.assert_called_once_with(self.command, capture_output=True, timeout=40)
        self.ocr.assert_not_called()
        self.assert_capture(output, "observe", [])

    def test_ocr_gets_decoded_pixels_and_stays_in_local_json(self):
        box = [[1, 2], [6, 2], [6, 5], [1, 5]]
        result = SimpleNamespace(txts=["角色甲"], scores=[np.float32(0.75)], boxes=[np.array(box)])
        engine = Mock(return_value=result)
        self.ocr.return_value = engine
        output = io.StringIO()
        self.invoke(output, "--label", "monitor_5")

        self.run_adb.assert_called_once_with(self.command, capture_output=True, timeout=40)
        self.ocr.assert_called_once_with()
        engine.assert_called_once()
        np.testing.assert_array_equal(engine.call_args.args[0], self.frame)
        self.assert_capture(output, "monitor_5", [{"text": "角色甲", "score": 0.75, "box": box}])

    def test_two_captures_in_the_same_second_keep_distinct_archives(self):
        first = io.StringIO()
        second = io.StringIO()
        with patch.object(dfx_device, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 13, 9, 0, 0)
            self.invoke(first, "--no-ocr")
            self.invoke(second, "--no-ocr")

        self.assertNotEqual(self.assert_capture(first, "observe", []), self.assert_capture(second, "observe", []))

    def test_invalid_or_failed_capture_never_publishes_a_screenshot(self):
        success, jpeg = cv2.imencode(".jpg", self.frame)
        self.assertTrue(success)
        for name, status, data in (
            ("ADB nonzero", 1, self.png),
            ("empty stdout", 0, b""),
            ("text stdout", 0, b"unexpected ADB output"),
            ("JPEG stdout", 0, jpeg.tobytes()),
            ("truncated PNG", 0, self.png[:16]),
        ):
            with self.subTest(name=name):
                self.run_adb.reset_mock()
                self.run_adb.return_value = subprocess.CompletedProcess(self.command, status, stdout=data)
                self.assert_failed_capture(RuntimeError)

    def test_adb_timeout_never_publishes_a_screenshot(self):
        self.run_adb.side_effect = subprocess.TimeoutExpired(self.command, 40, output=self.png[:16])
        self.assert_failed_capture((RuntimeError, subprocess.TimeoutExpired))

    def assert_failed_capture(self, error):
        output = io.StringIO()
        with self.assertRaises(error):
            self.invoke(output, "--no-ocr")

        self.run_adb.assert_called_once_with(self.command, capture_output=True, timeout=40)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(list(self.root.glob("debug-runs/*/res/*.png")), [])
        self.assertEqual(list(self.root.glob("debug-runs/*/log/*.json")), [])


if __name__ == "__main__":
    unittest.main()
