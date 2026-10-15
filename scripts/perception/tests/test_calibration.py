"""Incremental distance updates retain the previously selected color points."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
from lupa import LuaRuntime


class CalibrationTest(unittest.TestCase):
    def test_named_wine_banks_use_confirmed_sources_of_the_same_wine(self):
        root=Path(__file__).resolve().parents[3]
        lua=LuaRuntime()
        catalog=lua.execute((root/'src/tasks/zhuagui/assets/catalog.lua').read_text(encoding='utf-8'))
        for topic,key in [('虎骨酒','tiger_wine'),('蛇胆酒','snake_wine'),('梅花酒','plum_wine'),('珍露酒','dew_wine')]:
            with self.subTest(topic=topic):
                bank=catalog[key]
                self.assertTrue(bank and len(bank)>0)
                self.assertTrue(all('/'+topic+'/' in entry['calibration_id'] for entry in bank.values()))

    def test_ghost_resource_preserves_unicode_evidence_and_confirmed_skeleton(self):
        root=Path(__file__).resolve().parents[3]
        bank=LuaRuntime().execute((root/'src/tasks/zhuagui/assets/reviewed_ghosts.lua').read_text(encoding='utf-8'))
        self.assertIn('骷髅怪',bank['skeleton'][1]['calibration_id'])

    def test_signature_selection_is_unchanged(self):
        path=Path(__file__).resolve().parents[1]/'calibrate-reviewed-items.py'
        spec=importlib.util.spec_from_file_location('calibrate_items',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        crop=np.random.default_rng(7).integers(0,256,(64,64,3),dtype=np.uint8)
        expected=[(20,12),(46,52),(15,52),(45,15),(20,28),(40,31),(22,40),(39,22),
                  (29,36),(51,25),(29,46),(47,44),(17,23),(13,22),(37,15),(14,27),
                  (13,42),(24,26),(48,36),(14,33),(52,21),(29,17),(51,12),(36,53)]
        points=module.sample(crop)
        self.assertEqual([(x,y) for x,y,color in points],expected)
        for x,y,color in points:
            b,g,r=map(int,crop[y,x]);self.assertEqual(color,(r<<16)|(g<<8)|b)
