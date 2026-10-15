"""Import cannot approve predictions; corrections replace old coordinates."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import cv2
import numpy as np
from scripts.perception.lib import corpus
from scripts.perception.lib.ingest import import_frames,approve


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source.png'
        cv2.imencode('.png',np.full((1600,900,3),160,np.uint8))[1].tofile(self.source)
        self.context=patch.object(corpus,'ROOT',self.root/'testdata');self.context.start();self.addCleanup(self.context.stop)
        self.case='抓鬼/寻物/黄金/新界面'

    def test_import_is_pending_and_redacted(self):
        folder=import_frames([self.source],self.case,[[10,10,100,100]])
        case=corpus.load_cases()[0]
        self.assertTrue(all(a['status']=='pending' for a in case['truth'].values()))
        self.assertEqual(case['capture']['split'],'holdout')
        image=cv2.imdecode(np.fromfile(folder/'画面.png',dtype=np.uint8),1)
        self.assertFalse(image[:10].any());self.assertTrue(image[10:100,10:100].any())

    def test_import_does_not_overwrite_reviewed_case(self):
        import_frames([self.source],self.case,[[0,0,900,1600]])
        with self.assertRaises(ValueError):import_frames([self.source],self.case,[[0,0,900,1600]])

    def test_image_only_recognition_folder_cannot_masquerade_as_a_case(self):
        folder=self.root/'testdata'/self.case
        folder.mkdir(parents=True)
        (folder/'画面.png').write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError,'no approved answer file'):corpus.load_cases()

    def test_explicit_correction_replaces_stale_answer_and_preserves_history(self):
        folder=import_frames([self.source],self.case,[[0,0,900,1600]])
        approve(self.case,{'正确':{'金锭':{'画面.png':[10,10,40,40]}}},'user','confirmed first answer')
        approve(self.case,{'正确':{'金锭':{'画面.png':[50,50,80,80]}}},'user','corrected answer')
        case=corpus.load_cases()[0]
        self.assertEqual(case['truth']['target_regions']['value'],[[50,50,80,80]])
        self.assertEqual(case['capture']['split'],'holdout')
        self.assertIn('[10, 10, 40, 40]',(folder/'审核.md').read_text(encoding='utf-8'))

    def test_unapproved_or_invalid_proposal_does_not_write(self):
        folder=import_frames([self.source],self.case,[[0,0,900,1600]])
        before=(folder/'答案.json').read_bytes()
        for reviewer,box in [('',[10,10,20,20]),('user',[-10,10,20,20])]:
            with self.assertRaises(ValueError):approve(self.case,{'正确':{'金锭':{'画面.png':box}}},reviewer,'approval')
        self.assertEqual((folder/'答案.json').read_bytes(),before)
