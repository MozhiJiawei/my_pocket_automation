"""Run the real frontend sources through the dependency-free Node DOM harness."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).with_suffix('.js')


class FrontendTest(unittest.TestCase):
    def run_frontend(self, name):
        node = shutil.which('node')
        if node is None:
            self.skipTest('Node.js unavailable; frontend regression was not executed')
        with tempfile.TemporaryDirectory(prefix='annotation_frontend_', dir=ROOT / '.tmp') as working:
            result = subprocess.run(
                [node, str(SCRIPT), name], cwd=working,
                capture_output=True, text=True, encoding='utf-8', timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS ' + name, result.stdout)

    def test_puzzle_all_pages_and_serialization(self):
        self.run_frontend('puzzle_all_pages_and_serialization')

    def test_puzzle_swap_and_restore_review(self):
        self.run_frontend('puzzle_swap_and_restore_review')

    def test_puzzle_cancel_and_readonly(self):
        self.run_frontend('puzzle_cancel_and_readonly')

    def test_queue_refresh_preserves_new_round(self):
        self.run_frontend('queue_refresh_preserves_new_round')

    def test_queue_refresh_cannot_unlock_confirmation(self):
        self.run_frontend('queue_refresh_cannot_unlock_confirmation')

    def test_capture_height_updates_with_round_and_preserves_confirmed_answers(self):
        self.run_frontend('capture_height_updates_with_round_and_preserves_confirmed_answers')

    def test_capture_height_hides_on_the_existing_image_open_error(self):
        self.run_frontend('capture_height_hides_on_the_existing_image_open_error')
