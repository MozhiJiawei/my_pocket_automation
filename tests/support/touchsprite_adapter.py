"""Host approximation of TS colors. Degree is recorded, NOT claimed emulated.

The historical max-channel tolerance of 25 is retained for baseline comparison.
On-device API behavior must be measured separately before changing this contract.
"""
import cv2
import numpy as np

cv2.setNumThreads(1)
CONTRACT = {'backend': 'host_max_channel_25_v1', 'degree_emulated': False,
            'device_equivalent': False, 'channel_tolerance': 25}


class Screen:
    def __init__(self, frame):
        self.frame = frame
        self.matches = []
        self.cache = {}
        self.anchor_key = None
        self.anchor_candidates = None

    @classmethod
    def read(cls, path):
        frame = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f'Unreadable frame: {path}')
        return cls(frame)

    def color(self, x, y):
        b, g, r = map(int, self.frame[int(y), int(x)])
        return (r << 16) | (g << 8) | b

    def find(self, base, offsets, degree, x1, y1, x2, y2):
        key = (int(base), offsets, degree, int(x1), int(y1), int(x2), int(y2))
        if key not in self.cache:
            self.cache[key] = self._find(*key)
        result = self.cache[key]
        self.matches.append({'feature': hashlib_id(key), 'degree': degree,
                             'region': list(key[3:]), 'position': list(result)})
        return result

    def _find(self, base, offsets, degree, x1, y1, x2, y2):
        height, width = self.frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width - 1, x2), min(height - 1, y2)
        if x2 < x1 or y2 < y1:
            return -1, -1
        points = [(0, 0, base)] + [
            (int(x), int(y), int(c, 16)) for x, y, c in (s.split('|') for s in offsets.split(','))]
        # Consecutive rotated features share the base color and region. Keep
        # only the last anchor scan, including misses, for this immutable frame.
        anchor_key = (base, x1, y1, x2, y2)
        if anchor_key != self.anchor_key:
            expected = (base & 255, (base >> 8) & 255, (base >> 16) & 255)
            mask = cv2.inRange(self.frame[y1:y2+1,x1:x2+1],
                               tuple(max(0,c-25) for c in expected),
                               tuple(min(255,c+25) for c in expected))
            self.anchor_candidates = cv2.findNonZero(mask)
            self.anchor_key = anchor_key
        candidates = self.anchor_candidates
        if candidates is None:
            return -1, -1
        candidates = candidates.reshape(-1, 2)
        xx = candidates[:, 0] + x1
        yy = candidates[:, 1] + y1
        for dx, dy, color in points[1:]:
            px, py = xx + dx, yy + dy
            valid = (px >= 0) & (px < width) & (py >= 0) & (py < height)
            xx,yy,px,py = xx[valid],yy[valid],px[valid],py[valid]
            if not len(xx):
                return -1,-1
            pixels = self.frame[py,px].astype(np.int16)
            expected = np.array([color & 255, (color >> 8) & 255, (color >> 16) & 255])
            valid = np.max(np.abs(pixels - expected), axis=1) <= 25
            xx,yy = xx[valid],yy[valid]
            if not len(xx):
                return -1, -1
        if not len(xx):
            return -1, -1
        # Preserve the historical host backend's row-major first match without
        # depending on OpenCV's candidate order.
        first = np.argmin(yy * width + xx)
        return int(xx[first]), int(yy[first])


def hashlib_id(key):
    import hashlib
    return hashlib.sha256(repr(key).encode()).hexdigest()[:12]
