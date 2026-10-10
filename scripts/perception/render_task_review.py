"""Render every captured task round with scrolling overlap removed."""
import json
import argparse
import hashlib
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.perception.lib.corpus import image_path, load_cases
from scripts.perception.lib.task_review import ALIGNMENT_METHOD, VIEWPORT, rounds, scroll_offset

FOLDER = ROOT / '.tmp/annotation/zhuagui/tasks'
FONT = 'C:/Windows/Fonts/msyh.ttc'


def compose(pages, cached_records=None):
    images = [(page, case, Image.open(image_path(case)).convert('RGB'))
              for page, case in sorted(pages.items()) if case['truth'].get('page', {}).get('value') == 'find']
    segments, records, previous, position = [], [], None, 0
    height = 0
    cache_matches = (cached_records is not None
                     and [(r['page'],r['sha256']) for r in cached_records] == [(p,c['sha256']) for p,c,_ in images]
                     and all(tuple(r['viewport']) == VIEWPORT and
                             (r['alignment'] is None or r['alignment']['method'] == ALIGNMENT_METHOD)
                             for r in cached_records))
    for capture_index, (page, case, frame) in enumerate(images):
        crop = frame.crop(VIEWPORT)
        alignment = (cached_records[capture_index]['alignment'] if cache_matches
                     else None if previous is None else scroll_offset(previous, crop))
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
            segments.append((height if source_start else position, crop.crop((0, source_start, crop.width, crop.height))))
            height = max(height, position + crop.height)
        records.append({'page': page, 'case_id': case['id'], 'sha256': case['sha256'],
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
    return strip, records, images[0][2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--topic', help='Regenerate one category; retain other category entries')
    parser.add_argument('--output', type=Path, help='Absolute output directory within debug-runs')
    args = parser.parse_args()
    output=(args.output or ROOT/'debug-runs'/datetime.now().strftime('%Y%m%d_%H%M%S')/'annotation-review/tasks').resolve()
    if not output.is_relative_to((ROOT/'debug-runs').resolve()):
        parser.error('Review output must remain within debug-runs')
    output.mkdir(parents=True, exist_ok=True)
    FOLDER.mkdir(parents=True, exist_ok=True)
    cases = load_cases('zhuagui')
    grouped = rounds(cases)
    old_categories = json.loads((FOLDER/'rounds.json').read_text(encoding='utf-8'))['categories'] if (FOLDER/'rounds.json').exists() else {}
    cache = {entry['id']:entry['captures'] for entries in old_categories.values() for entry in entries}
    annotations = json.loads((FOLDER / 'annotations.json').read_text(encoding='utf-8'))
    round_file = FOLDER/'round_annotations.json'
    round_annotations = json.loads(round_file.read_text(encoding='utf-8')) if round_file.exists() else {}
    approved_file=ROOT/'testdata/zhuagui/rounds.json'
    approved_rounds={r['id']:r for r in json.loads(approved_file.read_text(encoding='utf-8'))['rounds']} if approved_file.exists() else {}
    font, small = ImageFont.truetype(FONT, 23), ImageFont.truetype(FONT, 18)
    catalog, index = {}, ['# 按题目类别、采集轮次审核', '',
        '同一轮的列表已按像素内容对齐，去掉滑动重叠和到底后的重复截图；保留原截图哈希、坐标映射及合并误差。原始截图不删除。',
        '一轮答案是集合，支持多个物品；跨轮保留不同输入。橙框是 AI 答案提案，青框是疑似候选，绿色已有验证。未标框不代表错误，答案集合完整性仍待审核。',
        '截图数量、唯一候选数量、答案数量分别记录；七张截图不能证明采集完整。尚未对齐的片段保留间隔，并标为待检查。', '']
    for (run, round_number), pages in sorted(grouped.items()):
        topics = {(case['truth'].get('question', {}).get('value') or {}).get('target') for case in pages.values()}
        topics.discard(None)
        if len(topics) != 1:
            raise ValueError(f'A capture round needs one independently annotated question: {run}/{round_number}')
        topic = next(iter(topics))
        if args.topic and topic != args.topic:
            continue
        task_id = f'{run}_r{round_number:03d}'
        result = compose(pages, cache.get(task_id))
        if result is None:
            continue
        strip, records, first = result
        folder = output / topic
        folder.mkdir(exist_ok=True)
        header_height = 420
        sheet = Image.new('RGB', (900, header_height + strip.height + 50), '#18212d')
        draw = ImageDraw.Draw(sheet)
        draw.text((16, 8), f'{topic} | {task_id}', font=font, fill='white')
        duplicate_count = sum(record['redundant_capture'] for record in records)
        unknown = sum(record['alignment'] is not None and not record['alignment']['accepted'] for record in records)
        draw.text((16, 42), f'{len(records)} 张寻物截图，移除 {duplicate_count} 张重复底部截图；未对齐 {unknown}', font=small, fill='#e6c775')
        draw.text((16, 72), '橙：答案提案   青：疑似候选   绿：已有验证；漏标仍可补充', font=small, fill='white')
        sheet.paste(first.crop((15, 174, 887, 465)), (14, 105))
        sheet.paste(strip, (80, header_height))
        for row, y in enumerate(range(3, strip.height, 156), 1):
            draw.text((10, header_height + y + 45), f'R{row:02d}', font=small, fill='#a1b0c3')
        for column in range(5):
            draw.text((125 + column * 156, header_height - 24), f'C{column+1}', font=small, fill='white')
        for record in records:
            if record['alignment'] is not None and not record['alignment']['accepted']:
                gap_y = header_height + record['list_origin_y'] - 60
                draw.rectangle((80, gap_y, 846, gap_y+59), fill='#512d32')
                draw.text((90, gap_y+8), '采集缺口：此处无法对齐，后续行号仅用于图内定位', font=small, fill='#ffcccc')
        candidates, seen = [], set()
        mapped_marks = []
        for mark in round_annotations.get(task_id, []):
            x1 = 63 + round((mark['column']-1)*156.5)
            global_top = 3 + round((mark['row']-1)*155.8)
            suitable = [record for record in records if global_top >= record['list_origin_y'] and global_top+139 <= record['list_origin_y']+875]
            if not suitable:
                raise ValueError(f'Candidate has no full source rectangle: {task_id}/{mark}')
            record = min(suitable, key=lambda r:abs(global_top-r['list_origin_y']-437))
            y1 = global_top-record['list_origin_y']+VIEWPORT[1]
            mapped_marks.append((record, {**mark, 'region':[x1,y1,x1+139,y1+139],
                                         'status':mark.get('status','proposed'),'reason':mark.get('reason','AI independent visual review of full deduplicated round')}))
        for record in records:
            if task_id not in round_annotations:
                mapped_marks.extend((record,mark) for mark in annotations.get(task_id, {}).get(str(record['page']), []))
        for record, mark in mapped_marks:
                x1, y1, x2, y2 = mark['region']
                bbox = [x1 - VIEWPORT[0], y1 - VIEWPORT[1] + record['list_origin_y'],
                        x2 - VIEWPORT[0], y2 - VIEWPORT[1] + record['list_origin_y']]
                if bbox[1] < 0 or bbox[3] > strip.height:
                    continue
                approved=next((c for c in approved_rounds.get(task_id,{}).get('candidate_annotations',[])
                               if c['status']=='user_verified' and c['stitched_region']==bbox),None)
                if approved:
                    mark={**mark,'status':'verified','reason':approved['source']}
                identity = (round((bbox[0]+bbox[2])/2/156), round((bbox[1]+bbox[3])/2/156))
                if identity in seen:
                    continue
                seen.add(identity)
                item_id = f'A{len(candidates)+1}'
                candidate = {**mark, 'id': item_id, 'stitched_region': bbox,
                             'source_page': record['page'], 'case_id': record['case_id']}
                candidates.append(candidate)
                color = {'proposed': '#ff8900', 'uncertain': '#00b8db', 'verified': '#15b96c'}[mark['status']]
                box = [bbox[0]+80, bbox[1]+header_height, bbox[2]+80, bbox[3]+header_height]
                draw.rectangle(box, outline=color, width=5)
                draw.rectangle((box[0],box[1],box[0]+55,box[1]+28), fill=color)
                draw.text((box[0]+4,box[1]),item_id,font=font,fill='black')
        target = folder / f'{task_id}.png'
        sheet.save(target, compress_level=3)
        round_case = {'id': task_id, 'topic': topic, 'captures': records,
                      'input_sha256': hashlib.sha256(strip.tobytes()).hexdigest(),
                      'excluded_captures': [case['id'] for case in pages.values() if case['truth'].get('page', {}).get('value') != 'find'],
                      'review_image': target.as_posix(),
                      'collection_status': 'end_repeated' if duplicate_count and not unknown else 'extent_unconfirmed',
                      'candidate_annotations': candidates,
                      'visual_review': 'ai_reviewed' if task_id in round_annotations else 'not_reviewed',
                      'answer_set': {'item_ids': [c['id'] for c in candidates if c['status'] != 'uncertain'],
                                     'status': 'proposed', 'exhaustive': False,
                                     'scope': 'all acceptable item instances in this round; no fixed cardinality'}}
        if candidates and all(c['status']=='verified' for c in candidates):
            round_case['answer_set']['status']='user_verified'
            round_case['answer_set']['source']=approved_rounds[task_id]['answer_set']['source']
        catalog.setdefault(topic, []).append(round_case)
        labels = '\n'.join(f'- {c["id"]}：R{c.get("row", "?")}C{c.get("column", "?")}，{c["label"]}（{c["status"]}）。' for c in candidates)
        if not candidates:
            labels = '本轮已查看，未识别出明确答案；不表示题目没有正确答案。'
        sources = '\n'.join(f'- 第 {r["page"]} 张：[原始截图](</{image_path(pages[r["page"]]).as_posix()}>)。' for r in records)
        review_note='已标位置经用户审核；未标区域及未采画面不自动视为负例。' if task_id in approved_rounds else '答案集合仍待审核，可能有漏标。'
        (folder / f'{task_id}.md').write_text(f'# {topic}：{task_id}\n\n![去重长图](</{target.as_posix()}>)\n\n{labels}\n\n{review_note}\n\n## 原始证据\n\n{sources}\n', encoding='utf-8')
    if args.topic and (FOLDER/'rounds.json').exists():
        previous_catalog = old_categories
        previous_catalog.pop(args.topic, None)
        catalog = {**previous_catalog, **catalog}
    for topic, entries in catalog.items():
        answer_count = sum(len(e['answer_set']['item_ids']) for e in entries)
        uncertain_count = sum(c['status'] == 'uncertain' for e in entries for c in e['candidate_annotations'])
        lines = [f'# {topic}：{len(entries)} 轮输入', '', f'答案位置 {answer_count} 个，疑似候选 {uncertain_count} 个。绿框已获用户审核，橙框是提案，青框待确认；均不代表已验证的算法识别结果。', '',
                 '每轮保留全部画面和多个答案位置。零提案表示尚未找到明确答案，不表示真值为空；采集缺口会在图中注明。', '',
                 '|轮次|寻物截图|重复底部截图|答案提案 / 疑似|审核长图与标注|', '|---|---|---|---|---|']
        wine_file=ROOT/'testdata/zhuagui/annotation-history/wine_review.json'
        if topic == '酒' and wine_file.exists():
            wine_review = json.loads(wine_file.read_text(encoding='utf-8'))
            names = '、'.join(c['name'] for c in wine_review['categories'])
            pending = '、'.join(c['name'] for c in wine_review['categories'] if c['appearance_status'] == 'pending')
            lines[2:2] = [f'用户确认的酒类范围：{names}。', '',
                          f'尚待确认具名图标：{pending or "无"}；未按名字猜测外观。', '']
        for entry in entries:
            target = Path(entry['review_image'])
            if not target.is_absolute():
                target=ROOT/'debug-runs/20261010_174000/annotation-review/tasks'/target
            answer_count = len(entry['answer_set']['item_ids'])
            uncertain_count = sum(c['status'] == 'uncertain' for c in entry['candidate_annotations'])
            lines.append(f'|{entry["id"]}|{len(entry["captures"])}|{sum(c["redundant_capture"] for c in entry["captures"])}|{answer_count} / {uncertain_count}|[查看](</{target.with_suffix(".md").as_posix()}>)|')
        category_index = output / topic / 'README.md'
        category_index.parent.mkdir(parents=True, exist_ok=True)
        category_index.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        index.append(f'- [{topic}：{len(entries)} 轮](</{category_index.as_posix()}>)')
    (FOLDER/'rounds.json').write_text(json.dumps({'schema_version': 2, 'categories': catalog},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (output/'README.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
    print(json.dumps({'rounds':sum(map(len,catalog.values())),'categories':{k:len(v) for k,v in catalog.items()},
                      'unregistered':sum(c['alignment'] is not None and not c['alignment']['accepted'] for v in catalog.values() for r in v for c in r['captures'])},ensure_ascii=True))


if __name__ == '__main__':
    main()
