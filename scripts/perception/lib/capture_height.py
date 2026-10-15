"""Measure current source pixels without saving capture state."""
from pathlib import Path

from PIL import Image
from scripts.perception.lib.task_review import compose_rows


def height(folder,kind):
    folder=Path(folder);files=sorted(folder.glob('*.png'))
    if not files:raise ValueError('没有采集原图')
    if kind=='拼图':
        heights=[]
        for path in files:
            with Image.open(path) as image:heights.append(image.height)
        return min(heights)
    strip,_,_,_=compose_rows({i:{'id':p.name,'image':p.name} for i,p in enumerate(files)},lambda c:folder/c['image'])
    return strip.height


def complete(pixel_height,kind):
    return pixel_height>=(1600 if kind=='拼图' else 2760)
