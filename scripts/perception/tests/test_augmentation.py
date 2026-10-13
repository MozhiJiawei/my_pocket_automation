"""Eight geometric variants inherit approved pixels and independent coordinates."""
import unittest
import numpy as np
import cv2
import json
from copy import deepcopy
from scripts.perception.lib.corpus import ROOT
from scripts.perception.lib.corpus import load_cases,crop_sources,iter_variants,validate,transform


class AugmentationTest(unittest.TestCase):
    def test_shimen_transforms_every_approved_region_together(self):
        case=next(c for c in load_cases('shimen') if c['truth'].get('target_regions',{}).get('value'))
        crops=crop_sources([case])[case['id']]
        self.assertEqual(len(crops),sum(len(case['truth'].get(k,{}).get('value') or []) for k in ('target_regions','negative_regions')))
        original=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
        variants=list(iter_variants(case,crops,original,persist=False));self.assertEqual(len(variants),8)
        buffer=np.empty((8,*original.shape),dtype=original.dtype)
        buffered=list(iter_variants(case,crops,original,persist=False,canvases=buffer))
        for (expected_doc,expected),(actual_doc,actual) in zip(variants,buffered):
            self.assertEqual(expected_doc,actual_doc)
            self.assertTrue(np.array_equal(expected,actual))
            self.assertTrue(np.shares_memory(actual,buffer))
        for variant,pixels in variants:
            self.assertEqual(variant['truth'],case['truth'])
            for crop in crops:
                x1,y1,x2,y2=crop['region']
                np.testing.assert_array_equal(pixels[y1:y2,x1:x2],transform(original[y1:y2,x1:x2],variant['augmentation']['mirror'],variant['augmentation']['turn']))
            np.testing.assert_array_equal(pixels[:535],original[:535])
    def test_all_eight_orientations_preserve_pixels(self):
        tile=np.arange(18,dtype=np.uint8).reshape(2,3,3)
        variants=[transform(tile,mirror,turn) for mirror in (False,True) for turn in range(4)]
        self.assertEqual(len({(v.shape,v.tobytes()) for v in variants}),8)
        for v in variants:self.assertEqual(sorted(v.ravel()),sorted(tile.ravel()))

    def test_approved_crop_geometry_and_parent_split(self):
        cases=load_cases('zhuagui');sources=crop_sources(cases)
        case=next(c for c in cases if c['id'] in sources)
        crop=sources[case['id']][0]
        variants=list(iter_variants(case,[crop]));self.assertEqual(len(variants),8)
        original=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
        transient=list(iter_variants(case,[crop],original,persist=False))
        x1,y1,x2,y2=crop['region'];tile=original[y1:y2,x1:x2]
        for variant,(in_memory,pixels) in zip(variants,transient):
            a=variant['augmentation'];x,y,right,bottom=a['destination']
            image=cv2.imdecode(np.fromfile(validate(variant),dtype=np.uint8),1)
            self.assertEqual(variant,in_memory)
            np.testing.assert_array_equal(image,pixels)
            np.testing.assert_array_equal(image[y:bottom,x:right],transform(tile,a['mirror'],a['turn']))
            np.testing.assert_array_equal(image[174:433],original[174:433])
            self.assertEqual(variant['capture']['split'],case['capture']['split'])
            field='target_regions' if crop['positive'] else 'negative_regions'
            self.assertEqual(variant['truth'][field]['value'],[a['destination']])

    def test_pending_regions_never_create_variants(self):
        cases=[c for c in load_cases('zhuagui') if '/待审核/' in c['id']]
        self.assertTrue(cases);self.assertEqual(crop_sources(cases),{})

    def test_puzzle_permutations_preserve_pixels_and_canonical_answer(self):
        case=next(c for c in load_cases('zhuagui') if 'puzzle_order' in c['truth'])
        original=cv2.imdecode(np.fromfile(validate(case),dtype=np.uint8),1)
        cells=json.loads((ROOT/'抓鬼/拼图/格位.json').read_text(encoding='utf-8'))
        tiles=[original[y1:y2,x1:x2].copy() for x1,y1,x2,y2 in cells]
        canonical=[tiles[ord(letter)-65] for letter in case['truth']['puzzle_order']['value']]
        seen={(0,1,2,3)}
        for derived,pixels in iter_variants(case,[],original,persist=False):
            permutation=tuple(derived['augmentation']['permutation'])
            self.assertNotIn(permutation,seen);seen.add(permutation)
            for letter,expected in zip(derived['truth']['puzzle_order']['value'],canonical):
                x1,y1,x2,y2=cells[ord(letter)-65]
                np.testing.assert_array_equal(pixels[y1:y2,x1:x2],expected)
            np.testing.assert_array_equal(pixels[:500],original[:500])
            self.assertEqual(derived['capture']['split'],case['capture']['split'])
        self.assertEqual(len(seen),24)
        pending=deepcopy(case);pending['truth']['puzzle_order']['status']='proposed'
        self.assertEqual(list(iter_variants(pending,[],original,persist=False)),[])
