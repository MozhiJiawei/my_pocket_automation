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
    def test_enumerated_subregions_and_overflow_match_cpu(self):
        class IsolatedGpu(GpuScreen):
            engine=None
            all_kernel=None
            groups=None
            query_groups=None
            all_queries={}
        frame=np.zeros((1600,900,3),dtype=np.uint8)
        for x,y in [(100,700),(400,1000),(700,1300)]:frame[y,x]=[10,30,210]
        query=(0xd21e0a,'1|0|0x000000',90,65,535,829,1410)
        IsolatedGpu.groups=[(query,)];IsolatedGpu.query_groups={query:0};IsolatedGpu.all_queries={query[:3]:(0,query)}
        overflowing=np.zeros_like(frame);overflowing[::2,::2]=[10,30,210]
        pictures=(frame,np.zeros_like(frame),overflowing)
        batch={'pixels':np.stack(pictures),'results':{}}
        for index,pixels in enumerate(pictures):
            screen=IsolatedGpu(pixels)
            screen.frame_batch=batch;screen.batch_index=index
            for region in [(65,535,829,1410),(101,535,829,1410),(400,999,500,1001),(101,701,200,800)]:
                q=(*query[:3],*region)
                self.assertEqual(screen.find(*q),Screen(pixels).find(*q))

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
