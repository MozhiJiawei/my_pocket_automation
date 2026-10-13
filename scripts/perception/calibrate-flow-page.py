"""Extract a bounded UI signature from a visually inspected device capture."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--tap', required=True)
    parser.add_argument('--ink', choices=['white', 'light', 'dark'], default='white')
    args = parser.parse_args()
    frame = cv2.imdecode(np.fromfile(args.source, np.uint8), 1)
    x1, y1, x2, y2 = map(int, args.region.split(','))
    tx, ty = map(int, args.tap.split(','))
    crop = frame[y1:y2, x1:x2]
    mask = np.max(crop, axis=2)<130 if args.ink=='dark' else np.min(crop, axis=2)>(200 if args.ink=='light' else 220)
    pixels = np.column_stack(np.where(mask))[:, ::-1]
    if len(pixels)<24:
        raise ValueError('Insufficient glyph pixels')
    chosen = [0]
    for _ in range(23):
        distances = np.min(np.sum((pixels[:, None]-pixels[chosen][None, :])**2, axis=2), axis=1)
        chosen.append(int(np.argmax(distances)))
    points = pixels[chosen]+[x1, y1]
    ax, ay = map(int, points[0])
    def color(x, y):
        b, g, r = map(int, frame[y, x])
        return (r<<16)|(g<<8)|b
    offsets = ','.join(f'{x-ax}|{y-ay}|0x{color(x,y):06x}' for x, y in points[1:])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('return {width=%d,height=%d,base=0x%06x,offsets=%s,degree=95,region={%d,%d,%d,%d},tap_offset={%d,%d}}\n' % (
        frame.shape[1], frame.shape[0], color(ax,ay), json.dumps(offsets), ax-3, ay-3, ax+3, ay+3, tx-ax, ty-ay), encoding='utf-8')


if __name__=='__main__':
    main()
