"""Generate deduplicated review strips. Original coordinates remain the only truth."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.perception.lib.corpus import image_path,load_cases,read_answers,regions
from scripts.perception.lib.task_review import VIEWPORT,rounds,scroll_offset,compose_rows,item_cells


def compose(pages, with_sources=False):
    if pages:
        import numpy as np
        first=pages[min(pages)]
        if item_cells(np.asarray(Image.open(image_path(first)).convert('RGB'))):
            result=compose_rows(pages)
            return result if with_sources else result[:3]
    return _compose_pixels(pages,with_sources)

def _compose_pixels(pages, with_sources=False):
    images = [(page, case, Image.open(image_path(case)).convert('RGB'))
              for page, case in sorted(pages.items())]
    segments, records, previous, position = [], [], None, 0
    height = 0
    sources_map = []
    for capture_index, (page, case, frame) in enumerate(images):
        crop = frame.crop(VIEWPORT)
        alignment = None if previous is None else scroll_offset(previous, crop)
        if alignment and alignment['accepted']:
            position += alignment['offset']
            if position < 0:
                raise ValueError('Scroll moved before the beginning of the capture')
        elif previous is not None:
            position = height + 60
        extension = position + crop.height - height
        duplicated = previous is not None and alignment['accepted'] and extension <= 32
        if not duplicated:
            source_start = max(0, height - position)
            destination=height if source_start else position
            segments.append((destination, crop.crop((0, source_start, crop.width, crop.height))))
            sources_map.append({'image':Path(case['image']).name,
                                'source':[VIEWPORT[0],VIEWPORT[1]+source_start,VIEWPORT[2],VIEWPORT[3]],
                                'destination':[0,destination,crop.width,destination+crop.height-source_start]})
            height = max(height, position + crop.height)
        records.append({'page': page, 'case_id': case['id'],
                        'list_origin_y': position, 'alignment': alignment,
                        'redundant_capture': duplicated, 'added_pixel_rows': 0 if duplicated else max(0, extension),
                        'viewport': list(VIEWPORT)})
        previous = crop
    if not images:
        return None
    strip = Image.new('RGB', (VIEWPORT[2] - VIEWPORT[0], height), '#40556d')
    for y, crop in segments:
        strip.paste(crop, (0, y))
    # A seam through the faded viewport edge can obscure an icon. Prefer a
    # whole row from a capture where that row is fully inside the viewport.
    if all(record['alignment'] is None or record['alignment']['accepted'] for record in records):
        sources = [(record, frame.crop(VIEWPORT)) for record, (_, _, frame) in zip(records, images)]
        for row in range((height + 155) // 156):
            top = 3 + round(row * 155.8)
            bottom = min(height, 3 + round((row + 1) * 155.8))
            eligible = [(abs((top+bottom)/2 - record['list_origin_y'] - crop.height/2), record, crop)
                        for record, crop in sources
                        if top >= record['list_origin_y'] + 5 and bottom <= record['list_origin_y'] + crop.height - 5]
            if eligible and bottom > top:
                _, record, crop = min(eligible, key=lambda item: item[0])
                strip.paste(crop.crop((0, top-record['list_origin_y'], crop.width, bottom-record['list_origin_y'])), (0, top))
                sources_map.append({'image':Path(record['case_id']).name,
                    'source':[VIEWPORT[0],VIEWPORT[1]+top-record['list_origin_y'],VIEWPORT[2],VIEWPORT[1]+bottom-record['list_origin_y']],
                    'destination':[0,top,crop.width,bottom]})
    result=(strip, records, images[0][2])
    return (*result,sources_map) if with_sources else result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--topic')
    parser.add_argument('--case',help='Readable case directory')
    parser.add_argument('--proposal',type=Path,help='Unapproved local answer proposal; drawn in orange')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.proposal and not args.case:parser.error('--proposal requires one --case')
    output=(args.output or ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-review').resolve()
    if not output.is_relative_to((ROOT/'debug-runs').resolve()):parser.error('Output must stay in debug-runs')
    output.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',18)
    lines=['# 原图真值审核','', '绿框为正式正确答案，蓝框为明确反例；未框选位置仍为未知。','']
    cases=load_cases();groups=rounds(cases)
    if args.case:
        selected=[c for c in cases if str(Path(c['image']).parent).replace(chr(92),'/')==args.case]
        if not selected:parser.error('No input images in the selected case')
        groups[args.case]={i:c for i,c in enumerate(selected,1)}
    for identity,pages in groups.items():
        if args.case and identity!=args.case:continue
        if args.topic and (pages[1]['truth'].get('question',{}).get('value') or {}).get('target')!=args.topic:continue
        strip,records,header,layers=compose(pages,with_sources=True)
        draw=ImageDraw.Draw(strip)
        documents=[(read_answers(ROOT/'testdata'/identity),'green','blue')]
        if args.proposal:
            documents.append((json.loads(args.proposal.read_text(encoding='utf-8')),'orange','orange'))
        for layer in layers:
            for document,positive,negative in documents:
                for section,color in [('正确',positive),('反例',negative)]:
                    for label,locations in document.get(section,{}).items():
                        for alias in layer.get('aliases',[layer]):
                            sx,sy,ex,ey=alias['source'];dx,dy,_,_=layer['destination']
                            for x1,y1,x2,y2 in regions(locations.get(alias['image'],[])):
                                if not (sx<=x1<x2<=ex and sy<=y1<y2<=ey):continue
                                box=[x1-sx+dx,y1-sy+dy,x2-sx+dx,y2-sy+dy]
                                draw.rectangle(box,outline=color,width=4)
                                draw.text((box[0],box[1]),label,font=font,fill=color,stroke_width=1,stroke_fill='white')
        hint=header.crop((VIEWPORT[0],245,VIEWPORT[2],450))
        sheet=Image.new('RGB',(strip.width,strip.height+hint.height),'#40556d')
        sheet.paste(hint,(0,0));sheet.paste(strip,(0,hint.height))
        target=output/identity/'审核长图.png';target.parent.mkdir(parents=True,exist_ok=True)
        sheet.save(target)
        lines.append(f'- [{identity}](</{target.as_posix()}>)')
    (output/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(output/'README.md')

if __name__=='__main__':main()
