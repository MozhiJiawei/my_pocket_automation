"""Sparse matching must preserve the historical max-channel-25 contract."""
import unittest
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


if __name__=='__main__': unittest.main()
