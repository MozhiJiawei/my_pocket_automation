"""Capture completeness is a read-only comparison of source-pixel height."""
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from PIL import Image
from scripts.perception.lib import annotation_queue as queue,capture_height


class CaptureHeightTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=queue.ROOT/'.tmp');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def write_frames(self,offsets,thumb=True):
        for path in self.folder.glob('第*页.png'):path.unlink()
        for page,offset in enumerate(offsets,1):
            frame=np.full((1600,900,3),(229,180,164),np.uint8)
            cv2.putText(frame,'FIND THE WINE',(80,385),cv2.FONT_HERSHEY_SIMPLEX,1,(20,20,20),3)
            body=frame.copy()
            for row in range(20):
                top=537+row*156-offset
                for column in range(5):
                    left=64+column*156
                    cv2.rectangle(body,(left,top),(left+138,top+138),(245,220,205),1)
                    if 0<=top+20 and top+120<=1600:
                        texture=np.random.default_rng(row*5+column).integers(0,220,(8,8,3),dtype=np.uint8)
                        body[top+20:top+120,left+20:left+120]=cv2.resize(texture,(100,100),interpolation=cv2.INTER_NEAREST)
            frame[527:1402,63:826]=body[527:1402,63:826]
            if thumb:
                start=round(527+offset*(875-246)/2245)
                frame[max(527,start):min(1402,start+246),828:832]=(184,140,108)
            cv2.imencode('.png',frame,[cv2.IMWRITE_PNG_COMPRESSION,1])[1].tofile(self.folder/f'第{page:02d}页.png')

    def test_inventory_height_boundary_is_shared_by_recognition_types(self):
        for kind in ('寻物','找鬼'):
            for height,complete in ((2759,False),(2760,True),(2761,True)):
                with self.subTest(kind=kind,height=height):
                    self.assertEqual(capture_height.complete(height,kind),complete)

    def test_complete_strip_deduplicates_bottom_page_without_a_scrollbar(self):
        self.write_frames([0,624,1248,1872,2245,2245],thumb=False)
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()}
        height=capture_height.height(self.folder,'寻物')
        self.assertEqual(height,2760)
        self.assertTrue(capture_height.complete(height,'寻物'))
        self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()},before)

    def test_missing_middle_or_repeating_one_page_does_not_meet_threshold(self):
        for offsets,expected in (([0,624,1872,2245,2245],2346),([0]*7,690)):
            with self.subTest(offsets=offsets):
                self.write_frames(offsets)
                height=capture_height.height(self.folder,'寻物')
                self.assertEqual(height,expected)
                self.assertFalse(capture_height.complete(height,'寻物'))

    def test_height_uses_current_pixels_and_ignores_prompt_pixels(self):
        self.write_frames([0,624,1248,1872,2245,2245])
        path=self.folder/'第03页.png';frame=cv2.imdecode(np.fromfile(path,np.uint8),1)
        frame[325:425,63:610]=(0,0,0);cv2.imencode('.png',frame)[1].tofile(path)
        self.assertEqual(capture_height.height(self.folder,'寻物'),2760)
        Image.new('RGB',(900,1600),'blue').save(path)
        self.assertLess(capture_height.height(self.folder,'寻物'),2760)

    def test_puzzle_uses_the_shortest_png_including_named_originals(self):
        Image.new('RGB',(900,1601),'blue').save(self.folder/'第01页.png')
        for height,complete in ((1599,False),(1600,True),(1601,True)):
            with self.subTest(height=height):
                Image.new('RGB',(900,height),'red').save(self.folder/'画面.png')
                measured=capture_height.height(self.folder,'拼图')
                self.assertEqual(measured,height)
                self.assertEqual(capture_height.complete(measured,'拼图'),complete)

    def test_height_and_comparison_have_no_file_side_effects(self):
        Image.new('RGB',(900,1600),'blue').save(self.folder/'第01页.png')
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()}
        for _ in range(2):
            self.assertTrue(capture_height.complete(capture_height.height(self.folder,'拼图'),'拼图'))
        self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.folder.iterdir()},before)

    def test_missing_and_unreadable_originals_fail(self):
        for kind in ('寻物','拼图'):
            with self.subTest(kind=kind),self.assertRaises(ValueError):capture_height.height(self.folder,kind)
        (self.folder/'第01页.png').write_bytes(b'broken png')
        for kind in ('寻物','拼图'):
            with self.subTest(kind=kind),self.assertRaises((ValueError,OSError)):capture_height.height(self.folder,kind)
