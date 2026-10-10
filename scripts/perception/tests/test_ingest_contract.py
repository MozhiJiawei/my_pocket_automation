"""Collection data must neither overwrite reviewed labels nor create verified truth."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from scripts.perception.lib.corpus import image_path, load_cases
from scripts.perception.lib import ingest


class IngestContractTest(unittest.TestCase):
    def exercise(self, existing):
        case=deepcopy(load_cases('zhuagui')[0])
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder=root/'zhuagui'
            images=folder/'images/catalog'
            images.mkdir(parents=True)
            shutil.copy2(image_path(case),images/'sample.png')
            capture={'source_run':'fake_run','source_round':1,'question':'deliberately wrong collector label',
                     'topic':'黄金','frames':[{'image':'sample.png','sha256':case['sha256'],
                     'source':'debug-runs/fake_run/res/frame.png','hint_visible':True}]}
            (images/'manifest.json').write_text(json.dumps({'cases':[capture]}),encoding='utf-8')
            document={'schema_version':1,'cases':[case] if existing else []}
            (folder/'cases.json').write_text(json.dumps(document),encoding='utf-8')
            with patch.object(ingest,'ROOT',root): ingest.sync_catalog()
            result=json.loads((folder/'cases.json').read_text(encoding='utf-8'))
            return document,result

    def test_wrong_collector_label_cannot_overwrite_existing_truth(self):
        before,after=self.exercise(True)
        self.assertEqual(before,after)

    def test_new_machine_labels_are_only_proposals(self):
        _,after=self.exercise(False)
        case=after['cases'][0]
        self.assertEqual(case['truth']['page']['status'],'proposed')
        self.assertEqual(case['truth']['question']['status'],'proposed')
        self.assertEqual(case['truth']['target_regions']['status'],'pending')
