"""Assemble one logged recognition round at a time; never infer annotations."""
from pathlib import Path
import re


def assemble(archive):
    archive = Path(archive)
    log = archive / 'log' / f'daily_{archive.name}.log'
    if not log.is_file():
        return []
    results = []
    seen = set()
    for line in log.read_text(encoding='utf-8').splitlines():
        if '[recognition_materials] ' not in line:
            continue
        fields = dict(re.findall(r'(\w+)=([^\s]+)', line.split('[recognition_materials] ', 1)[1]))
        prefix = fields.get('prefix', '')
        if not re.fullmatch(r'(shimen|zhuagui)_(find|puzzle)_r\d+_', prefix) or prefix in seen:
            continue
        seen.add(prefix)
        expected_task, expected_kind = prefix.split('_')[:2]
        item = dict(task=fields.get('task'), kind=fields.get('kind'), account=fields.get('account'),
                    prefix=prefix, status='incomplete', reason='capture_not_verified', images=[])
        results.append(item)
        if (item['task'], item['kind']) != (expected_task, expected_kind):
            continue
        pages = sorted((archive / 'res').glob(f'daily_{archive.name}_*_{prefix}p[0-9][0-9].png'),
                       key=lambda path: int(re.search(r'p(\d+)\.png$', path.name)[1]))
        item['images'] = [p.relative_to(archive).as_posix() for p in pages]
        if fields.get('from_first') != 'true' or fields.get('captured') != 'true':
            continue
        expected = fields.get('pages', '')
        if not expected.isdigit() or len(pages) != int(expected) or not pages:
            continue
        indexes = [int(re.search(r'p(\d+)\.png$', p.name)[1]) for p in pages]
        if indexes != list(range(1, len(pages) + 1)):
            item['reason'] = 'missing_or_duplicate_page'
            continue
        try:
            from PIL import Image
            for path in pages:
                with Image.open(path) as image:
                    if image.size != (900, 1600):
                        raise ValueError('full original image required')
            if item['kind'] == 'puzzle':
                if len(pages) != 1:
                    raise ValueError('one original puzzle board required')
            else:
                from scripts.perception.lib.task_review import compose_rows
                cases = {i: {'id': f'{prefix}p{i:02}', 'image': str(path)}
                         for i, path in enumerate(pages, 1)}
                strip, records, header, _ = compose_rows(cases, image_resolver=lambda case: Path(case['image']))
                item['item_height'] = strip.height
                if strip.height < 2760:
                    item['reason'] = 'insufficient_unique_rows'
                    continue
                if any(record['alignment'] and not record['alignment']['accepted'] for record in records):
                    item['reason'] = 'page_seam_not_verified'
                    continue
                stitched = Image.new('RGB', (900, 535 + strip.height), (0, 0, 0))
                stitched.paste(header.crop((0, 0, 900, 535)), (0, 0))
                stitched.paste(strip, (63, 535))
                output = archive / f'{prefix}stitched.png'
                stitched.save(output)
                item['stitched'] = output.relative_to(archive).as_posix()
            item.update(status='awaiting_visual_review', reason='check_first_last_and_seams')
        except (OSError, ValueError) as exc:
            item['reason'] = type(exc).__name__
    return results
