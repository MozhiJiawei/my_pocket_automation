from __future__ import annotations
from pathlib import Path
import cv2
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
TAP=(1534,716)
def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Unreadable image')
    return image

def template_match(image: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int]]:
    scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, pos = cv2.minMaxLoc(scores)
    return (float(score), pos)

class OCRProbe:
    def __init__(self,engine):self.ocr_engine=engine
    def ocr(self,image):return self.ocr_engine(image)
    def ocr_locator(self, image: np.ndarray) -> tuple[tuple[int, int] | None, dict]:
        h, w = image.shape[:2]
        left, top = (int(w * 0.75), int(h * 0.5))
        output = self.ocr(image[top:, left:])
        candidates = []
        target_scores = []
        refinement_used = False
        if output.txts is not None:
            for box, text, score in zip(output.boxes, output.txts, output.scores):
                accepted = text.replace(' ', '') == '口袋' and float(score) >= 0.8
                if not accepted and '袋' in text:
                    bx1, by1 = np.floor(np.min(box, axis=0)).astype(int)
                    bx2, by2 = np.ceil(np.max(box, axis=0)).astype(int)
                    crop = image[max(0, by1 + top - 20):min(h, by2 + top + 20), max(0, bx1 + left - 20):min(w, bx2 + left + 20)]
                    refined = self.ocr(cv2.resize(crop, None, fx=2, fy=2))
                    refinement_used = True
                    for refined_text, refined_score in zip(refined.txts or [], refined.scores if refined.scores is not None else []):
                        if refined_text.replace(' ', '') == '口袋' and float(refined_score) >= 0.8:
                            accepted, score = (True, refined_score)
                if accepted:
                    center = np.mean(box, axis=0)
                    candidates.append((round(float(center[0])) + left, round(float(center[1])) + top))
                    target_scores.append(round(float(score), 4))
        tile_rescan_used = not candidates
        if tile_rescan_used:
            mid_x, mid_y = ((left + w) // 2, (top + h) // 2)
            for tx1, ty1, tx2, ty2 in ((left, top, mid_x + 24, mid_y + 24), (mid_x - 24, top, w, mid_y + 24), (left, mid_y - 24, mid_x + 24, h), (mid_x - 24, mid_y - 24, w, h)):
                tiled = self.ocr(cv2.resize(image[ty1:ty2, tx1:tx2], None, fx=2, fy=2))
                for box, text, confidence in zip(tiled.boxes if tiled.boxes is not None else [], tiled.txts or [], tiled.scores if tiled.scores is not None else []):
                    if text.replace(' ', '') != '口袋' or float(confidence) < 0.8:
                        continue
                    center = np.mean(box, axis=0) / 2
                    point = (round(float(center[0])) + tx1, round(float(center[1])) + ty1)
                    if not any((abs(point[0] - other[0]) < 15 and abs(point[1] - other[1]) < 15 for other in candidates)):
                        candidates.append(point)
                        target_scores.append(round(float(confidence), 4))
        return (candidates[0] if len(candidates) == 1 else None, {'target_count': len(candidates), 'target_scores': target_scores, 'refinement_used': refinement_used, 'tile_rescan_used': tile_rescan_used})
