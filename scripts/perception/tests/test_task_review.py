"""Review strips remove redundant scrolling without replacing original truth."""
import importlib.util
from pathlib import Path
import unittest
from scripts.perception.lib.corpus import load_cases
from scripts.perception.lib.task_review import rounds

spec=importlib.util.spec_from_file_location('review',Path(__file__).parents[1]/'render_task_review.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


class TaskReviewTest(unittest.TestCase):
    def test_scroll_scratch_buffer_preserves_alignment_result(self):
        import cv2
        import numpy as np
        from PIL import Image
        from scripts.perception.lib.task_review import scroll_offset,ALIGNMENT_METHOD
        rng=np.random.default_rng(7)
        for channels in ((),(3,)):
            pixels=rng.integers(0,256,(63,120)+channels,dtype=np.uint8)
            first=Image.fromarray(pixels)
            second=Image.fromarray(np.roll(pixels,11,axis=0))
            left=cv2.resize(np.asarray(first),(96,63)).astype(np.float32)
            right=cv2.resize(np.asarray(second),(96,63)).astype(np.float32)
            scores=[]
            for offset in range(-63+32,63-32):
                begin=max(0,offset);end=min(63,63+offset)
                error=float(np.mean(np.abs(left[begin+6:end-6,4:-4]-right[begin-offset+6:end-offset-6,4:-4])))
                scores.append((error,offset,end-begin))
            error,offset,overlap=min(scores)
            self.assertEqual(scroll_offset(first,second),
                             {'offset':offset,'overlap':overlap,'error':round(error,4),
                              'accepted':error<18,'method':ALIGNMENT_METHOD})

    def test_row_shift_candidates_keep_the_same_content_and_match_checks(self):
        import numpy as np
        from scripts.perception.lib.task_review import matching_row,row_matches
        rng=np.random.default_rng(8)
        textured=rng.integers(0,256,(24,126,3)).astype(np.float32)
        for left in (textured,np.zeros_like(textured)):
            for delta in (0,7,20):
                for shifted in ([],[left+20],[left+20,left+5]):
                    right={'sample':left+delta,'shifted_samples':shifted}
                    expected=any(row_matches(left,sample) for sample in (right['sample'],*right['shifted_samples']))
                    self.assertEqual(matching_row({'sample':left},right),expected)

    def test_repeated_bottom_pages_do_not_repeat_in_long_strip(self):
        pages=rounds(load_cases('zhuagui'))['抓鬼/寻物/上好的兵器/第02轮']
        strip,records,_=review.compose(pages)
        self.assertGreater(len(records),1)
        self.assertTrue(any(r['redundant_capture'] for r in records))
        self.assertLess(strip.height,len(records)*875)
        self.assertTrue(all(r['alignment'] is None or r['alignment']['accepted'] for r in records))
