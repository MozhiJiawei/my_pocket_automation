"""Shared atomic command coordination uses only temporary local files."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DEVICE_SCRIPTS = ROOT / 'scripts/device'
if str(DEVICE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DEVICE_SCRIPTS))

from dfx_device import allocate_run_id, instance_lock


class AtomicCoordinationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mumu_dir = self.root / 'mumu'

    def test_same_installation_and_vm_exclude_a_second_command(self):
        with instance_lock(self.root, self.mumu_dir, 5):
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with instance_lock(self.root, self.mumu_dir / '..' / 'mumu', 5):
                    self.fail('A second command acquired the selected instance')
        with instance_lock(self.root, self.mumu_dir, 5):
            pass

    def test_different_instances_and_installations_do_not_share_a_lock(self):
        with instance_lock(self.root, self.mumu_dir, 5):
            with instance_lock(self.root, self.mumu_dir, 6):
                with instance_lock(self.root, self.root / 'another-mumu', 5):
                    pass

    def test_failed_command_releases_the_instance_lock(self):
        with self.assertRaisesRegex(RuntimeError, 'command fault'):
            with instance_lock(self.root, self.mumu_dir, 5):
                raise RuntimeError('command fault')
        with instance_lock(self.root, self.mumu_dir, 5):
            pass

    def test_invalid_lock_identity_is_rejected_without_creating_evidence(self):
        for vm_index, mumu_dir in ((-1, self.mumu_dir), (True, self.mumu_dir),
                                   ('5', self.mumu_dir), (5, Path('relative-mumu'))):
            with self.subTest(vm_index=vm_index, mumu_dir=mumu_dir):
                with self.assertRaises(ValueError):
                    with instance_lock(self.root, mumu_dir, vm_index):
                        self.fail('Invalid instance identity was accepted')
        self.assertFalse((self.root / 'debug-runs').exists())

    def test_run_ids_are_atomically_reserved_across_targets(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda _index: allocate_run_id(self.root), range(24)))
        self.assertEqual(len(set(ids)), 24)
        for run_id in ids:
            self.assertRegex(run_id, r'^\d{8}_\d{6}$')
            self.assertFalse((self.root / 'debug-runs' / run_id).exists())
            self.assertEqual((self.root / 'debug-runs/run-ids' / run_id).read_text(encoding='ascii'), run_id)

    def test_existing_archive_and_reserved_id_are_never_reused(self):
        old_archive = self.root / 'debug-runs/20261103_120000'
        old_archive.mkdir(parents=True)
        prior = old_archive / 'result.json'
        prior.write_text('{"prior":true}', encoding='utf-8')
        reservations = self.root / 'debug-runs/run-ids'
        reservations.mkdir()
        (reservations / '20261103_120001').write_text('reserved', encoding='ascii')
        with patch('dfx_device.datetime') as clock:
            clock.now.return_value = datetime(2026, 11, 3, 12)
            self.assertEqual(allocate_run_id(self.root), '20261103_120002')
        self.assertEqual(prior.read_text(encoding='utf-8'), '{"prior":true}')
        self.assertEqual((reservations / '20261103_120001').read_text(encoding='ascii'), 'reserved')


if __name__ == '__main__':
    unittest.main()
