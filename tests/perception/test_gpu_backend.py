"""GPU integer matching agrees with independent brute force, including bounds."""
import unittest
import numpy as np
from tests.support.touchsprite_adapter import Screen
from tests.perception.test_color_backend import brute

try:
    from tests.support.opencl_colors import GpuScreen
    AVAILABLE=GpuScreen.available()
except (ImportError,RuntimeError):
    AVAILABLE=False


@unittest.skipUnless(AVAILABLE, 'No OpenCL GPU')
class GpuBackendTest(unittest.TestCase):
    def test_batch_matches_independent_brute_force(self):
        class IsolatedGpu(GpuScreen):
            engine=None
            groups=None
            query_groups=None
        rng=np.random.default_rng(12)
        frame=rng.integers(0,256,(12,14,3),dtype=np.uint8)
        frame[4,10]=[100,100,100];frame[5,8]=[20,30,40]
        frame[7,3]=[125,100,100];frame[8,1]=[20,30,40]
        queries=[(0x646464,'-2|1|0x281e14',90,-2,-1,500,500),
                 (0x646464,'-2|1|0x281e14',10,-2,-1,500,500)]
        for _ in range(25):
            queries.append((int(rng.integers(0,0xffffff)), '-2|1|0x281e14,1|-2|0xdcd2c8',
                            90,-2,-1,500,500))
        IsolatedGpu.groups=[tuple(queries)]
        IsolatedGpu.query_groups={q:0 for q in queries}
        screen=IsolatedGpu(frame)
        for q in queries:
            actual=screen.find(*q)
            self.assertEqual(actual,brute(frame,q[0],q[1],q[3:]))
            self.assertEqual(actual,Screen(frame).find(*q))
        self.assertEqual(len(screen.cache),len(queries))
        fresh=IsolatedGpu(np.zeros_like(frame))
        self.assertEqual(fresh.find(*queries[0]),(-1,-1))
