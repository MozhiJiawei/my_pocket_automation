"""Review grouping must ignore tile order and preserve all original inputs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np

PATH=Path(__file__).resolve().parents[1]/'review-puzzles.py'
spec=importlib.util.spec_from_file_location('puzzle_review',PATH)
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)

class PuzzleReviewTest(unittest.TestCase):
    def write_board(self,folder,name,order,colors):
        frame=np.full((1600,900,3),210,np.uint8)
        for box,piece in zip(review.CELLS,order):
            x1,y1,x2,y2=box;frame[y1:y2,x1:x2]=colors[piece]
        path=Path(folder)/name
        cv2.imencode('.png',frame)[1].tofile(path)
        return path

    def test_rearrangement_is_one_pattern_and_sources_remain_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            colors=((30,60,90),(120,40,60),(20,180,70),(150,80,30))
            first=self.write_board(folder,'first.png',(0,1,2,3),colors)
            second=self.write_board(folder,'second.png',(2,0,3,1),colors)
            groups=review.grouping([first,second])
            self.assertEqual(len(groups),1)
            self.assertEqual(len(groups[0]['sources']),2)
            self.assertEqual(groups[0]['sources'][1]['current_to_reference'],[3,1,4,2])
            self.assertTrue(first.exists() and second.exists())

    def test_different_pictures_are_not_merged(self):
        with tempfile.TemporaryDirectory() as folder:
            first=self.write_board(folder,'first.png',(0,1,2,3),((0,0,0),)*4)
            second=self.write_board(folder,'second.png',(0,1,2,3),((200,200,200),)*4)
            self.assertEqual(len(review.grouping([first,second])),2)

if __name__=='__main__':unittest.main()
