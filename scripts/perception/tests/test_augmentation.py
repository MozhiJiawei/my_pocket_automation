"""Eight geometric variants inherit approved pixels and independent coordinates."""
import unittest
import numpy as np
import cv2
from scripts.perception.lib.corpus import load_cases,crop_sources,iter_variants,validate,transform


class AugmentationTest(unittest.TestCase):
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
