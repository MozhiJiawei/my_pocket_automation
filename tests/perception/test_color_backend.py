"""Sparse matching must preserve the historical max-channel-25 contract."""
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from tests.support.touchsprite_adapter import Screen


def brute(frame, base, offsets, box):
    height,width=frame.shape[:2]
    points=[(0,0,base)]+[(int(x),int(y),int(c,16)) for x,y,c in
                          (s.split('|') for s in offsets.split(','))]
    for y in range(max(0,box[1]),min(height-1,box[3])+1):
        for x in range(max(0,box[0]),min(width-1,box[2])+1):
            ok=True
            for dx,dy,c in points:
                px,py=x+dx,y+dy
                expected=np.array([c&255,(c>>8)&255,(c>>16)&255])
                if not (0<=px<width and 0<=py<height) or np.max(np.abs(frame[py,px].astype(int)-expected))>25:
                    ok=False; break
            if ok: return x,y
    return -1,-1


class ColorBackendTest(unittest.TestCase):
    def test_random_matches_and_edge_offsets_equal_independent_brute_force(self):
        rng=np.random.default_rng(42)
        for _ in range(60):
            frame=rng.integers(0,256,(12,14,3),dtype=np.uint8)
            base=int(rng.integers(0,0xffffff))
            offsets=f'-2|1|0x{int(rng.integers(0,0xffffff)):06x},1|-2|0x{int(rng.integers(0,0xffffff)):06x}'
            box=[-2,-1,14,12]
            self.assertEqual(Screen(frame)._find(base,offsets,90,*box),brute(frame,base,offsets,box))

    def test_threshold_first_match_and_out_of_image_offsets(self):
        frame=np.zeros((10,10,3),dtype=np.uint8)
        frame[2,3]=[125,100,100]; frame[2,4]=[20,30,40]
        frame[3,3]=[126,100,100]; frame[3,4]=[20,30,40]
        args=(0x646464,'1|0|0x281e14',90,0,0,9,9)
        self.assertEqual(Screen(frame)._find(*args),(3,2))
        self.assertEqual(Screen(frame)._find(0,'-1|0|0x000000',90,0,0,0,0),(-1,-1))
        self.assertEqual(Screen(frame)._find(0,'0|0|0x000000',90,5,5,4,4),(-1,-1))

    def test_planted_matches_equal_brute_force(self):
        rng = np.random.default_rng(7)
        for _ in range(40):
            frame = rng.integers(0, 256, (12, 14, 3), dtype=np.uint8)
            for x, y in ((10, 4), (3, 7)):
                frame[y, x] = [100, 100, 100]
                frame[y + 1, x - 2] = [20, 30, 40]
                frame[y - 2, x + 1] = [200, 210, 220]
            offsets = '-2|1|0x281e14,1|-2|0xdcd2c8'
            box = [2, 2, 11, 9]
            self.assertEqual(Screen(frame)._find(0x646464, offsets, 90, *box),
                             brute(frame, 0x646464, offsets, box))

    def test_candidate_order_and_offsets_outside_search_region(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        native = cv2.findNonZero
        with patch('tests.support.touchsprite_adapter.cv2.findNonZero',
                   side_effect=lambda mask: native(mask)[::-1]):
            self.assertEqual(Screen(frame)._find(0, '-1|0|0', 90, 2, 3, 7, 8), (2, 3))

    def test_anchor_reuse_including_misses_and_frame_isolation(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        screen = Screen(frame)
        with patch('tests.support.touchsprite_adapter.cv2.findNonZero',
                   wraps=cv2.findNonZero) as scan:
            for offsets in ('1|0|0', '-1|0|0'):
                self.assertEqual(screen._find(0, offsets, 90, 2, 3, 7, 8), (2, 3))
            self.assertEqual(scan.call_count, 1)
            for offsets in ('1|0|0', '-1|0|0'):
                self.assertEqual(screen._find(0xffffff, offsets, 90, 2, 3, 7, 8), (-1, -1))
            self.assertEqual(scan.call_count, 2)
            screen._find(0xffffff, '0|0|0', 90, 0, 0, 9, 9)
            self.assertEqual(scan.call_count, 3)
        self.assertEqual(Screen(np.full_like(frame, 255))._find(
            0xffffff, '0|0|0xffffff', 90, 2, 3, 7, 8), (2, 3))


if __name__=='__main__': unittest.main()
