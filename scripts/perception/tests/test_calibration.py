"""Incremental distance updates retain the previously selected color points."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np


class CalibrationTest(unittest.TestCase):
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
