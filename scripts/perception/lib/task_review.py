"""Recover capture rounds and register scrolling content, without inferring answers."""
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np

VIEWPORT = (63, 535, 829, 1410)
ALIGNMENT_METHOD = 'scroll_overlap_mae_v2_bidirectional'


def rounds(cases):
    groups = defaultdict(dict)
    for case in cases:
        if case['capture']['origin'] != 'device':
            continue
        folder = str(Path(case['image']).parent).replace(chr(92), '/')
        page=case['truth'].get('page',{}).get('value')
        if page!='find' and not (page is None and '/寻物/' in folder):continue
        groups[folder][len(groups[folder])+1] = case
    return groups


def scroll_offset(previous, current):
    """Estimate vertical scroll; compare content over overlap, not fixed UI or timer.

    Negative shifts also cover scroll rebound at the bottom. At least 32 shared pixel rows
    and a normalized mean absolute error below 18 are required for stitching.
    """
    previous = cv2.resize(np.asarray(previous), (96, previous.height)).astype(np.float32)
    current = cv2.resize(np.asarray(current), (96, current.height)).astype(np.float32)
    height = min(len(previous), len(current))
    candidates = []
    for offset in range(-height + 32, height - 32):
        begin = max(0, offset)
        end = min(height, height + offset)
        # Exclude the clipping edges: the UI fades partially visible tiles.
        if end - begin < 32:
            continue
        left = previous[begin + 6:end - 6, 4:-4]
        right = current[begin - offset + 6:end - offset - 6, 4:-4]
        error = float(np.mean(np.abs(left - right)))
        candidates.append((error, offset, end - begin))
    error, offset, overlap = min(candidates)
    return {'offset': offset, 'overlap': overlap, 'error': round(error, 4),
            'accepted': error < 18, 'method': ALIGNMENT_METHOD}
